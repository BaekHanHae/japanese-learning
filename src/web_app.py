"""Serve a private, local Japanese vocabulary browser."""

from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DICT_DB = ROOT / "data" / "reference" / "jmdict.sqlite3"
STUDY_DB = ROOT / "data" / "private" / "study.sqlite3"
MATERIALS_DB = ROOT / "data" / "reference" / "learning_materials.sqlite3"
PAGE = ROOT / "src" / "web" / "index.html"
HOST = "127.0.0.1"
PORT = 8000


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
    return connection


def pos_for(senses_json: str) -> list[str]:
    senses = json.loads(senses_json)
    return sorted({tag for sense in senses for tag in sense.get("partOfSpeech", [])})


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
        "pos": pos_for(row["senses_json"]),
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
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/filters":
            if not DICT_DB.exists():
                self.respond(503, {"error": "사전 데이터가 없습니다."})
                return
            with sqlite3.connect(DICT_DB) as dictionary:
                rows = dictionary.execute("SELECT senses_json FROM entries").fetchall()
            tags = sorted(
                {
                    tag
                    for (raw,) in rows
                    for sense in json.loads(raw)
                    for tag in sense.get("partOfSpeech", [])
                }
            )
            self.respond(200, {"pos": tags})
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
            offset = max(0, min(int(params.get("offset", ["0"])[0]), 100_000_000))
            limit = max(1, min(int(params.get("limit", ["60"])[0]), 100))
            clauses = []
            values: list[str | int] = []
            if query:
                clauses.append("(japanese LIKE ? OR english LIKE ? OR context LIKE ?)")
                values.extend([f"%{query}%"] * 3)
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
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with sqlite3.connect(MATERIALS_DB) as materials, connect_study() as study:
                materials.row_factory = sqlite3.Row
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
        jlpt_filter = params.get("jlpt", [""])[0]
        with sqlite3.connect(DICT_DB) as dictionary, connect_study() as study:
            dictionary.row_factory = sqlite3.Row
            if parsed.path == "/api/browse":
                offset = max(0, min(int(params.get("offset", ["0"])[0]), 100_000_000))
                limit = max(1, min(int(params.get("limit", ["60"])[0]), 100))
                rows = dictionary.execute(
                    "SELECT id, kanji_json, kana_json, senses_json FROM entries ORDER BY id LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                saved_ids = {
                    row[0] for row in study.execute("SELECT entry_id FROM saved_words")
                }
                items = [
                    entry_payload(row) | {"saved": row["id"] in saved_ids}
                    for row in rows
                ]
                if pos_filter:
                    items = [item for item in items if pos_filter in item["pos"]]
                if jlpt_filter and jlpt_filter != "unclassified":
                    items = []
                total = dictionary.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
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
                if len(query) < 1:
                    self.respond(200, {"items": []})
                    return
                rows = dictionary.execute(
                    "SELECT id, kanji_json, kana_json, senses_json FROM entries WHERE search_text LIKE ? ORDER BY id LIMIT 80",
                    (f"%{query.casefold()}%",),
                ).fetchall()
                saved_ids = {
                    row[0] for row in study.execute("SELECT entry_id FROM saved_words")
                }
                items = [
                    entry_payload(row) | {"saved": row["id"] in saved_ids}
                    for row in rows
                ]
                if pos_filter:
                    items = [item for item in items if pos_filter in item["pos"]]
                if jlpt_filter and jlpt_filter != "unclassified":
                    items = []  # The JMdict snapshot has no JLPT annotations.
                self.respond(200, {"items": items, "limit": 80})
                return
            study.row_factory = sqlite3.Row
            study.execute("ATTACH DATABASE ? AS reference_dictionary", (str(DICT_DB),))
            sql = """SELECT e.id, e.kanji_json, e.kana_json, e.senses_json, s.note, s.saved_at
                     FROM saved_words s JOIN reference_dictionary.entries e ON e.id=s.entry_id
                     ORDER BY s.saved_at DESC, e.id"""
            rows = study.execute(sql).fetchall()
            items = [entry_payload(row, row["note"], row["saved_at"]) for row in rows]
            if pos_filter:
                items = [item for item in items if pos_filter in item["pos"]]
            if jlpt_filter and jlpt_filter != "unclassified":
                items = []
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
        }:
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 12000)
            data = json.loads(self.rfile.read(length))
            entry_id = str(data.get("id", ""))[:200]
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
                    else:
                        study.execute(
                            "DELETE FROM saved_materials WHERE item_id=?", (entry_id,)
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
                elif self.path == "/api/note":
                    study.execute(
                        "UPDATE saved_words SET note=? WHERE entry_id=?",
                        (str(data.get("note", ""))[:4000], entry_id),
                    )
                else:
                    study.execute(
                        "DELETE FROM saved_words WHERE entry_id=?", (entry_id,)
                    )
            self.respond(200, {"ok": True})
        except (ValueError, json.JSONDecodeError) as error:
            self.respond(400, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    if not DICT_DB.exists():
        raise SystemExit("사전 DB가 없습니다. 먼저 import-dictionary를 실행하세요.")
    connect_study().close()
    print(f"일본어 단어장: http://{HOST}:{PORT} (이 기기에서만 접속 가능)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
