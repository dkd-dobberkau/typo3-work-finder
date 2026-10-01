# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `scripts/suggest.py`: reads a Forge query (default 219 "Easy tasks"), skips taken tickets, lists tickets with open Gerrit changes for review, and ranks the rest with TypeSafe Jev (heuristic fallback without an API key).
- Claude Code plugin packaging with its own marketplace.
