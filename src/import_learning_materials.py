"""Download licensed Japanese learning corpora into a local SQLite database."""

from __future__ import annotations

import bz2
import csv
import hashlib
import io
import json
import sqlite3
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from materials_search import ensure_index

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "data" / "downloads" / "learning"
DATABASE = ROOT / "data" / "reference" / "learning_materials.sqlite3"
USER_SENTENCES_URL = "https://downloads.tatoeba.org/exports/users_sentences.csv"
TATOEBA_DIR = "https://downloads.tatoeba.org/exports/per_language"
BSD_COMMIT = "050fd4241da458377c1ce26b2c31b0af0a20e444"
OPENJLPT_COMMIT = "0d1d3410bec90bd4098a7c72de820543cb4f707c"

FILES = {
    "kftt-data-1.0.tar.gz": (
        "https://www.phontron.com/kftt/download/kftt-data-1.0.tar.gz",
        "fcfcaa670d6d59aa691b0e909c0d7c393852dd2fb1d6310fda9b3282dc6d1638",
    ),
    "jpn_sentences.tsv.bz2": (
        f"{TATOEBA_DIR}/jpn/jpn_sentences.tsv.bz2",
        "dd942845be225766229fa6391cbb7796c6b8bdcaea38809e65720cc406dace93",
    ),
    "eng_sentences.tsv.bz2": (
        f"{TATOEBA_DIR}/eng/eng_sentences.tsv.bz2",
        "5f7ebf552bd3925dfd33236ccb6a210c5ba02b365e4a39964fb658e1209e87d9",
    ),
    "jpn-eng_links.tsv.bz2": (
        f"{TATOEBA_DIR}/jpn/jpn-eng_links.tsv.bz2",
        "b078aebb6b6b1e568fe0cb4683a4ae02e17d23b3a08f8a2b0bbb88e83ec697fa",
    ),
    "sentences_CC0.tar.bz2": (
        "https://downloads.tatoeba.org/exports/sentences_CC0.tar.bz2",
        "ab7bd43d9beda51c77ec62949c74320211d42aec6ab2341b4147f7bc8e704497",
    ),
    "tatoeba_users_sentences.csv": (
        USER_SENTENCES_URL,
        "3c9b65970952869fb70993a7d31db9833ce3711c2f49742286c45e668be2a61e",
    ),
    f"bsd-{BSD_COMMIT}.zip": (
        f"https://codeload.github.com/tsuruoka-lab/BSD/zip/{BSD_COMMIT}",
        "e02bd882c434a621882fc394c1453a686254eb02374fd1ca340191186e358213",
    ),
    f"openjlpt-{OPENJLPT_COMMIT}.zip": (
        f"https://codeload.github.com/evanclan/OpenJLPT/zip/{OPENJLPT_COMMIT}",
        "affcfe5d40b6b3c386d416eb2f210bb9772deb37c5cfd8c7d42b46b5df1cbf13",
    ),
}

CREATE_ITEMS = """
CREATE TABLE learning_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    japanese TEXT NOT NULL,
    english TEXT NOT NULL DEFAULT '',
    reading TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    license TEXT NOT NULL,
    source_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX learning_items_source_kind ON learning_items(source, kind, id);
CREATE INDEX learning_items_level ON learning_items(level, kind);
CREATE TABLE source_manifest (
    source TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    license TEXT NOT NULL,
    attribution TEXT NOT NULL,
    source_url TEXT NOT NULL,
    imported_count INTEGER NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
"""


def download_sources() -> dict[str, str]:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}
    for name, (url, expected) in FILES.items():
        path = DOWNLOADS / name
        if not path.exists():
            print(f"Downloading {name} ...", flush=True)
            request = urllib.request.Request(
                url, headers={"User-Agent": "JapaneseLearningLocal/1.0"}
            )
            temporary = path.with_suffix(path.suffix + ".part")
            digest = hashlib.sha256()
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    with temporary.open("wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError(
                        f"Checksum mismatch for {name}; file retained as .part"
                    )
                temporary.replace(path)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(
                f"Checksum mismatch for {name}; replace the local source file"
            )
        checksums[name] = actual
    return checksums


def row(
    item_id: str,
    source: str,
    source_id: str,
    kind: str,
    japanese: str,
    english: str,
    license_name: str,
    source_url: str,
    *,
    reading: str = "",
    level: str = "",
    context: str = "",
    author: str = "",
    metadata: dict | None = None,
) -> tuple:
    return (
        item_id,
        source,
        source_id,
        kind,
        japanese.strip(),
        english.strip(),
        reading,
        level,
        context,
        author,
        license_name,
        source_url,
        json.dumps(metadata or {}, ensure_ascii=False),
    )


def insert_rows(connection: sqlite3.Connection, rows: Iterable[tuple]) -> int:
    count = 0
    batch = []
    for record in rows:
        batch.append(record)
        if len(batch) >= 2000:
            connection.executemany(
                "INSERT OR IGNORE INTO learning_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
            count += len(batch)
            batch.clear()
    if batch:
        connection.executemany(
            "INSERT OR IGNORE INTO learning_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )
        count += len(batch)
    return count


def read_tsv_bz2(path: Path, wanted: set[str]) -> dict[str, str]:
    result = {}
    with bz2.open(path, "rt", encoding="utf-8", newline="") as stream:
        for line in stream:
            fields = line.rstrip("\n").split("\t", 2)
            if len(fields) == 3 and fields[0] in wanted:
                result[fields[0]] = fields[2]
    return result


def import_tatoeba(connection: sqlite3.Connection) -> int:
    links = []
    japanese_ids = set()
    english_ids = set()
    with bz2.open(
        DOWNLOADS / "jpn-eng_links.tsv.bz2", "rt", encoding="utf-8"
    ) as stream:
        for line in stream:
            fields = line.rstrip("\n").split("\t")
            if len(fields) == 2:
                links.append((fields[0], fields[1]))
                japanese_ids.add(fields[0])
                english_ids.add(fields[1])

    ja_text = read_tsv_bz2(DOWNLOADS / "jpn_sentences.tsv.bz2", japanese_ids)
    en_text = read_tsv_bz2(DOWNLOADS / "eng_sentences.tsv.bz2", english_ids)
    needed = japanese_ids | english_ids

    cc0_ids = set()
    with tarfile.open(DOWNLOADS / "sentences_CC0.tar.bz2", "r:bz2") as archive:
        member = next(item for item in archive.getmembers() if item.isfile())
        source = archive.extractfile(member)
        if source is not None:
            for raw in source:
                fields = raw.decode("utf-8").rstrip("\n").split("\t", 3)
                if len(fields) >= 2 and fields[1] in {"jpn", "eng"}:
                    cc0_ids.add(fields[0])

    authors = {}
    with (DOWNLOADS / "tatoeba_users_sentences.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        for fields in csv.reader(stream, delimiter="\t"):
            if len(fields) >= 2 and fields[1] in needed:
                authors[fields[1]] = fields[0]

    def license_for(sentence_id: str) -> str:
        return "CC0 1.0" if sentence_id in cc0_ids else "CC BY 2.0 FR"

    license_url = "https://creativecommons.org/licenses/by/2.0/fr/"

    def records():
        for ja_id, en_id in links:
            japanese, english = ja_text.get(ja_id, ""), en_text.get(en_id, "")
            if not japanese or not english:
                continue
            license_name = f"JA: {license_for(ja_id)}; EN: {license_for(en_id)}"
            yield row(
                f"tatoeba:{ja_id}:{en_id}",
                "Tatoeba",
                f"{ja_id}:{en_id}",
                "sentence",
                japanese,
                english,
                license_name,
                f"https://tatoeba.org/en/sentences/show/{ja_id}",
                author=f"JA: {authors.get(ja_id, 'unknown')}; EN: {authors.get(en_id, 'unknown')}",
                metadata={
                    "japanese_id": ja_id,
                    "english_id": en_id,
                    "license_url": license_url,
                },
            )

    return insert_rows(connection, records())


def import_kftt(connection: sqlite3.Connection) -> int:
    count = 0
    path = DOWNLOADS / "kftt-data-1.0.tar.gz"
    root = "kftt-data-1.0/data/orig/"
    with tarfile.open(path, "r:gz") as archive:
        for split in ("train", "dev", "test", "tune"):
            ja_member = archive.extractfile(f"{root}kyoto-{split}.ja")
            en_member = archive.extractfile(f"{root}kyoto-{split}.en")
            if ja_member is None or en_member is None:
                raise ValueError(f"Missing KFTT {split} files")
            ja_lines = io.TextIOWrapper(ja_member, encoding="utf-8")
            en_lines = io.TextIOWrapper(en_member, encoding="utf-8")
            count += insert_rows(connection, kftt_records(split, ja_lines, en_lines))
    return count


def kftt_records(split: str, ja_lines: Iterable[str], en_lines: Iterable[str]):
    for line_number, (ja, en) in enumerate(
        zip(ja_lines, en_lines, strict=True), start=1
    ):
        yield row(
            f"kftt:{split}:{line_number}",
            "KFTT",
            f"{split}:{line_number}",
            "sentence",
            ja,
            en,
            "CC BY-SA 3.0",
            "https://www.phontron.com/kftt/",
            context=f"Kyoto Wikipedia · {split}",
            author="NICT / KFTT contributors",
        )


def import_bsd(connection: sqlite3.Connection) -> int:
    archive_path = next(DOWNLOADS.glob("bsd-*.zip"))
    count = 0
    with zipfile.ZipFile(archive_path) as archive:
        for split in ("train", "dev", "test"):
            name = next(
                item for item in archive.namelist() if item.endswith(f"/{split}.json")
            )
            scenarios = json.loads(archive.read(name))
            count += insert_rows(connection, bsd_records(scenarios, split))
    return count


def bsd_records(scenarios: list[dict], split: str):
    for scenario in scenarios:
        for line in scenario.get("conversation", []):
            japanese = line.get("ja_sentence", "").strip()
            english = line.get("en_sentence", "").strip()
            if not japanese or not english:
                continue
            source_id = f"{scenario['id']}:{line.get('no', 0)}"
            yield row(
                f"bsd:{source_id}",
                "BSD",
                source_id,
                "sentence",
                japanese,
                english,
                "CC BY-NC-SA",
                f"https://github.com/tsuruoka-lab/BSD/tree/{BSD_COMMIT}",
                context=f"{scenario.get('tag', split)} · {scenario.get('title', '')}",
                author="University of Tokyo",
                metadata={
                    "ja_speaker": line.get("ja_speaker", ""),
                    "en_speaker": line.get("en_speaker", ""),
                    "split": split,
                },
            )


def import_openjlpt(connection: sqlite3.Connection) -> int:
    archive_path = next(DOWNLOADS.glob("openjlpt-*.zip"))
    count = 0
    base_url = f"https://github.com/evanclan/OpenJLPT/tree/{OPENJLPT_COMMIT}"
    with zipfile.ZipFile(archive_path) as archive:
        for level_index in range(1, 6):
            level = f"N{level_index}"
            grammar_path = next(
                name
                for name in archive.namelist()
                if name.endswith(f"data/json/grammar/n{level_index}.json")
            )
            vocab_path = next(
                name
                for name in archive.namelist()
                if name.endswith(f"data/json/vocab/n{level_index}.json")
            )
            grammar = json.loads(archive.read(grammar_path))
            vocab = json.loads(archive.read(vocab_path))
            count += insert_rows(
                connection,
                openjlpt_records(grammar, vocab, level, level_index, base_url),
            )
    return count


def openjlpt_records(
    grammar: list[dict], vocab: list[dict], level: str, level_index: int, base_url: str
):
    for point in grammar:
        point_id = point["id"]
        yield row(
            f"openjlpt:grammar:{point_id}",
            "OpenJLPT",
            point_id,
            "grammar",
            point["pattern"],
            point.get("meaning", ""),
            "CC BY-SA 4.0",
            f"{base_url}/data/json/grammar/n{level_index}.json",
            reading=point.get("reading", ""),
            level=level,
            context=point.get("formation", ""),
            author="OpenJLPT contributors",
            metadata={
                "romaji": point.get("romaji", ""),
                "notes": point.get("notes", ""),
                "tags": point.get("tags", []),
            },
        )
        for index, example in enumerate(point.get("examples", []), start=1):
            yield row(
                f"openjlpt:grammar:{point_id}:example:{index}",
                "OpenJLPT",
                f"{point_id}:example:{index}",
                "sentence",
                example.get("ja", ""),
                example.get("en", ""),
                "CC BY-SA 4.0",
                f"{base_url}/data/json/grammar/n{level_index}.json",
                reading=example.get("furigana", ""),
                level=level,
                context=f"문법 예문 · {point['pattern']}",
                author="OpenJLPT contributors",
                metadata={
                    "grammar_id": point_id,
                    "tatoeba_id": example.get("tatoeba_id", ""),
                },
            )
    for word in vocab:
        for index, example in enumerate(word.get("examples", []), start=1):
            yield row(
                f"openjlpt:vocab:{word['id']}:example:{index}",
                "OpenJLPT",
                f"{word['id']}:example:{index}",
                "sentence",
                example.get("ja", ""),
                example.get("en", ""),
                "CC BY-SA 4.0",
                f"{base_url}/data/json/vocab/n{level_index}.json",
                reading=example.get("furigana", ""),
                level=level,
                context=f"어휘 예문 · {word['word']} ({word['reading']})",
                author="OpenJLPT contributors",
                metadata={
                    "jmdict_id": word.get("jmdict_id"),
                    "vocab_id": word["id"],
                    "tatoeba_id": example.get("tatoeba_id", ""),
                },
            )


def main() -> None:
    if "--rebuild-search-index" in sys.argv[1:]:
        if not DATABASE.exists():
            raise SystemExit(f"{DATABASE} 가 없습니다. 먼저 자료를 임포트하세요.")
        with sqlite3.connect(DATABASE) as connection:
            print("trigram 검색 인덱스를 만드는 중입니다 ...", flush=True)
            ensure_index(connection)
        print(f"검색 인덱스 생성 완료: {DATABASE}")
        return
    checksums = download_sources()
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATABASE.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.executescript(CREATE_ITEMS)
            counts = {
                "Tatoeba": import_tatoeba(connection),
                "KFTT": import_kftt(connection),
                "BSD": import_bsd(connection),
                "OpenJLPT": import_openjlpt(connection),
            }
            now = datetime.now(UTC).isoformat(timespec="seconds")
            sources = {
                "Tatoeba": (
                    "2026-10-03 export",
                    "CC BY 2.0 FR / CC0 1.0 per sentence",
                    "Tatoeba community; per-sentence author retained",
                    "https://tatoeba.org/en/downloads",
                ),
                "KFTT": (
                    "1.0",
                    "CC BY-SA 3.0",
                    "NICT / Kyoto Free Translation Task",
                    "https://www.phontron.com/kftt/",
                ),
                "BSD": (
                    BSD_COMMIT,
                    "CC BY-NC-SA",
                    "University of Tokyo",
                    f"https://github.com/tsuruoka-lab/BSD/tree/{BSD_COMMIT}",
                ),
                "OpenJLPT": (
                    OPENJLPT_COMMIT,
                    "CC BY-SA 4.0",
                    "OpenJLPT; upstream credits in project NOTICE",
                    f"https://github.com/evanclan/OpenJLPT/tree/{OPENJLPT_COMMIT}",
                ),
            }
            source_files = {
                "Tatoeba": [
                    name
                    for name in checksums
                    if name.startswith(("jpn_", "eng_", "sentences_CC0", "tatoeba_"))
                ],
                "KFTT": ["kftt-data-1.0.tar.gz"],
                "BSD": [f"bsd-{BSD_COMMIT}.zip"],
                "OpenJLPT": [f"openjlpt-{OPENJLPT_COMMIT}.zip"],
            }
            for source, (
                version,
                license_name,
                attribution,
                source_url,
            ) in sources.items():
                digest = hashlib.sha256(
                    "".join(checksums[name] for name in source_files[source]).encode()
                ).hexdigest()
                connection.execute(
                    "INSERT INTO source_manifest VALUES (?,?,?,?,?,?,?,?)",
                    (
                        source,
                        version,
                        license_name,
                        attribution,
                        source_url,
                        counts[source],
                        digest,
                        now,
                    ),
                )
            print("trigram 검색 인덱스를 만드는 중입니다 ...", flush=True)
            ensure_index(connection)
            connection.commit()
        temporary.replace(DATABASE)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print(f"Created {DATABASE}")
    for source, count in counts.items():
        print(f"{source}: {count:,} records")
    print(f"Total: {sum(counts.values()):,} records")


if __name__ == "__main__":
    main()
