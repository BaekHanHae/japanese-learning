"""Small regression checks for answer matching, scheduling, and query parsing."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import warnings
from contextlib import closing
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from materials_search import match_expression, supports_query  # noqa: E402
from reading import segment  # noqa: E402
from study_logic import (  # noqa: E402
    _dialogue_context,
    check_answer,
    next_interval,
    normalize_answer,
    streak_days,
)
from web_app import parse_int  # noqa: E402


class NormalizeAnswerTest(unittest.TestCase):
    def test_ignores_width_and_spaces(self) -> None:
        self.assertEqual(normalize_answer(" ＡＢＣ ねこ "), "abcねこ")

    def test_keeps_japanese_punctuation(self) -> None:
        self.assertEqual(normalize_answer("猫！"), normalize_answer("猫!"))


class NextIntervalTest(unittest.TestCase):
    def test_again_resets_and_waits_ten_minutes(self) -> None:
        interval, repetitions, lapses = next_interval("again", 4, 30.0, 2)
        self.assertAlmostEqual(interval, 10 / 1440)
        self.assertEqual(repetitions, 0)
        self.assertEqual(lapses, 3)

    def test_good_first_reviews(self) -> None:
        self.assertEqual(next_interval("good", 0, 0, 0)[:2], (1, 1))
        self.assertEqual(next_interval("good", 1, 1, 0)[:2], (3, 2))
        self.assertEqual(next_interval("good", 2, 3, 0)[:2], (6, 3))

    def test_easy_first_reviews(self) -> None:
        self.assertEqual(next_interval("easy", 0, 0, 0)[:2], (3, 1))
        self.assertEqual(next_interval("easy", 1, 3, 0)[:2], (7, 2))
        self.assertEqual(next_interval("easy", 2, 7, 0)[:2], (17.5, 3))

    def test_hard_never_drops_below_one_day(self) -> None:
        self.assertEqual(next_interval("hard", 0, 0, 0)[:2], (1, 1))
        self.assertAlmostEqual(next_interval("hard", 3, 10, 0)[0], 12)


class CheckAnswerTest(unittest.TestCase):
    """Flashcard and typing modes must accept the right answer shapes."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.dictionary = root / "dict.sqlite3"
        with closing(sqlite3.connect(self.dictionary)) as db:
            db.execute(
                "CREATE TABLE entries (id TEXT PRIMARY KEY, kanji_json TEXT, kana_json TEXT, senses_json TEXT)"
            )
            db.execute(
                "INSERT INTO entries VALUES (?,?,?,?)",
                (
                    "1",
                    '[{"text":"猫"}]',
                    '[{"text":"ねこ"}]',
                    '[{"gloss":[{"text":"cat","lang":"eng"}]}]',
                ),
            )
            db.commit()
        self.materials = root / "materials.sqlite3"
        with closing(sqlite3.connect(self.materials)) as db:
            db.execute(
                """CREATE TABLE learning_items (id TEXT PRIMARY KEY, source TEXT,
                source_id TEXT, kind TEXT, japanese TEXT, english TEXT, reading TEXT,
                level TEXT, context TEXT, author TEXT, license TEXT, source_url TEXT,
                metadata_json TEXT)"""
            )
            db.execute(
                "INSERT INTO learning_items VALUES ('m1','Tatoeba','1','sentence',"
                "'猫が好き','I like cats.','','','','','CC BY 2.0 FR','u','{}')"
            )
            db.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_word_flashcard_does_not_require_a_japanese_key(self) -> None:
        result = check_answer(
            self.dictionary, self.materials, "word_flashcard", "1", ""
        )
        self.assertFalse(result["correct"])
        self.assertEqual(result["accepted"], ["猫", "ねこ"])

    def test_word_typing_accepts_a_reading(self) -> None:
        result = check_answer(
            self.dictionary, self.materials, "word_typing", "1", "ねこ"
        )
        self.assertTrue(result["correct"])

    def test_material_copy_typing_compares_the_source_sentence(self) -> None:
        result = check_answer(
            self.dictionary, self.materials, "japanese_copy_typing", "m1", "猫が好き"
        )
        self.assertTrue(result["correct"])


class SegmentTest(unittest.TestCase):
    def test_links_inflections_to_the_dictionary_form(self) -> None:
        self.assertEqual(
            segment("食べた", {"食べる": "9"}),
            [{"text": "食べ", "id": "9"}, {"text": "た"}],
        )

    def test_leaves_unmatched_particles_unlinked(self) -> None:
        tokens = segment("猫が好き", {"猫": "1", "好き": "3"})
        self.assertEqual([token.get("id") for token in tokens], ["1", None, "3"])


class DialogueContextTest(unittest.TestCase):
    def test_returns_the_two_previous_turns_of_the_same_scenario(self) -> None:
        with closing(sqlite3.connect(":memory:")) as materials:
            materials.row_factory = sqlite3.Row
            materials.execute(
                "CREATE TABLE learning_items (source, source_id, japanese,"
                " english, metadata_json)"
            )
            materials.executemany(
                "INSERT INTO learning_items VALUES (?,?,?,?,?)",
                [
                    ("BSD", "scenario:1", "一", "one", '{"ja_speaker": "A"}'),
                    ("BSD", "scenario:2", "二", "two", "{}"),
                    ("BSD", "scenario:3", "三", "three", "{}"),
                    ("BSD", "other:2", "別", "other", "{}"),
                ],
            )
            turns = _dialogue_context(
                materials, {"source": "BSD", "source_id": "scenario:3"}
            )
        self.assertEqual([turn["number"] for turn in turns], [1, 2])
        self.assertEqual(turns[0]["speaker"], "A")


class ParseIntTest(unittest.TestCase):
    def test_bounds_and_fallback(self) -> None:
        self.assertEqual(parse_int({}, "offset", 0, 0, 100), 0)
        self.assertEqual(parse_int({"offset": ["abc"]}, "offset", 0, 0, 100), 0)
        self.assertEqual(parse_int({"limit": ["999"]}, "limit", 60, 1, 100), 100)
        self.assertEqual(parse_int({"offset": ["-5"]}, "offset", 0, 0, 100), 0)


class StreakTest(unittest.TestCase):
    def test_counts_back_from_today(self) -> None:
        days = {"2026-10-23", "2026-10-22", "2026-10-21", "2026-10-19"}
        self.assertEqual(streak_days(days, date(2026, 10, 23)), 3)

    def test_keeps_yesterdays_streak_until_today_starts(self) -> None:
        days = {"2026-10-22", "2026-10-21"}
        self.assertEqual(streak_days(days, date(2026, 10, 23)), 2)

    def test_empty_or_stale_history_is_zero(self) -> None:
        self.assertEqual(streak_days(set(), date(2026, 10, 23)), 0)
        self.assertEqual(streak_days({"2026-10-20"}, date(2026, 10, 23)), 0)


class MaterialsSearchTest(unittest.TestCase):
    def test_query_is_quoted_as_a_literal_phrase(self) -> None:
        self.assertEqual(match_expression("猫 OR 犬"), '"猫 OR 犬"')
        self.assertEqual(match_expression('say "hi"'), '"say ""hi"""')

    def test_trigram_needs_three_characters(self) -> None:
        self.assertFalse(supports_query("猫"))
        self.assertTrue(supports_query("食べる"))


if __name__ == "__main__":
    unittest.main()
