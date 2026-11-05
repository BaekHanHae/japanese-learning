"""Serve a private, local Japanese vocabulary browser."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import materials_search
import reading
import speech
from study_data import ensure_study_schema
from study_logic import (
    MODES,
    check_answer,
    next_item,
    overview,
    schedule_review,
    set_mastered,
)

ROOT = Path(__file__).resolve().parents[1]
DICT_DB = ROOT / "data" / "reference" / "jmdict.sqlite3"
STUDY_DB = ROOT / "data" / "private" / "study.sqlite3"
MATERIALS_DB = ROOT / "data" / "reference" / "learning_materials.sqlite3"
PITCH_DB = ROOT / "data" / "reference" / "kanjium.sqlite3"
JLPT_DB = ROOT / "data" / "reference" / "jlpt_vocab.sqlite3"
PAGE = ROOT / "src" / "web" / "index.html"
STYLESHEET = ROOT / "src" / "web" / "style.css"
HOST = "127.0.0.1"
PORT = 8000
POS_FILTER_SQL = (
    "EXISTS (SELECT 1 FROM json_each(entries.senses_json) sense,"
    " json_each(sense.value, '$.partOfSpeech') tag WHERE tag.value=?)"
)
SAVED_SORTS = {
    "recent": "s.saved_at DESC, e.id",
    "kana": "json_extract(e.kana_json, '$[0].text'), e.id",
    "due": "COALESCE(r.due_at, ''), s.saved_at DESC, e.id",
}


def parse_int(
    params: dict[str, list[str]], key: str, default: int, low: int, high: int
) -> int:
    """Read a bounded integer query parameter, falling back on malformed input."""
    try:
        value = int(params.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        return default
    return max(low, min(value, high))


def pitch_accents(words: list[str], readings: list[str]) -> list[str]:
    """Look up Kanjium accents, preferring the exact headword over homophones."""
    if not PITCH_DB.exists():
        return []
    with sqlite3.connect(PITCH_DB) as pitch:
        rows = []
        for column, values in (("word", words[:3]), ("reading", readings[:3])):
            values = [value for value in values if value]
            if not values:
                continue
            placeholders = ",".join("?" * len(values))
            rows = pitch.execute(
                "SELECT DISTINCT accents FROM pitch_accents"
                f" WHERE {column} IN ({placeholders}) LIMIT 6",
                values,
            ).fetchall()
            if rows:
                break
    return list(dict.fromkeys(pattern for row in rows for pattern in row[0].split(",")))


def item_exists(item_type: str, item_id: str) -> bool:
    """Check a study item against its read-only reference database."""
    path, table = (
        (DICT_DB, "entries")
        if item_type == "word"
        else (MATERIALS_DB, "learning_items")
    )
    if not path.exists():
        return False
    with sqlite3.connect(path) as database:
        return (
            database.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone()
            is not None
        )


def connect_study() -> sqlite3.Connection:
    STUDY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STUDY_DB)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS saved_words (
            entry_id TEXT PRIMARY KEY,
            note TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS saved_materials (
            item_id TEXT PRIMARY KEY,
            note TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    ensure_study_schema(connection)
    return connection


def entry_payload(row: sqlite3.Row, note: str = "", saved_at: str = "") -> dict:
    kanji = json.loads(row["kanji_json"])
    kana = json.loads(row["kana_json"])
    senses = json.loads(row["senses_json"])
    return {
        "id": row["id"],
        "kanji": [item["text"] for item in kanji],
        "readings": [item["text"] for item in kana],
        "senses": senses,
        "glosses": [
            g["text"]
            for s in senses
            for g in s.get("gloss", [])
            if g.get("lang") == "eng"
        ],
        "pos": sorted(
            {tag for sense in senses for tag in sense.get("partOfSpeech", [])}
        ),
        "note": note,
        "saved_at": saved_at,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "JapaneseLearningLocal/1.0"

    def respond(
        self,
        status: int,
        payload: object,
        content_type: str = "application/json; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, ensure_ascii=False).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.handle_get()
        except (ValueError, json.JSONDecodeError) as error:
            self.respond(400, {"error": str(error)})
        except sqlite3.Error:
            self.respond(500, {"error": "로컬 데이터베이스를 읽지 못했습니다."})
        except Exception:
            self.respond(500, {"error": "요청을 처리하지 못했습니다."})

    def handle_get(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/style.css":
            self.respond(200, STYLESHEET.read_bytes(), "text/css; charset=utf-8")
            return
        if parsed.path == "/study.js":
            self.respond(
                200,
                (ROOT / "src" / "web" / "study.js").read_bytes(),
                "text/javascript; charset=utf-8",
            )
            return
        if parsed.path == "/reading.js":
            self.respond(
                200,
                (ROOT / "src" / "web" / "reading.js").read_bytes(),
                "text/javascript; charset=utf-8",
            )
            return
        if parsed.path == "/jlpt.js":
            self.respond(
                200,
                (ROOT / "src" / "web" / "jlpt.js").read_bytes(),
                "text/javascript; charset=utf-8",
            )
            return
        if parsed.path == "/api/word":
            if not DICT_DB.exists():
                self.respond(503, {"error": "사전 DB가 없습니다."})
                return
            params = parse_qs(parsed.query)
            word_id = params.get("id", [""])[0][:200]
            surface = params.get("surface", [""])[0][:40]
            with sqlite3.connect(DICT_DB) as dictionary:
                dictionary.row_factory = sqlite3.Row
                row = dictionary.execute(
                    "SELECT id, kanji_json, kana_json, senses_json FROM entries WHERE id=?",
                    (word_id,),
                ).fetchone()
                alternatives = []
                if surface:
                    alternatives = dictionary.execute(
                        """SELECT id, kanji_json, kana_json, senses_json FROM entries
                           WHERE id != ? AND (
                             EXISTS (SELECT 1 FROM json_each(kanji_json)
                                     WHERE json_extract(value, '$.text')=?)
                             OR EXISTS (SELECT 1 FROM json_each(kana_json)
                                     WHERE json_extract(value, '$.text')=?)
                           ) LIMIT 4""",
                        (word_id, surface, surface),
                    ).fetchall()
            if not row:
                self.respond(404, {"error": "사전에서 단어를 찾지 못했습니다."})
                return
            with connect_study() as study:
                saved = (
                    study.execute(
                        "SELECT 1 FROM saved_words WHERE entry_id=?", (word_id,)
                    ).fetchone()
                    is not None
                )
            payload = entry_payload(row)
            payload["pitch"] = pitch_accents(payload["kanji"], payload["readings"])
            self.respond(
                200,
                {
                    "item": payload | {"saved": saved},
                    "alternatives": [entry_payload(item) for item in alternatives],
                },
            )
            return
        if parsed.path == "/api/pitch":
            params = parse_qs(parsed.query)
            word = params.get("word", [""])[0][:40]
            pitch_reading = params.get("reading", [""])[0][:40]
            self.respond(200, {"accents": pitch_accents([word], [pitch_reading])})
            return
        if parsed.path == "/api/speech":
            text = parse_qs(parsed.query).get("text", [""])[0][:200].strip()
            if not text:
                self.respond(400, {"error": "읽을 문장을 입력해 주세요."})
                return
            try:
                wav = speech.speech_wav(text)
            except (OSError, ValueError) as error:
                self.respond(500, {"error": f"음성을 만들지 못했습니다: {error}"})
                return
            self.respond(200, wav.read_bytes(), "audio/wav")
            return
        if parsed.path == "/api/jlpt":
            if not JLPT_DB.exists():
                self.respond(
                    503,
                    {
                        "error": "JLPT 어휘 DB가 없습니다. import-jlpt-vocab를 실행하세요."
                    },
                )
                return
            params = parse_qs(parsed.query)
            level = params.get("level", ["N5"])[0]
            if level not in {"N5", "N4", "N3", "N2", "N1"}:
                level = "N5"
            limit = parse_int(params, "limit", 20, 1, 50)
            excluded = [
                value[:120]
                for value in params.get("exclude", [""])[0].split(",")[:60]
                if value
            ]
            clauses = ["level=?"]
            values: list[str | int] = [level]
            if excluded:
                clauses.append("id NOT IN (" + ",".join("?" * len(excluded)) + ")")
                values.extend(excluded)
            with sqlite3.connect(JLPT_DB) as jlpt:
                jlpt.row_factory = sqlite3.Row
                rows = jlpt.execute(
                    "SELECT id, word, reading, level, jmdict_id, meanings_json,"
                    " example_ja, example_en FROM jlpt_vocab WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY RANDOM() LIMIT ?",
                    [*values, limit],
                ).fetchall()
            self.respond(
                200,
                {
                    "items": [
                        dict(row) | {"meanings": json.loads(row["meanings_json"])}
                        for row in rows
                    ]
                },
            )
            return
        if parsed.path == "/api/reading":
            if not MATERIALS_DB.exists():
                self.respond(503, {"error": "자료 DB가 없습니다."})
                return
            if not DICT_DB.exists():
                self.respond(503, {"error": "사전 DB가 없습니다."})
                return
            params = parse_qs(parsed.query)
            level = params.get("level", [""])[0]
            limit = parse_int(params, "limit", 10, 1, 20)
            max_length = parse_int(params, "max_len", 80, 20, 200)
            excluded = [
                value[:120]
                for value in params.get("exclude", [""])[0].split(",")[:40]
                if value
            ]
            clauses = ["kind='sentence'", "english != ''", "length(japanese) <= ?"]
            values: list[str | int] = [max_length]
            if level:
                clauses.append("source='OpenJLPT'")
                clauses.append("level=?")
                values.append(level)
            if excluded:
                clauses.append("id NOT IN (" + ",".join("?" * len(excluded)) + ")")
                values.extend(excluded)
            with sqlite3.connect(MATERIALS_DB) as materials:
                materials.row_factory = sqlite3.Row
                rows = materials.execute(
                    "SELECT id, source, japanese, english, reading, level, context"
                    " FROM learning_items WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY RANDOM() LIMIT ?",
                    [*values, limit],
                ).fetchall()
            forms = reading.dictionary_forms(DICT_DB)
            items = [
                dict(row) | {"tokens": reading.segment(row["japanese"], forms)}
                for row in rows
            ]
            self.respond(200, {"items": items})
            return
        if parsed.path == "/api/materials/meta":
            if not MATERIALS_DB.exists():
                self.respond(
                    503,
                    {
                        "error": "자료 DB가 없습니다. import-learning-materials를 먼저 실행하세요."
                    },
                )
                return
            with sqlite3.connect(MATERIALS_DB) as materials:
                total = materials.execute(
                    "SELECT COUNT(*) FROM learning_items"
                ).fetchone()[0]
                sources = materials.execute(
                    "SELECT source, COUNT(*) FROM learning_items GROUP BY source ORDER BY source"
                ).fetchall()
                levels = materials.execute(
                    "SELECT DISTINCT level FROM learning_items WHERE level != '' ORDER BY level"
                ).fetchall()
            self.respond(
                200,
                {
                    "total": total,
                    "sources": [
                        {"name": name, "count": count} for name, count in sources
                    ],
                    "levels": [level[0] for level in levels],
                },
            )
            return
        if parsed.path == "/api/study/overview":
            self.respond(200, overview(STUDY_DB))
            return
        if parsed.path == "/api/export":
            with sqlite3.connect(STUDY_DB) as source:
                dump = "\n".join(source.iterdump())
            filename = f"kotoba-note-{datetime.now().date().isoformat()}.sql"
            self.respond(
                200,
                dump.encode(),
                "application/sql; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="{filename}"'},
            )
            return
        if parsed.path == "/api/study/next":
            params = parse_qs(parsed.query)
            mode = params.get("mode", [""])[0]
            if mode not in MODES:
                self.respond(400, {"error": "학습 모드를 선택해 주세요."})
                return
            try:
                item = next_item(
                    STUDY_DB,
                    DICT_DB,
                    MATERIALS_DB,
                    mode,
                    params.get("completed", [""])[0] == "1",
                )
            except ValueError as error:
                self.respond(503, {"error": str(error)})
                return
            self.respond(200, {"item": item})
            return
        if parsed.path == "/api/materials":
            if not MATERIALS_DB.exists():
                self.respond(
                    503,
                    {
                        "error": "자료 DB가 없습니다. import-learning-materials를 먼저 실행하세요."
                    },
                )
                return
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0].strip()[:120]
            source = params.get("source", [""])[0]
            kind = params.get("kind", [""])[0]
            level = params.get("level", [""])[0]
            saved_only = params.get("saved", [""])[0] == "1"
            offset = parse_int(params, "offset", 0, 0, 100_000_000)
            limit = parse_int(params, "limit", 60, 1, 100)
            clauses = []
            values: list[str | int] = []
            if source:
                clauses.append("source = ?")
                values.append(source)
            if kind:
                clauses.append("kind = ?")
                values.append(kind)
            if level:
                clauses.append("level = ?")
                values.append(level)
            if saved_only:
                clauses.append(
                    "EXISTS (SELECT 1 FROM private_study.saved_materials sm WHERE sm.item_id = learning_items.id)"
                )
            with sqlite3.connect(MATERIALS_DB) as materials, connect_study() as study:
                materials.row_factory = sqlite3.Row
                if query:
                    if materials_search.supports_query(
                        query
                    ) and materials_search.has_index(materials):
                        clauses.append(
                            "learning_items.rowid IN"
                            f" (SELECT rowid FROM {materials_search.FTS_TABLE}"
                            f" WHERE {materials_search.FTS_TABLE} MATCH ?)"
                        )
                        values.append(materials_search.match_expression(query))
                    else:
                        clauses.append(
                            "(japanese LIKE ? OR english LIKE ? OR context LIKE ?)"
                        )
                        values.extend([f"%{query}%"] * 3)
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                if saved_only:
                    materials.execute(
                        "ATTACH DATABASE ? AS private_study", (str(STUDY_DB),)
                    )
                total = materials.execute(
                    "SELECT COUNT(*) FROM learning_items" + where, values
                ).fetchone()[0]
                rows = materials.execute(
                    "SELECT id, source, source_id, kind, japanese, english, reading, level, context, author, license, source_url, metadata_json FROM learning_items"
                    + where
                    + " ORDER BY source, kind, id LIMIT ? OFFSET ?",
                    [*values, limit, offset],
                ).fetchall()
                ids = [item["id"] for item in rows]
                placeholders = ",".join("?" for _ in ids)
                saved = set()
                if ids:
                    saved = {
                        item[0]
                        for item in study.execute(
                            f"SELECT item_id FROM saved_materials WHERE item_id IN ({placeholders})",
                            ids,
                        )
                    }
            items = [dict(item) | {"saved": item["id"] in saved} for item in rows]
            self.respond(
                200,
                {
                    "items": items,
                    "offset": offset,
                    "limit": limit,
                    "total": total,
                    "has_more": offset + len(items) < total,
                },
            )
            return
        if parsed.path not in {"/api/search", "/api/saved", "/api/browse"}:
            self.respond(404, {"error": "Not found"})
            return
        if not DICT_DB.exists():
            self.respond(
                503,
                {
                    "error": "먼저 사전을 가져와 주세요: uv run python src/japanese_learning.py import-dictionary"
                },
            )
            return
        params = parse_qs(parsed.query)
        query = params.get("q", [""])[0].strip()[:100]
        pos_filter = params.get("pos", [""])[0]
        with sqlite3.connect(DICT_DB) as dictionary, connect_study() as study:
            dictionary.row_factory = sqlite3.Row
            where = ""
            values: list[str] = []
            if pos_filter:
                where = " WHERE " + POS_FILTER_SQL
                values.append(pos_filter)
            if parsed.path == "/api/browse":
                offset = parse_int(params, "offset", 0, 0, 100_000_000)
                limit = parse_int(params, "limit", 60, 1, 100)
                rows = dictionary.execute(
                    "SELECT id, kanji_json, kana_json, senses_json FROM entries"
                    + where
                    + " ORDER BY id LIMIT ? OFFSET ?",
                    [*values, limit, offset],
                ).fetchall()
                saved_ids = {
                    row[0] for row in study.execute("SELECT entry_id FROM saved_words")
                }
                items = [
                    entry_payload(row) | {"saved": row["id"] in saved_ids}
                    for row in rows
                ]
                total = dictionary.execute(
                    "SELECT COUNT(*) FROM entries" + where, values
                ).fetchone()[0]
                self.respond(
                    200,
                    {
                        "items": items,
                        "next_offset": offset + limit,
                        "has_more": offset + limit < total,
                        "total": total,
                    },
                )
                return
            if parsed.path == "/api/search":
                if not query:
                    self.respond(200, {"items": []})
                    return
                rows = dictionary.execute(
                    "SELECT id, kanji_json, kana_json, senses_json FROM entries"
                    " WHERE search_text LIKE ?"
                    + (" AND " + POS_FILTER_SQL if pos_filter else "")
                    + " ORDER BY id LIMIT 80",
                    [f"%{query.casefold()}%", *values],
                ).fetchall()
                saved_ids = {
                    row[0] for row in study.execute("SELECT entry_id FROM saved_words")
                }
                items = [
                    entry_payload(row) | {"saved": row["id"] in saved_ids}
                    for row in rows
                ]
                self.respond(200, {"items": items, "limit": 80})
                return
            study.row_factory = sqlite3.Row
            study.execute("ATTACH DATABASE ? AS reference_dictionary", (str(DICT_DB),))
            order = SAVED_SORTS.get(
                params.get("sort", ["recent"])[0], SAVED_SORTS["recent"]
            )
            sql = f"""SELECT e.id, e.kanji_json, e.kana_json, e.senses_json, s.note, s.saved_at
                     FROM saved_words s JOIN reference_dictionary.entries e ON e.id=s.entry_id
                     LEFT JOIN (SELECT item_id, MIN(due_at) AS due_at FROM study_reviews
                                WHERE item_type='word' GROUP BY item_id) r ON r.item_id=s.entry_id
                     ORDER BY {order}"""
            rows = study.execute(sql).fetchall()
            items = [entry_payload(row, row["note"], row["saved_at"]) for row in rows]
            if pos_filter:
                items = [item for item in items if pos_filter in item["pos"]]
            self.respond(
                200, {"items": items, "total": len(items), "total_saved": len(rows)}
            )

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {
            "/api/save",
            "/api/note",
            "/api/remove",
            "/api/materials/save",
            "/api/materials/remove",
            "/api/study/check",
            "/api/study/review",
            "/api/study/master",
        }:
            self.respond(404, {"error": "Not found"})
            return
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self.respond(415, {"error": "JSON 요청만 받습니다."})
            return
        origin = self.headers.get("Origin", "")
        if origin and origin not in {
            f"http://{HOST}:{PORT}",
            f"http://localhost:{PORT}",
        }:
            self.respond(403, {"error": "허용되지 않은 출처입니다."})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 12000)
            data = json.loads(self.rfile.read(length))
            entry_id = str(data.get("id", ""))[:200]
            if self.path.startswith("/api/study/"):
                mode = str(data.get("mode", ""))
                item_type = str(data.get("type", ""))
                if mode not in MODES or item_type != MODES[mode][0] or not entry_id:
                    raise ValueError("학습 모드와 항목 정보가 필요합니다.")
                if self.path == "/api/study/check":
                    result = check_answer(
                        DICT_DB,
                        MATERIALS_DB,
                        mode,
                        entry_id,
                        str(data.get("answer", "")),
                    )
                    self.respond(200, result)
                    return
                if not item_exists(item_type, entry_id):
                    self.respond(404, {"error": "학습 항목을 찾지 못했습니다."})
                    return
                if self.path == "/api/study/review":
                    correct = data.get("correct")
                    result = schedule_review(
                        STUDY_DB,
                        item_type,
                        entry_id,
                        mode,
                        str(data.get("rating", "")),
                        None if correct is None else bool(correct),
                    )
                    self.respond(200, result)
                else:
                    set_mastered(
                        STUDY_DB, item_type, entry_id, bool(data.get("mastered", True))
                    )
                    self.respond(200, {"ok": True})
                return
            if not entry_id:
                raise ValueError("단어 ID가 필요합니다.")
            if self.path.startswith("/api/materials/"):
                if not MATERIALS_DB.exists():
                    self.respond(503, {"error": "자료 DB가 없습니다."})
                    return
                with sqlite3.connect(MATERIALS_DB) as materials:
                    exists = materials.execute(
                        "SELECT 1 FROM learning_items WHERE id=?", (entry_id,)
                    ).fetchone()
                if not exists:
                    self.respond(
                        404, {"error": "학습 자료에서 항목을 찾지 못했습니다."}
                    )
                    return
                with connect_study() as study:
                    if self.path == "/api/materials/save":
                        study.execute(
                            "INSERT OR IGNORE INTO saved_materials(item_id) VALUES (?)",
                            (entry_id,),
                        )
                        study.execute(
                            "INSERT OR IGNORE INTO study_progress(item_type,item_id) VALUES('material',?)",
                            (entry_id,),
                        )
                    else:
                        study.execute(
                            "DELETE FROM saved_materials WHERE item_id=?", (entry_id,)
                        )
                        study.execute(
                            "DELETE FROM study_progress WHERE item_type='material' AND item_id=?",
                            (entry_id,),
                        )
                        study.execute(
                            "DELETE FROM study_reviews WHERE item_type='material' AND item_id=?",
                            (entry_id,),
                        )
                self.respond(200, {"ok": True})
                return
            with sqlite3.connect(DICT_DB) as dictionary:
                exists = dictionary.execute(
                    "SELECT 1 FROM entries WHERE id=?", (entry_id,)
                ).fetchone()
            if not exists:
                self.respond(404, {"error": "사전에서 단어를 찾지 못했습니다."})
                return
            with connect_study() as study:
                if self.path == "/api/save":
                    study.execute(
                        "INSERT OR IGNORE INTO saved_words(entry_id) VALUES (?)",
                        (entry_id,),
                    )
                    study.execute(
                        "INSERT OR IGNORE INTO study_progress(item_type,item_id) VALUES('word',?)",
                        (entry_id,),
                    )
                elif self.path == "/api/note":
                    study.execute(
                        "UPDATE saved_words SET note=? WHERE entry_id=?",
                        (str(data.get("note", ""))[:4000], entry_id),
                    )
                else:
                    study.execute(
                        "DELETE FROM saved_words WHERE entry_id=?", (entry_id,)
                    )
                    study.execute(
                        "DELETE FROM study_progress WHERE item_type='word' AND item_id=?",
                        (entry_id,),
                    )
                    study.execute(
                        "DELETE FROM study_reviews WHERE item_type='word' AND item_id=?",
                        (entry_id,),
                    )
            self.respond(200, {"ok": True})
        except (ValueError, json.JSONDecodeError) as error:
            self.respond(400, {"error": str(error)})
        except sqlite3.Error:
            self.respond(500, {"error": "로컬 데이터베이스에 저장하지 못했습니다."})
        except Exception:
            self.respond(500, {"error": "요청을 처리하지 못했습니다."})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    if not DICT_DB.exists():
        raise SystemExit("사전 DB가 없습니다. 먼저 import-dictionary를 실행하세요.")
    if not MATERIALS_DB.exists():
        print(
            "학습 자료 DB가 없습니다. 문장·문법 학습을 쓰려면 "
            "uv run python src/import_learning_materials.py 를 먼저 실행하세요."
        )
    else:
        with sqlite3.connect(MATERIALS_DB) as materials:
            if not materials_search.has_index(materials):
                print(
                    "자료 검색 인덱스가 없어 느린 검색으로 동작합니다. "
                    "uv run python src/import_learning_materials.py "
                    "--rebuild-search-index 로 한 번만 만들어 주세요."
                )
    connect_study().close()
    print(f"일본어 단어장: http://{HOST}:{PORT} (이 기기에서만 접속 가능)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
