"""Download the pinned Kanjium pitch-accent list into a local lookup database."""

from __future__ import annotations

import hashlib
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "data" / "downloads"
DATABASE = ROOT / "data" / "reference" / "kanjium.sqlite3"
COMMIT = "685d4d723d6d20bf9beb169103aeac188eb067ad"
URL = (
    "https://raw.githubusercontent.com/mifunetoshiro/kanjium/"
    f"{COMMIT}/data/source_files/raw/accents.txt"
)
SHA256 = "8bd0dd127dab32ceec94cb03ab1ba6b68858ea73421dfa1731af2f373deb4f20"
NAME = "kanjium-accents.txt"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download() -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    path = DOWNLOADS / NAME
    if path.exists() and _digest(path.read_bytes()) == SHA256:
        return path
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    if _digest(data) != SHA256:
        raise SystemExit("Kanjium accents.txt의 SHA-256이 고정값과 다릅니다.")
    path.write_bytes(data)
    return path


def main() -> None:
    source = download()
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
            continue
        rows.append((parts[0], parts[1], parts[2]))
    temporary = DATABASE.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute(
                "CREATE TABLE pitch_accents ("
                "word TEXT NOT NULL, reading TEXT NOT NULL, accents TEXT NOT NULL)"
            )
            connection.executemany("INSERT INTO pitch_accents VALUES (?,?,?)", rows)
            connection.execute("CREATE INDEX pitch_accents_word ON pitch_accents(word)")
            connection.execute(
                "CREATE INDEX pitch_accents_reading ON pitch_accents(reading)"
            )
        temporary.replace(DATABASE)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print(f"Created {DATABASE} ({len(rows):,} accent rows)")


if __name__ == "__main__":
    main()
