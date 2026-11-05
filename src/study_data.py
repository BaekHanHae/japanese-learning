"""Private study database schema and migrations."""

from __future__ import annotations

import sqlite3

SKILL_BY_MODE = {
    "word_flashcard": "recognition",
    "word_typing": "recall",
    "sentence_typing": "production",
    "dialogue_typing": "production",
    "japanese_copy_typing": "transcription",
}

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS study_progress (
    item_type TEXT NOT NULL CHECK (item_type IN ('word', 'material')),
    item_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'learning'
        CHECK (status IN ('learning', 'mastered')),
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    PRIMARY KEY (item_type, item_id)
);
CREATE TABLE IF NOT EXISTS study_reviews (
    item_type TEXT NOT NULL CHECK (item_type IN ('word', 'material')),
    item_id TEXT NOT NULL,
    skill TEXT NOT NULL,
    due_at TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    last_rating TEXT NOT NULL,
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (item_type, item_id, skill)
);
CREATE TABLE IF NOT EXISTS study_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    skill TEXT NOT NULL DEFAULT '',
    rating TEXT NOT NULL,
    correct INTEGER,
    logged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS study_log_time ON study_log(logged_at);
CREATE INDEX IF NOT EXISTS study_progress_status
    ON study_progress(status, item_type, added_at);
"""


def _migrate_reviews_to_skills(connection: sqlite3.Connection) -> None:
    """Rebuild the old per-mode review table into one row per item and skill."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(study_reviews)")}
    if not columns or "skill" in columns:
        return
    mapping = " ".join(
        f"WHEN '{mode}' THEN '{skill}'" for mode, skill in SKILL_BY_MODE.items()
    )
    connection.executescript(
        f"""
        ALTER TABLE study_reviews RENAME TO study_reviews_legacy;
        CREATE TABLE study_reviews (
            item_type TEXT NOT NULL CHECK (item_type IN ('word', 'material')),
            item_id TEXT NOT NULL,
            skill TEXT NOT NULL,
            due_at TEXT NOT NULL,
            interval_days REAL NOT NULL DEFAULT 0,
            repetitions INTEGER NOT NULL DEFAULT 0,
            lapses INTEGER NOT NULL DEFAULT 0,
            last_rating TEXT NOT NULL,
            reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (item_type, item_id, skill)
        );
        INSERT OR IGNORE INTO study_reviews
            (item_type, item_id, skill, due_at, interval_days, repetitions,
             lapses, last_rating, reviewed_at)
        SELECT item_type, item_id,
            CASE mode {mapping} ELSE 'production' END,
            due_at, interval_days, repetitions, lapses, last_rating, reviewed_at
        FROM study_reviews_legacy;
        DROP TABLE study_reviews_legacy;
        CREATE INDEX IF NOT EXISTS study_reviews_skill_due
            ON study_reviews(skill, due_at);
        """
    )


def _migrate_log_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(study_log)")}
    if not columns:
        return
    if "skill" not in columns:
        connection.execute(
            "ALTER TABLE study_log ADD COLUMN skill TEXT NOT NULL DEFAULT ''"
        )
    if "correct" not in columns:
        connection.execute("ALTER TABLE study_log ADD COLUMN correct INTEGER")


def ensure_study_schema(connection: sqlite3.Connection) -> None:
    """Create additive study tables, migrate old shapes, and enroll saved items."""
    connection.executescript(CREATE_TABLES)
    _migrate_reviews_to_skills(connection)
    _migrate_log_columns(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS study_reviews_skill_due"
        " ON study_reviews(skill, due_at)"
    )
    connection.executescript(
        """
        INSERT OR IGNORE INTO study_progress (item_type, item_id)
            SELECT 'word', entry_id FROM saved_words;
        INSERT OR IGNORE INTO study_progress (item_type, item_id)
            SELECT 'material', item_id FROM saved_materials;
        """
    )
