import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


class AudioProcessingError(Exception):
    pass


def require_program(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AudioProcessingError(
            f"Required program `{name}` was not found. Install FFmpeg and ensure ffmpeg/ffprobe are on PATH."
        )
    return path


def run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise AudioProcessingError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error").strip()
        raise AudioProcessingError(detail[-1800:])


def get_duration_seconds(path: Path) -> float:
    ffprobe = require_program("ffprobe")
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioProcessingError(f"Couldn't read audio duration: {result.stderr[-800:]}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise AudioProcessingError("Couldn't determine the audio duration.") from exc


def apply_user_macro_approximation(source: Path, destination: Path) -> None:
    """
    Approximation of the non-SC4 commands in the supplied Audacity macro.
    It is NOT guaranteed to be bit-for-bit or perceptually identical to Audacity:
      - FilterCurve: recorded point data is sparse/ambiguous in the exported file.
      - BassAndTreble: mapped to FFmpeg bass/treble filters plus gain.
      - MixAndRender: rendered by writing the filter output to WAV.
    Test and tune against Audacity exports before relying on exact sound matching.
    """
    ffmpeg = require_program("ffmpeg")

    # The macro file has FilterCurve values f0=420.05786, f1=22050,
    # v0=v1=16.418339. Treat this as a high-frequency boost approximation.
    # Bass/Treble commands are applied sequentially, matching macro order.
    filters = [
        "highshelf=f=420.05786:g=16.418339",
        "bass=g=-5",
        "treble=g=5",
        "volume=17.5dB",
        "bass=g=-6.5",
    ]
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn",
        "-af", ",".join(filters),
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(destination),
    ]
    run(cmd)


def tempo_filter_for_audacity_percent(percent: int) -> str:
    if not -14 <= percent <= 14:
        raise AudioProcessingError("Tempo must be between -14 and +14.")
    # Audacity Change Tempo changes duration while attempting to preserve pitch.
    # FFmpeg atempo uses a factor; +7 means 1.07x tempo, -7 means 0.93x tempo.
    factor = 1.0 + (percent / 100.0)
    return f"atempo={factor:.6f}"


def normalize_for_concat(source: Path, destination: Path, audio_filter: str | None) -> None:
    ffmpeg = require_program("ffmpeg")
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn",
    ]
    if audio_filter:
        cmd += ["-af", audio_filter]
    cmd += [
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(destination)
    ]
    run(cmd)


def concatenate_audio(pieces: Iterable[Path], destination: Path) -> None:
    ffmpeg = require_program("ffmpeg")
    pieces = list(pieces)
    if not pieces:
        raise AudioProcessingError("No audio clips were provided.")
    # Use the concat filter rather than stream-copy; all pieces are normalized WAVs.
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for piece in pieces:
        cmd += ["-i", str(piece)]
    streams = "".join(f"[{i}:a]" for i in range(len(pieces)))
    filter_complex = f"{streams}concat=n={len(pieces)}:v=0:a=1[out]"
    cmd += [
        "-filter_complex", filter_complex, "-map", "[out]",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(destination)
    ]
    run(cmd)


def convert_ogg_q0_then_mp3(source: Path, ogg_path: Path, mp3_path: Path) -> None:
    ffmpeg = require_program("ffmpeg")
    # OGG Vorbis quality scale: q=0 is the lowest-quality setting.
    run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-c:a", "libvorbis", "-q:a", "0", str(ogg_path)
    ])
    # Re-open/decode the newly encoded OGG and export MP3.
    run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(ogg_path), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3_path)
    ])
