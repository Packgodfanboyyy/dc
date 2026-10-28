import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from audio_processing import (
    AudioProcessingError,
    apply_user_macro_approximation,
    concatenate_audio,
    convert_ogg_q0_then_mp3,
    get_duration_seconds,
    normalize_for_concat,
    tempo_filter_for_audacity_percent,
)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()

ROOT = Path(__file__).resolve().parent
FIXED_INTRO = ROOT / "1.mp3"
FIXED_OUTRO = ROOT / "2.mp3"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_MAIN_DURATION = 300  # seconds; adjust to your needs
MAX_INTRO_SECONDS = 10
MAX_OUTPUT_BYTES = 24 * 1024 * 1024  # Discord upload limit varies by account/server

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("audio-bot")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def validate_upload(attachment: discord.Attachment, label: str) -> None:
    if attachment.size > MAX_UPLOAD_BYTES:
        raise AudioProcessingError(
            f"{label} is too large. The current bot limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    suffix = Path(attachment.filename).suffix.lower()
    if suffix not in {".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a", ".aac", ".opus", ".webm"}:
        raise AudioProcessingError(
            f"{label} has an unsupported file extension (`{suffix or 'none'}`). "
            "Use MP3, WAV, OGG, FLAC, M4A, AAC, OPUS, or WEBM."
        )


async def save_attachment(attachment: discord.Attachment, path: Path) -> None:
    await attachment.save(path)


async def process_job(
    interaction: discord.Interaction,
    main_attachment: discord.Attachment,
    optional_intro: discord.Attachment | None,
    tempo_percent: int,
    include_optional_intro: bool,
) -> None:
    if not TOKEN:
        await interaction.followup.send("Bot token is missing. Set `DISCORD_TOKEN` in `.env`.", ephemeral=True)
        return

    if not FIXED_INTRO.is_file() or not FIXED_OUTRO.is_file():
        await interaction.followup.send(
            "I couldn't find `1.mp3` and/or `2.mp3` in the bot folder. Add both files and restart the bot.",
            ephemeral=True,
        )
        return

    try:
        validate_upload(main_attachment, "Main audio")
        if include_optional_intro and optional_intro is not None:
            validate_upload(optional_intro, "Optional intro")
    except AudioProcessingError as exc:
        await interaction.response.send_message(f"Invalid upload: {exc}", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    try:
        with tempfile.TemporaryDirectory(prefix="discord-audio-") as tmp:
            work = Path(tmp)
            main_in = work / f"main_input{Path(main_attachment.filename).suffix.lower()}"
            main_processed = work / "main_processed.wav"
            intro_fixed = work / "fixed_intro.wav"
            outro_fixed = work / "fixed_outro.wav"
            optional_in = work / "optional_intro_input"
            optional_wav = work / "optional_intro.wav"
            final_mix = work / "combined.wav"
            ogg_file = work / "combined_q0.ogg"
            mp3_file = work / "result.mp3"

            await save_attachment(main_attachment, main_in)
            main_duration = await asyncio.to_thread(get_duration_seconds, main_in)
            if main_duration > MAX_MAIN_DURATION:
                raise AudioProcessingError(
                    f"Main audio is {main_duration:.1f} seconds long. "
                    f"Maximum is {MAX_MAIN_DURATION} seconds."
                )

            # Apply the remaining macro-like effects to ONLY the main audio.
            # See README for why this is an approximation of Audacity's effects.
            await asyncio.to_thread(apply_user_macro_approximation, main_in, main_processed)

            # Tempo change is applied after the macro, and only to the main audio.
            if tempo_percent != 0:
                tempo_processed = work / "main_tempo.wav"
                await asyncio.to_thread(
                    normalize_for_concat,
                    main_processed,
                    tempo_processed,
                    tempo_filter_for_audacity_percent(tempo_percent),
                )
                main_processed = tempo_processed

            # Prepare fixed clips without applying the macro or tempo change.
            await asyncio.gather(
                asyncio.to_thread(normalize_for_concat, FIXED_INTRO, intro_fixed, None),
                asyncio.to_thread(normalize_for_concat, FIXED_OUTRO, outro_fixed, None),
            )

            pieces = [intro_fixed]
            if include_optional_intro and optional_intro is not None:
                optional_in = work / f"optional_intro{Path(optional_intro.filename).suffix.lower()}"
                await save_attachment(optional_intro, optional_in)
                duration = await asyncio.to_thread(get_duration_seconds, optional_in)
                if duration > MAX_INTRO_SECONDS:
                    raise AudioProcessingError(
                        f"Optional intro is {duration:.2f} seconds long. Maximum is {MAX_INTRO_SECONDS} seconds."
                    )
                await asyncio.to_thread(normalize_for_concat, optional_in, optional_wav, None)
                pieces.append(optional_wav)

            pieces.extend([main_processed, outro_fixed])
            await asyncio.to_thread(concatenate_audio, pieces, final_mix)

            # Required pipeline: final mix -> OGG Vorbis q=0 -> decode/reimport -> MP3.
            await asyncio.to_thread(convert_ogg_q0_then_mp3, final_mix, ogg_file, mp3_file)

            if mp3_file.stat().st_size > MAX_OUTPUT_BYTES:
                raise AudioProcessingError(
                    "The finished MP3 exceeds the bot's configured upload limit. "
                    "Reduce the input length or lower MAX_OUTPUT_BYTES only if your Discord upload limit allows it."
                )

            await interaction.followup.send(
                content=f"Finished! Tempo adjustment: `{tempo_percent:+d}` (Audacity Change Tempo-style percentage).",
                file=discord.File(mp3_file, filename="processed_audio.mp3"),
            )
    except AudioProcessingError as exc:
        await interaction.followup.send(f"Audio processing failed: {exc}", ephemeral=True)
    except Exception:
        log.exception("Unexpected processing failure")
        await interaction.followup.send(
            "Something went wrong while processing the audio. Check the bot console for details.",
            ephemeral=True,
        )


@bot.event
async def on_ready():
    log.info("Logged in as %s (ID %s)", bot.user, bot.user.id if bot.user else "?")
    try:
        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            log.info("Synced %d command(s) to guild %s", len(synced), GUILD_ID)
        else:
            synced = await bot.tree.sync()
            log.info("Synced %d global command(s)", len(synced))
    except Exception:
        log.exception("Slash-command sync failed")


@bot.tree.command(name="audio", description="Process audio, adjust tempo, and optionally add an intro.")
@app_commands.describe(
    main_audio="The main audio file to process",
    tempo="Optional tempo change from -14 to +14 (default: 0)",
    optional_intro="Optional extra intro clip (maximum 10 seconds)",
)
async def audio(
    interaction: discord.Interaction,
    main_audio: discord.Attachment,
    tempo: int = 0,
    optional_intro: discord.Attachment | None = None,
):
    if not -14 <= tempo <= 14:
        await interaction.response.send_message(
            "Tempo must be between -14 and +14.", ephemeral=True
        )
        return
    await process_job(interaction, main_audio, optional_intro, tempo, True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in your .env file first.")
    bot.run(TOKEN)
