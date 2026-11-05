"""Extract OpenJLPT's graded vocabulary from the pinned archive into SQLite."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "data" / "downloads" / "learning"
DATABASE = ROOT / "data" / "reference" / "jlpt_vocab.sqlite3"
OPENJLPT_COMMIT = "0d1d3410bec90bd4098a7c72de820543cb4f707c"
ARCHIVE = DOWNLOADS / f"openjlpt-{OPENJLPT_COMMIT}.zip"


def main() -> None:
    if not ARCHIVE.exists():
        raise SystemExit(f"{ARCHIVE} 가 없습니다. 먼저 자료를 임포트하세요.")
    rows = []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for level_index in range(1, 6):
            level = f"N{level_index}"
            path = next(
                name
                for name in archive.namelist()
                if name.endswith(f"data/json/vocab/n{level_index}.json")
            )
            for word in json.loads(archive.read(path)):
                example = (word.get("examples") or [{}])[0]
                rows.append(
                    (
                        word["id"],
                        word["word"],
                        word["reading"],
                        level,
                        word.get("jmdict_id"),
                        json.dumps(word.get("meanings", []), ensure_ascii=False),
                        example.get("ja", ""),
                        example.get("en", ""),
                    )
                )
    temporary = DATABASE.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute(
                "CREATE TABLE jlpt_vocab ("
                "id TEXT PRIMARY KEY, word TEXT NOT NULL, reading TEXT NOT NULL,"
                " level TEXT NOT NULL, jmdict_id INTEGER, meanings_json TEXT NOT NULL,"
                " example_ja TEXT NOT NULL DEFAULT '',"
                " example_en TEXT NOT NULL DEFAULT '')"
            )
            connection.executemany(
                "INSERT INTO jlpt_vocab VALUES (?,?,?,?,?,?,?,?)", rows
            )
            connection.execute("CREATE INDEX jlpt_vocab_level ON jlpt_vocab(level)")
        temporary.replace(DATABASE)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print(f"Created {DATABASE} ({len(rows):,} words)")


if __name__ == "__main__":
    main()
