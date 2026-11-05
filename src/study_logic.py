"""Study queues, answer checking, and spaced review scheduling."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import materials_search
from study_data import SKILL_BY_MODE

REVIEW_CAP = 80
NEW_CAP = 15
FORECAST_DAYS = 7
MODES = {
    "word_flashcard": ("word", SKILL_BY_MODE["word_flashcard"], "단어 플래시카드"),
    "word_typing": ("word", SKILL_BY_MODE["word_typing"], "단어 입력"),
    "sentence_typing": ("material", SKILL_BY_MODE["sentence_typing"], "문장 입력"),
    "japanese_copy_typing": (
        "material",
        SKILL_BY_MODE["japanese_copy_typing"],
        "일본어 보고 입력",
    ),
    "dialogue_typing": ("material", SKILL_BY_MODE["dialogue_typing"], "대화 입력"),
}
SKILL_LABELS = {
    "recognition": "인식",
    "recall": "재생",
    "production": "산출",
    "transcription": "필사",
}
RATINGS = {"again", "hard", "good", "easy"}


def normalize_answer(value: str) -> str:
    """Normalize Unicode width and spacing while retaining Japanese punctuation."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _json_array(value: str) -> list[dict]:
    return json.loads(value or "[]")


def _word(dictionary: sqlite3.Connection, item_id: str) -> dict | None:
    row = dictionary.execute(
        "SELECT id, kanji_json, kana_json, senses_json FROM entries WHERE id=?",
        (item_id,),
    ).fetchone()
    if not row:
        return None
    kanji = [x["text"] for x in _json_array(row["kanji_json"])]
    readings = [x["text"] for x in _json_array(row["kana_json"])]
    senses = _json_array(row["senses_json"])
    glosses = [
        gloss["text"]
        for sense in senses
        for gloss in sense.get("gloss", [])
        if gloss.get("lang") == "eng"
    ]
    forms = kanji + readings
    return {
        "id": row["id"],
        "type": "word",
        "front": kanji[0] if kanji else (readings[0] if readings else ""),
        "readings": readings,
        "forms": list(dict.fromkeys(forms)),
        "glosses": glosses,
        "misc": sorted({tag for sense in senses for tag in sense.get("misc", [])}),
        "fields": sorted({tag for sense in senses for tag in sense.get("field", [])}),
        "antonyms": [
            entry["text"] if isinstance(entry, dict) else str(entry)
            for sense in senses
            for entry in sense.get("antonym", [])
        ][:6],
    }


def word_examples(materials_path: Path, forms: list[str], limit: int = 3) -> list[dict]:
    """Return the shortest corpus sentences that contain one of the word's forms."""
    if not materials_path.exists():
        return []
    clauses: list[str] = []
    values: list[str] = []
    with sqlite3.connect(materials_path) as materials:
        materials.row_factory = sqlite3.Row
        use_fts = materials_search.has_index(materials)
        for form in forms[:3]:
            if use_fts and materials_search.supports_query(form):
                clauses.append(
                    f"learning_items.rowid IN (SELECT rowid FROM {materials_search.FTS_TABLE}"
                    f" WHERE {materials_search.FTS_TABLE} MATCH ?)"
                )
                values.append(materials_search.match_expression(form))
            else:
                clauses.append("japanese LIKE ?")
                values.append(f"%{form}%")
        if not clauses:
            return []
        rows = materials.execute(
            "SELECT id, source, japanese, english, level FROM learning_items"
            " WHERE kind='sentence' AND length(japanese) BETWEEN 8 AND 60"
            " AND (" + " OR ".join(clauses) + ")"
            " ORDER BY length(japanese) LIMIT ?",
            [*values, limit * 3],
        ).fetchall()
    seen: set[str] = set()
    examples = []
    for row in rows:
        if row["japanese"] in seen:
            continue
        seen.add(row["japanese"])
        examples.append(dict(row))
        if len(examples) == limit:
            break
    return examples


def _material(materials: sqlite3.Connection, item_id: str) -> dict | None:
    row = materials.execute(
        "SELECT id, source, source_id, kind, japanese, english, reading, level, context, author, license, source_url, metadata_json FROM learning_items WHERE id=?",
        (item_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    return item


def _dialogue_context(materials: sqlite3.Connection, item: dict) -> list[dict]:
    if item["source"] != "BSD":
        return []
    match = re.match(r"^(.*):(\d+)$", item["source_id"])
    if not match:
        return []
    scenario, current = match.group(1), int(match.group(2))
    prefix = scenario + ":"
    rows = materials.execute(
        "SELECT source_id, japanese, english, metadata_json FROM learning_items"
        " WHERE source='BSD' AND substr(source_id, 1, ?) = ?",
        (len(prefix), prefix),
    ).fetchall()
    turns = []
    for row in rows:
        turn_match = re.match(r"^.*:(\d+)$", row["source_id"])
        if not turn_match:
            continue
        number = int(turn_match.group(1))
        if max(1, current - 2) <= number < current:
            meta = json.loads(row["metadata_json"] or "{}")
            turns.append(
                {
                    "number": number,
                    "japanese": row["japanese"],
                    "english": row["english"],
                    "speaker": meta.get("ja_speaker", ""),
                }
            )
    return sorted(turns, key=lambda turn: turn["number"])


def reviews_today(db: sqlite3.Connection) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM study_log WHERE date(logged_at, 'localtime')=?",
        (datetime.now().date().isoformat(),),
    ).fetchone()[0]


def new_today(db: sqlite3.Connection) -> int:
    return db.execute(
        """SELECT COUNT(*) FROM (
             SELECT item_type, item_id, MIN(date(logged_at, 'localtime')) AS first
             FROM study_log GROUP BY item_type, item_id
           ) WHERE first=?""",
        (datetime.now().date().isoformat(),),
    ).fetchone()[0]


def next_item(
    study_path: Path,
    dictionary_path: Path,
    materials_path: Path,
    mode: str,
    completed: bool = False,
    respect_caps: bool = True,
) -> dict | None:
    if mode not in MODES:
        raise ValueError("학습 모드를 선택해 주세요.")
    item_type, skill = MODES[mode][:2]
    if item_type == "word" and not dictionary_path.exists():
        raise ValueError("사전 DB가 없습니다. 먼저 import-dictionary를 실행하세요.")
    if item_type == "material" and not materials_path.exists():
        raise ValueError(
            "자료 DB가 없습니다. 먼저 import-learning-materials를 실행하세요."
        )
    status = "mastered" if completed else "learning"
    today = datetime.now().date().isoformat()
    with sqlite3.connect(study_path) as db:
        db.row_factory = sqlite3.Row
        if completed or not respect_caps:
            new_allowed = 1
        else:
            if reviews_today(db) >= REVIEW_CAP:
                return None
            new_allowed = 1 if new_today(db) < NEW_CAP else 0
        now = datetime.now(UTC).isoformat(timespec="seconds")
        rows = db.execute(
            """SELECT p.item_id, r.due_at, r.lapses FROM study_progress p
               LEFT JOIN study_reviews r ON r.item_type=p.item_type
                 AND r.item_id=p.item_id AND r.skill=?
               WHERE p.item_type=? AND p.status=?
                 AND (? OR EXISTS (SELECT 1 FROM study_reviews x
                      WHERE x.item_type=p.item_type AND x.item_id=p.item_id))
                 AND NOT EXISTS (SELECT 1 FROM study_log l
                      WHERE l.item_type=p.item_type AND l.item_id=p.item_id
                        AND date(l.logged_at, 'localtime')=?)
               ORDER BY CASE WHEN r.due_at IS NULL OR r.due_at<=? THEN 0 ELSE 1 END,
               COALESCE(r.lapses, 0) DESC,
               COALESCE(r.due_at, p.added_at), p.added_at""",
            (skill, item_type, status, new_allowed, today, now),
        ).fetchall()
    if not rows:
        return None
    db_path = dictionary_path if item_type == "word" else materials_path
    with sqlite3.connect(db_path) as source:
        source.row_factory = sqlite3.Row
        for row in rows:
            item = (
                _word(source, row["item_id"])
                if item_type == "word"
                else _material(source, row["item_id"])
            )
            if item is None:
                continue
            if mode == "word_typing":
                item["prompt"] = "영어 뜻에 맞는 일본어 단어를 입력하세요."
            elif mode == "word_flashcard":
                item["prompt"] = "일본어 단어의 읽기와 뜻을 떠올려 보세요."
            elif mode == "sentence_typing":
                if (
                    item["kind"] != "sentence"
                    or item["source"] == "BSD"
                    or not item["english"]
                ):
                    continue
                item["prompt"] = "영어 문장을 일본어로 입력하세요."
            elif mode == "japanese_copy_typing":
                if item["kind"] != "sentence" or not item["japanese"]:
                    continue
                item["prompt"] = "화면의 일본어 문장을 보며 그대로 입력하세요."
            elif mode == "dialogue_typing":
                if item["source"] != "BSD" or not item["english"]:
                    continue
                item["prompt"] = "대화 흐름을 참고해 일본어 발화를 입력하세요."
                item["context_turns"] = _dialogue_context(source, item)
            if item_type == "word":
                item["examples"] = word_examples(materials_path, item["forms"])
            item["type"] = item_type
            item["mode"] = mode
            item["due_at"] = row["due_at"]
            item["is_due"] = not row["due_at"] or row["due_at"] <= now
            return item
    return None


def check_answer(
    dictionary_path: Path,
    materials_path: Path,
    mode: str,
    item_id: str,
    answer: str,
) -> dict:
    item_type = MODES[mode][0]
    db_path = dictionary_path if item_type == "word" else materials_path
    if not db_path.exists():
        raise ValueError("학습에 필요한 로컬 DB가 없습니다.")
    with sqlite3.connect(db_path) as source:
        source.row_factory = sqlite3.Row
        item = (
            _word(source, item_id)
            if item_type == "word"
            else _material(source, item_id)
        )
    if not item:
        raise ValueError("학습 항목을 찾지 못했습니다.")
    accepted = item["forms"] if item_type == "word" else [item["japanese"]]
    match = any(
        normalize_answer(answer) == normalize_answer(value)
        for value in accepted
        if value
    )
    return {"correct": match, "accepted": accepted, "item": item}


def next_interval(
    rating: str, repetitions: int, interval_days: float, lapses: int
) -> tuple[float, int, int]:
    """Return the next (interval_days, repetitions, lapses) for one review."""
    if rating == "again":
        return 10 / 1440, 0, lapses + 1
    if rating == "hard":
        return max(1, interval_days * 1.2), repetitions + 1, lapses
    if rating == "good":
        interval = (
            1 if repetitions == 0 else 3 if repetitions == 1 else interval_days * 2
        )
        return interval, repetitions + 1, lapses
    interval = 3 if repetitions == 0 else 7 if repetitions == 1 else interval_days * 2.5
    return interval, repetitions + 1, lapses


def schedule_review(
    study_path: Path,
    item_type: str,
    item_id: str,
    mode: str,
    rating: str,
    correct: bool | None = None,
) -> dict:
    if rating not in RATINGS or mode not in MODES or MODES[mode][0] != item_type:
        raise ValueError("복습 평가 또는 학습 유형이 올바르지 않습니다.")
    skill = MODES[mode][1]
    with sqlite3.connect(study_path) as db:
        db.row_factory = sqlite3.Row
        prior = db.execute(
            "SELECT * FROM study_reviews WHERE item_type=? AND item_id=? AND skill=?",
            (item_type, item_id, skill),
        ).fetchone()
        reps = prior["repetitions"] if prior else 0
        lapses = prior["lapses"] if prior else 0
        old_interval = prior["interval_days"] if prior else 0
        interval_days, reps, lapses = next_interval(rating, reps, old_interval, lapses)
        now = datetime.now(UTC)
        due = (now + timedelta(days=interval_days)).isoformat(timespec="seconds")
        db.execute(
            """INSERT INTO study_reviews(item_type,item_id,skill,due_at,interval_days,repetitions,lapses,last_rating,reviewed_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(item_type,item_id,skill) DO UPDATE SET due_at=excluded.due_at, interval_days=excluded.interval_days, repetitions=excluded.repetitions, lapses=excluded.lapses, last_rating=excluded.last_rating, reviewed_at=excluded.reviewed_at""",
            (
                item_type,
                item_id,
                skill,
                due,
                interval_days,
                reps,
                lapses,
                rating,
                now.isoformat(timespec="seconds"),
            ),
        )
        db.execute(
            "UPDATE study_progress SET status='learning', completed_at=NULL WHERE item_type=? AND item_id=?",
            (item_type, item_id),
        )
        db.execute(
            "INSERT INTO study_log(item_type,item_id,mode,skill,rating,correct) VALUES(?,?,?,?,?,?)",
            (
                item_type,
                item_id,
                mode,
                skill,
                rating,
                None if correct is None else int(correct),
            ),
        )
    return {
        "due_at": due,
        "interval_days": interval_days,
        "repetitions": reps,
        "lapses": lapses,
        "skill": skill,
    }


def set_mastered(
    study_path: Path, item_type: str, item_id: str, mastered: bool
) -> None:
    with sqlite3.connect(study_path) as db:
        db.execute(
            "INSERT OR IGNORE INTO study_progress(item_type,item_id) VALUES(?,?)",
            (item_type, item_id),
        )
        db.execute(
            "UPDATE study_progress SET status=?, completed_at=? WHERE item_type=? AND item_id=?",
            (
                "mastered" if mastered else "learning",
                datetime.now(UTC).isoformat(timespec="seconds") if mastered else None,
                item_type,
                item_id,
            ),
        )


def streak_days(days: set[str], today: date) -> int:
    """Count consecutive study days ending today, or yesterday if today is empty."""
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def overview(study: Path) -> dict:
    with sqlite3.connect(study) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT item_type,status,COUNT(*) AS count FROM study_progress GROUP BY item_type,status"
        ).fetchall()
        due_rows = db.execute(
            """SELECT r.skill, COUNT(*) AS due FROM study_reviews r
               JOIN study_progress p ON p.item_type=r.item_type AND p.item_id=r.item_id
               WHERE r.due_at<=? AND p.status='learning' GROUP BY r.skill""",
            (datetime.now(UTC).isoformat(timespec="seconds"),),
        ).fetchall()
        days = {
            row[0]
            for row in db.execute(
                """SELECT DISTINCT date(logged_at, 'localtime') FROM study_log
                   UNION SELECT DISTINCT date(reviewed_at, 'localtime') FROM study_reviews"""
            )
        }
        today = datetime.now().date().isoformat()
        reviews_done = db.execute(
            "SELECT COUNT(*) FROM study_log WHERE date(logged_at, 'localtime')=?",
            (today,),
        ).fetchone()[0]
        new_done = new_today(db)
        leeches = db.execute(
            "SELECT COUNT(*) FROM study_reviews WHERE lapses>=4"
        ).fetchone()[0]
        forecast = {
            (datetime.now().date() + timedelta(days=offset)).isoformat(): 0
            for offset in range(FORECAST_DAYS)
        }
        for row in db.execute(
            """SELECT date(due_at, 'localtime') AS day, COUNT(*) AS count
               FROM study_reviews GROUP BY day"""
        ):
            day = max(row["day"], today)
            if day in forecast:
                forecast[day] += row["count"]
        retention = {}
        for row in db.execute(
            """SELECT skill, COUNT(*) AS reviews,
                      SUM(CASE WHEN rating IN ('good', 'easy') THEN 1 ELSE 0 END) AS recalled,
                      COUNT(correct) AS checked, SUM(correct) AS accurate
               FROM study_log GROUP BY skill"""
        ):
            retention[row["skill"]] = {
                "reviews": row["reviews"],
                "recall": row["recalled"] / row["reviews"],
                "accuracy": (
                    row["accurate"] / row["checked"] if row["checked"] else None
                ),
            }
    counts = {f"{r['item_type']}_{r['status']}": r["count"] for r in rows}
    return {
        "counts": counts,
        "due": {r["skill"]: r["due"] for r in due_rows},
        "stats": {
            "reviews_today": reviews_done,
            "new_today": new_done,
            "review_cap": REVIEW_CAP,
            "new_cap": NEW_CAP,
            "days_studied": len(days),
            "streak_days": streak_days(days, datetime.now().date()),
            "leeches": leeches,
            "forecast": forecast,
            "retention": retention,
        },
    }
