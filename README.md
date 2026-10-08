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

## Data and privacy

- `data/downloads/` contains the downloaded archive.
- `data/reference/` contains the generated dictionary database.
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
```

Python 3.13 and `uv` are pinned by the Personal Dev Kit conventions. Ruff starts with the shared rules in `pyproject.toml`; add stricter checks only when the project needs them.
