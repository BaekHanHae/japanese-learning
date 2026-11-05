"""Japanese segmentation for tap-to-look-up reading."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from janome.tokenizer import Tokenizer

_cache: tuple[Path, dict[str, str]] | None = None
_tokenizer: Tokenizer | None = None


def dictionary_forms(dictionary_path: Path) -> dict[str, str]:
    """Map every headword and reading to its JMdict entry id."""
    global _cache
    if _cache and _cache[0] == dictionary_path:
        return _cache[1]
    forms: dict[str, str] = {}
    with sqlite3.connect(dictionary_path) as dictionary:
        for entry_id, kanji_json, kana_json in dictionary.execute(
            "SELECT id, kanji_json, kana_json FROM entries"
        ):
            for item in json.loads(kanji_json) + json.loads(kana_json):
                forms.setdefault(item["text"], entry_id)
    _cache = (dictionary_path, forms)
    return forms


def segment(text: str, forms: dict[str, str]) -> list[dict]:
    """Split a sentence into words, resolving inflections to dictionary forms."""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer()
    tokens = []
    for token in _tokenizer.tokenize(text):
        entry_id = forms.get(token.base_form) or forms.get(token.surface)
        content_word = token.part_of_speech.split(",")[0] in {
            "名詞",
            "動詞",
            "形容詞",
            "副詞",
            "連体詞",
            "接続詞",
            "感動詞",
        }
        item = {"text": token.surface}
        if entry_id and content_word:
            item["id"] = entry_id
        tokens.append(item)
    return tokens
