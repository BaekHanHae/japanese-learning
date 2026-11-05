"""macOS text-to-speech with a cached WAV file per sentence."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "private" / "audio"
VOICE = "Kyoko"


def speech_wav(text: str) -> Path:
    """Return a cached WAV for the text, synthesizing it with macOS `say`."""
    key = hashlib.sha256(f"{VOICE}:{text}".encode()).hexdigest()[:32]
    target = CACHE / f"{key}.wav"
    if target.exists():
        return target
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        aiff = Path(directory) / "speech.aiff"
        subprocess.run(
            ["say", "-v", VOICE, "-o", str(aiff), text],
            check=True,
            capture_output=True,
            timeout=20,
        )
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff), str(target)],
            check=True,
            capture_output=True,
            timeout=20,
        )
    return target
