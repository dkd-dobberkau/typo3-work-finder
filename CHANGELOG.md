# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-10-01

### Added
- `scripts/suggest.py`: reads a Forge query (default 219 "Easy tasks"), skips taken tickets, lists tickets with open Gerrit changes for review, and ranks the rest with TypeSafe Jev (heuristic fallback without an API key).
- Ranking signal for maintained TYPO3 versions (get.typo3.org) and a warning for tickets that may need a Core team decision.
- Claude Code plugin packaging with its own marketplace.

[0.1.0]: https://github.com/dkd-dobberkau/typo3-work-finder/releases/tag/v0.1.0
