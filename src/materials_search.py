"""Trigram full-text index for the read-only learning materials corpus."""

from __future__ import annotations

import sqlite3

FTS_TABLE = "learning_items_fts"
MIN_TRIGRAM_QUERY = 3


def has_index(connection: sqlite3.Connection) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (FTS_TABLE,),
        ).fetchone()
        is not None
    )


def ensure_index(connection: sqlite3.Connection) -> None:
    """Build the trigram index over the whole corpus; it is read-only afterwards."""
    connection.executescript(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
            japanese, english, context,
            content='learning_items', content_rowid='rowid', tokenize='trigram'
        );
        INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild');
        """
    )


def match_expression(query: str) -> str:
    """Quote a user query as an FTS5 phrase so punctuation stays literal."""
    return '"' + query.replace('"', '""') + '"'


def supports_query(query: str) -> bool:
    """The trigram tokenizer cannot match fewer than three characters."""
    return len(query) >= MIN_TRIGRAM_QUERY
