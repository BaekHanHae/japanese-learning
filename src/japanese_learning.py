"""Import and search a local JMdict vocabulary database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "downloads"
DATABASE_PATH = PROJECT_ROOT / "data" / "reference" / "jmdict.sqlite3"

# This is a pinned snapshot. Update the version, URL, and checksum together.
DATA_VERSION = "3.6.2+20261005200550"
ARCHIVE_URL = (
    "https://github.com/scriptin/jmdict-simplified/releases/download/"
    "3.6.2%2B20261005200550/"
    "jmdict-eng-common-3.6.2%2B20261005200550.json.zip"
)
ARCHIVE_SHA256 = "956cb65b95d12d2b81fa550716d53163dbd3c70ca171a9c7dce97d7238c9d87a"


def download_archive() -> Path:
    """Download the pinned data archive and verify its published checksum."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = DOWNLOAD_DIR / f"jmdict-eng-common-{DATA_VERSION}.json.zip"

    if not archive_path.exists():
        request = urllib.request.Request(
            ARCHIVE_URL,
            headers={"User-Agent": "japanese-learning-personal-project"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            archive_path.write_bytes(response.read())

    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual_hash != ARCHIVE_SHA256:
        archive_path.unlink(missing_ok=True)
        raise ValueError(
            "The downloaded dictionary archive did not match its expected "
            "SHA-256 checksum. The file was removed; check the pinned release."
        )

    return archive_path


def create_database(database_path: Path = DATABASE_PATH) -> int:
    """Import the source JSON into SQLite and return the entry count."""
    archive_path = download_archive()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        json_names = [name for name in archive.namelist() if name.endswith(".json")]
        if len(json_names) != 1:
            raise ValueError(
                "Expected exactly one JSON file in the dictionary archive."
            )
        source: dict[str, Any] = json.loads(archive.read(json_names[0]))

    words = source.get("words")
    if not isinstance(words, list):
        raise ValueError("The dictionary JSON does not contain a words list.")

    temporary_path = database_path.with_suffix(".tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary_path) as connection:
            connection.execute(
                """
                CREATE TABLE entries (
                    id TEXT PRIMARY KEY,
                    kanji_json TEXT NOT NULL,
                    kana_json TEXT NOT NULL,
                    senses_json TEXT NOT NULL,
                    search_text TEXT NOT NULL
                )
                """
            )
            rows = []
            for word in words:
                kanji = word.get("kanji", [])
                kana = word.get("kana", [])
                senses = word.get("sense", [])
                search_terms = [item.get("text", "") for item in [*kanji, *kana]]
                search_terms.extend(
                    gloss.get("text", "")
                    for sense in senses
                    for gloss in sense.get("gloss", [])
                )
                rows.append(
                    (
                        str(word["id"]),
                        json.dumps(kanji, ensure_ascii=False),
                        json.dumps(kana, ensure_ascii=False),
                        json.dumps(senses, ensure_ascii=False),
                        " ".join(search_terms).casefold(),
                    )
                )

            connection.executemany(
                """
                INSERT INTO entries (id, kanji_json, kana_json, senses_json, search_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("source", "JMdict / EDRDG"), ("version", DATA_VERSION)],
            )
        temporary_path.replace(database_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return len(words)


def search_database(query: str, database_path: Path = DATABASE_PATH) -> int:
    """Print matching entries and return the number of results."""
    if not database_path.exists():
        raise FileNotFoundError(
            "The local dictionary is missing. Run 'import-dictionary' first."
        )

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, kanji_json, kana_json, senses_json
            FROM entries
            WHERE search_text LIKE ?
            ORDER BY id
            LIMIT 20
            """,
            (f"%{query.casefold()}%",),
        ).fetchall()

    for row in rows:
        kanji = json.loads(row["kanji_json"])
        kana = json.loads(row["kana_json"])
        senses = json.loads(row["senses_json"])
        forms = [item["text"] for item in kanji]
        readings = [item["text"] for item in kana]
        glosses = [
            gloss["text"]
            for sense in senses
            for gloss in sense.get("gloss", [])
            if gloss.get("lang") == "eng"
        ]
        print(f"{', '.join(forms) or ', '.join(readings)} [{', '.join(readings)}]")
        print(f"  {', '.join(glosses)}")

    print("Source: JMdict, Electronic Dictionary Research and Development Group")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("import-dictionary", help="Download and import JMdict")
    search_parser = subparsers.add_parser("search", help="Search the local dictionary")
    search_parser.add_argument("query", help="Japanese word, reading, or English gloss")
    args = parser.parse_args()

    if args.command == "import-dictionary":
        count = create_database()
        print(f"Imported {count:,} entries into {DATABASE_PATH}")
    elif args.command == "search":
        count = search_database(args.query)
        if count == 0:
            print("No matching entries found.")


if __name__ == "__main__":
    main()
