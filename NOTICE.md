# NOTICE — data sources and attribution

This project's code is separate from the data it imports. The data files and
generated SQLite databases stay on the user's machine and are not redistributed
with the repository. If you redistribute a generated database or a derivative,
the licenses below apply to the data.

## JMdict (dictionary)

- Source: [JMdict](https://www.edrdg.org/wiki/JMdict-EDICT_Dictionary_Project.html),
  Electronic Dictionary Research and Development Group (EDRDG).
- Snapshot used: `jmdict-eng-common` JSON from
  [`scriptin/jmdict-simplified`](https://github.com/scriptin/jmdict-simplified).
- License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/);
  see the [EDRDG license conditions](https://www.edrdg.org/edrdg/licence.html).
- EDRDG asks software that uses JMdict to offer a regular update path. See
  “Updating the dictionary” in `README.md`.

## Tatoeba (example sentences)

- Source: [Tatoeba downloads](https://tatoeba.org/en/downloads), Japanese and
  English sentence exports plus the Japanese–English link file.
- License: CC BY 2.0 FR for contributed sentences, CC0 1.0 for the CC0 export.
  Each imported row keeps its own license label and, where available, the
  Tatoeba author and sentence ID.
- Tatoeba content is community-contributed; translations may be inaccurate.

## KFTT (Kyoto Free Translation Task)

- Source: [KFTT 1.0](https://www.phontron.com/kftt/), NICT.
- License: CC BY-SA 3.0.
- Content is derived from Wikipedia Kyoto articles.

## BSD (business dialogue corpus)

- Source: [tsuruoka-lab/BSD](https://github.com/tsuruoka-lab/BSD), University of
  Tokyo, pinned at commit `050fd4241da458377c1ce26b2c31b0af0a20e444`.
- License: CC BY-NC-SA. Non-commercial use only; share-alike applies to
  derivatives.
- Scenario-written dialogue, not recorded native speech.

## OpenJLPT (grammar points, graded examples, vocabulary)

- Source: [evanclan/OpenJLPT](https://github.com/evanclan/OpenJLPT), pinned at
  commit `0d1d3410bec90bd4098a7c72de820543cb4f707c`.
- License: CC BY-SA 4.0.
- Upstream credits carried by OpenJLPT: JMdict and KANJIDIC2 (EDRDG,
  CC BY-SA 4.0), Jonathan Waller's JLPT lists, and Tatoeba (CC BY 2.0 FR).
- N5–N1 labels are community estimates, not official JLPT word or grammar
  lists.

## Kanjium (pitch accents)

- Source: [mifunetoshiro/kanjium](https://github.com/mifunetoshiro/kanjium),
  `data/source_files/raw/accents.txt`, pinned at commit
  `685d4d723d6d20bf9beb169103aeac188eb067ad` (SHA-256
  `8bd0dd127dab32ceec94cb03ab1ba6b68858ea73421dfa1731af2f373deb4f20`).
- License: CC BY-SA 4.0.
- Pitch-accent numbers are dictionary data, not a substitute for listening
  practice.

## Janome (Japanese morphological analyzer)

- Source: [mocobeta/janome](https://github.com/mocobeta/janome), installed as a
  Python dependency (version 0.5.0 or newer).
- License: Apache License 2.0.
- Used only to segment reading sentences and resolve inflected forms to
  dictionary entries; its bundled dictionary is not redistributed here.

## Rebuilding and verifying sources

`src/import_learning_materials.py` pins every corpus file by SHA-256 and records
the source, version, license, attribution, and source URL in the
`source_manifest` table of the generated database. `src/import_pitch_accents.py`
pins the Kanjium file the same way, and `src/import_jlpt_vocab.py` reads the
already-pinned OpenJLPT archive. `src/japanese_learning.py` does the same for
the dictionary archive. To refresh a source, update its pinned version and
checksum, re-import, and review the new license terms first.
