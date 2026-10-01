# Contributing

- Run `python3 tests/test_suggest.py`; CI runs it on Ubuntu and macOS.
- Keep `scripts/suggest.py` dependency-free (standard library only).
- New judgments: add the question in `jev_questions()`, map it in `composite()`, and add a test.
  Verify wording against real tickets before relying on it.
- Fixtures must be synthetic. Never commit real Forge descriptions or comments.
- On release, bump `.claude-plugin/plugin.json` and the CHANGELOG to the same version.
