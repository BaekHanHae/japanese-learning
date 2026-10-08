# Japanese Learning project instructions

## Project overview

- Purpose: Build a small, local-first Japanese vocabulary learning tool.
- Initial scope: Import the common-word English JMdict dataset into SQLite and search it from a CLI.
- Completion criteria: Public, reusable source with setup instructions; downloaded dictionary data and local databases stay out of Git.
- Runtime and tools: Python 3.13, `uv`, SQLite from Python's standard library, Ruff.

## Working rules

- Before changes, inspect existing code and reusable components.
- Before every change, explain the reason, plan, and affected files; wait for the user's confirmation.
- Keep changes within the approved scope and explain important choices so the user can learn.
- Keep secrets, private data, audio originals, downloaded dictionary files, and local databases out of public Git history.
- Preserve the source dictionary attribution and license conditions in the README and user-facing dictionary output.
- Follow the project's README for setup and verification commands.
