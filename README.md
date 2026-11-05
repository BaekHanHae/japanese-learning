# Japanese Learning

A small local-first Japanese vocabulary project. The first step is a CLI that imports the common-word English JMdict dataset into a local SQLite database and searches it offline.

## Why a local dictionary

This project downloads a versioned data file once instead of depending on a dictionary API every time it searches. SQLite is built into Python, so the project needs no database server or runtime package for its first version.

The source JSON has Japanese headwords, readings, English glosses, and language-learning tags in structured fields. JSON makes the data straightforward to parse and retain. It does **not** translate English glosses into Korean automatically. If Korean meanings are added later, they can be stored as a separate translation layer keyed by the stable JMdict entry ID, preserving the original data and its provenance.

## Requirements

- macOS or another Python 3.13 environment
- [`uv`](https://docs.astral.sh/uv/)

## First use

```sh
uv sync
uv run python src/japanese_learning.py import-dictionary
uv run python src/japanese_learning.py search 猫
```

The importer downloads the pinned common-only JSON archive, checks its SHA-256, and builds `data/reference/jmdict.sqlite3`. Search the database without an internet connection after import.

To search by a Japanese word, reading, or English gloss:

```sh
uv run python src/japanese_learning.py search ねこ
uv run python src/japanese_learning.py search cat
```

## Local web wordbook

Start the local browser app after importing the dictionary:

```sh
uv run python src/web_app.py
```

Then open <http://127.0.0.1:8000>. Browse the full dictionary in batches of 60 entries as you scroll, search by Japanese text, reading, or English gloss, save entries, filter by JMdict part-of-speech tags, sort saved words by save date, kana, or next review, and keep private notes. Filtering and pagination run in SQL, so the displayed count and the loaded pages always match the selected filter. The service binds only to the local machine. Personal records are stored in `data/private/study.sqlite3`, separate from the reference dictionary. The current JMdict snapshot has no word-level JLPT field, so the word screen has no JLPT filter; sentence and grammar materials show OpenJLPT's community N5–N1 labels separately.

## Sentence and grammar materials

Download and import the selected corpora into a local database:

```sh
uv run python src/import_learning_materials.py
```

The local web app then adds **문장·문법 자료** and **저장한 학습 자료** under My Space. It includes Japanese-English pairs from Tatoeba, all four KFTT splits, public BSD business-scene dialogues, and OpenJLPT grammar points and example sentences. The importer checks pinned source-file SHA-256 hashes, keeps records separated by source, and retains sentence IDs, author names where provided, source links, and license labels. Corpus databases are local-only and ignored by Git.

The importer also builds a trigram full-text index over the corpus, so searches of three or more characters answer in milliseconds instead of scanning all 764k rows. The index adds about 470 MB to the local database and takes roughly 30 seconds to build. Searches of one or two characters (`猫`, `京都`) fall back to a full scan and stay under a second. If a database was imported before this index existed, build it once with:

```sh
uv run python src/import_learning_materials.py --rebuild-search-index
```

## Practice and spaced review

Open **학습하기** to use five modes with items you have explicitly saved:

- **Word flashcards:** recall a word's reading and meanings before revealing them.
- **Word typing:** type a Japanese headword or reading from its English gloss. Accepted forms are checked after submission.
- **Sentence typing:** translate the saved non-BSD English sentence into Japanese. The app compares it with the source text; because multiple translations can be valid, compare the source and judge your recall yourself.
- **Japanese copy typing:** keep the Japanese sentence visible and type it as shown, practicing Japanese IME conversion, kana/kanji selection, and punctuation. Press Enter after IME conversion; a matching answer is rated Good and advances automatically, while a mismatch stays on the same sentence for correction. This is a transcription exercise, separate from translation recall.
- **Business dialogue typing:** translate a saved BSD line with the preceding turns, scenario, and speaker shown for context. The target line's source and license remain visible when revealed.

After each reveal, choose **다시**, **어려웠어요**, **알았어요**, or **쉬웠어요**. This sets the next review per **skill**, not per screen: flashcard = recognition, word typing = recall, sentence/dialogue typing = production, copy typing = transcription. That keeps one schedule when two modes practice the same skill. A word studied in any mode today does not appear again the same day. The session engine caps a day at **80 reviews** and **15 new items**, shows the next seven days of due counts, and puts often-lapsed items first. **학습 완료** moves the item to the completed list without deleting it from your saved library; use **다시 학습하기** to bring it back.

Word cards also show up to three corpus examples with the target highlighted, plus politeness/field tags, antonyms, and a character-level difference against the source after a wrong answer. 🔊 reads the word or sentence through macOS `say` (Kyoko voice) and, for words, shows the Kanjium pitch-accent number when available.

The private study database tracks progress and review dates in additive tables. When the app first starts, it enrolls items already present in `saved_words` and `saved_materials`. New saves enroll automatically; removing an item from the saved library removes its progress and review records as well. Reference dictionaries and source corpora are read-only during practice.

Each rating is appended to a small `study_log` table, which powers the line above the study card (**오늘 복습 N/80 · 신규 N/15 · 연속 N일 · 내일 N개**). A day counts as studied once it has at least one rating; a streak survives an empty today until the day ends. **내보내기** on the same screen downloads a dated `.sql` dump of the private database:

```sh
sqlite3 data/private/study-restored.sqlite3 < kotoba-note-2026-10-23.sql
```

The dump includes saved words, notes, progress, and review history. Keep it out of Git and shared storage.

## Reading and JLPT vocabulary

Two small lookup databases feed these screens:

```sh
uv run python src/import_pitch_accents.py
uv run python src/import_jlpt_vocab.py
```

`import_pitch_accents.py` downloads Kanjium's `accents.txt` (pinned commit and SHA-256) and writes `data/reference/kanjium.sqlite3`. The 3.2 MB list is CC BY-SA 4.0. `import_jlpt_vocab.py` reads the OpenJLPT archive that the sentence importer already downloaded and writes `data/reference/jlpt_vocab.sqlite3` (7,811 community-graded words), so the large corpus database is not rebuilt.

Open **읽기** to read N5–N1 or mixed sentences of at most 80 characters. Every content word is clickable: the popover shows its reading, English gloss, pitch accent, homophone alternatives, a save button, and 🔊 for pronunciation. Segmentation uses [Janome](https://github.com/mocobeta/janome) (Apache 2.0), which resolves inflected forms such as 会い → 会う; its bundled dictionary takes about 137 MB in the virtual environment.

Open **JLPT 어휘** to drill OpenJLPT's N5–N1 words in random batches: see the word, reveal its reading, meaning, and example, listen, or save it to the wordbook with its JMdict ID. Levels are community estimates, not official JLPT lists.

Tatoeba is community-contributed and may include awkward or incorrect translations; review examples before treating them as authoritative. KFTT is Wikipedia Kyoto article material and BSD is scenario-written business dialogue, so their styles differ. OpenJLPT's N5–N1 levels are community estimates rather than official JLPT lists. BSD uses CC BY-NC-SA; the other selected corpora have their own attribution/share-alike terms. Keep the source label and credit visible when viewing material, and do not redistribute the private combined database. JParaCrawl and subtitle corpora are excluded because their terms or provenance are not suitable for this personal learning database.

For OpenJLPT attribution, the app includes data from OpenJLPT (CC BY-SA 4.0), which uses JMdict and KANJIDIC2 (EDRDG), Jonathan Waller's JLPT lists, and Tatoeba. Full source, version, and license details for every corpus are in [`NOTICE.md`](NOTICE.md).

## Data and privacy

- `data/downloads/` contains the downloaded archive.
- `data/reference/` contains the generated reference databases (dictionary, corpora, pitch accents, JLPT vocabulary).
- `data/private/` is reserved for personal study records.
- These directories and local database files are ignored by Git. Do not commit them.
- The public repository contains the importer, schema, and source/license information so the local data can be recreated.

## Dictionary source and license

The dictionary is [JMdict](https://www.edrdg.org/wiki/JMdict-EDICT_Dictionary_Project.html), maintained by the Electronic Dictionary Research and Development Group (EDRDG). We use the beginner-friendly JSON conversion from [`scriptin/jmdict-simplified`](https://github.com/scriptin/jmdict-simplified), which retains the upstream JMdict license. Dictionary data is made available under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); see the [EDRDG license conditions](https://www.edrdg.org/edrdg/licence.html). This is a license for the dictionary data, separate from any future license for this project's code.

When dictionary results are displayed, the CLI identifies the JMdict/EDRDG source. If the project later redistributes transformed dictionary data, that data must retain the applicable share-alike license and attribution. The current local database is generated on the user's machine and is not committed.

### Updating the dictionary

EDRDG requires software using JMdict to provide a regular update procedure and gives monthly updates as an example for web dictionary services. To refresh this pinned snapshot, review the latest `jmdict-eng-common` asset at the [`jmdict-simplified` releases](https://github.com/scriptin/jmdict-simplified/releases), verify its source and license, then update `DATA_VERSION`, `ARCHIVE_URL`, and `ARCHIVE_SHA256` in `src/japanese_learning.py` before importing it. Running `import-dictionary` recreates the local database from the pinned archive.

## Development

```sh
uv run ruff check .
uv run ruff format .
uv run python -m unittest discover -s tests
```

Python 3.13 and `uv` are pinned by the Personal Dev Kit conventions. Ruff starts with the shared rules in `pyproject.toml`; add stricter checks only when the project needs them.
