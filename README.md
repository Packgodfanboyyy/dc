# Discord Audio Processing Bot

One slash command: `/audio main_audio tempo optional_intro`.

- `main_audio` is required.
- `tempo` is optional, defaults to `0`, and must be between `-14` and `+14`.
- `optional_intro` is optional and must be no longer than 10 seconds.

The command applies the macro-like processing and tempo change (if nonzero) only to the main audio, then joins `1.mp3`, optional intro, processed main audio, and `2.mp3`. It then exports the complete mix as OGG Vorbis quality 0, reopens/decodes the OGG, exports MP3, and sends it to Discord.

## Important note about macro fidelity

The supplied macro had these non-SC4 commands:
- `FilterCurve` with `f0=420.05786`, `f1=22050`, `v0=16.418339`, `v1=16.418339`
- `MixAndRender`
- `BassAndTreble` with Bass=-5, Gain=17.5, Treble=5
- `BassAndTreble` with Bass=-6.5, Gain=0, Treble=0

The bot uses an FFmpeg approximation of those effects in `audio_processing.py`. This is **not guaranteed to sound identical to Audacity**. The exported macro contains limited curve information and does not capture all effect implementation details. If you need an exact match, the next step is to run the macro in Audacity batch mode / scripting on the server, or compare test exports and tune the FFmpeg filter chain. The SC4 step is intentionally omitted.

## Requirements

- Python 3.10 or newer
- FFmpeg installed and `ffmpeg` plus `ffprobe` available on PATH
- Discord bot application with the `applications.commands` scope and bot permission to send messages/attach files
- `1.mp3` and `2.mp3` in this folder
- Network access from the host to Discord

## Setup

1. Install FFmpeg for your operating system and make sure `ffmpeg -version` and `ffprobe -version` work in a terminal.
2. Put your clips named exactly `1.mp3` and `2.mp3` next to `bot.py`.
3. Create a Discord application at https://discord.com/developers/applications, add a bot, and invite it to your server with `applications.commands` and permissions to send messages and attach files.
4. Copy `.env.example` to `.env` and enter your bot token. Never share the token or upload `.env`.
5. Install dependencies:

   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
6. Start the bot:

   ```bash
   python bot.py
   ```

If you set `GUILD_ID` in `.env` to your test server's ID, commands sync to that server for faster development. Leave it blank to sync globally; global command propagation can take time.

## Usage

- `/intro_adder`: attach main audio; optionally attach an intro file (10 seconds max).
- `/tempo_adjustment`: attach main audio and select a tempo value from -14 to +14. Here +7 means 7% faster tempo and -7 means 7% slower tempo, while attempting to preserve pitch. This is intended to match the percentage meaning of Audacity Change Tempo; time-stretch algorithms may sound different from Audacity.

## Limits and safety

- Default maximum input upload: 20 MB
- Default maximum main audio duration: constant is documented but not currently enforced; add a duration check if you want a hard cap.
- Discord's attachment size limit varies by account/server; adjust `MAX_OUTPUT_BYTES` in `bot.py` to your actual limit.
- Keep the bot token private. Do not commit `.env` to a public repository.
- Process only audio you have permission to use. This bot does not bypass platform moderation or copyright restrictions.


## Fix for Discord's 25-choice limit

The tempo command accepts an integer and validates it is between -14 and +14, instead of registering 29 separate preset choices. This avoids Discord's 25-choice command limit. Users type the desired integer into the `tempo` field.


## Unified command

The bot now registers a single slash command, `/audio`, with a required main audio upload and optional `tempo` and `optional_intro` parameters. Tempo defaults to 0. Remove/restart the bot and wait for the command sync log; old commands may take a little time to disappear from Discord's UI.
