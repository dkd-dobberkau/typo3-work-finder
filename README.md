# typo3-work-finder

[![CI](https://github.com/dkd-dobberkau/typo3-work-finder/actions/workflows/ci.yml/badge.svg)](https://github.com/dkd-dobberkau/typo3-work-finder/actions/workflows/ci.yml)

A Claude Code plugin that suggests **newcomer-friendly TYPO3 Core contributions**. It reads the Forge
query ["Easy tasks"](https://forge.typo3.org/projects/typo3cms-core/issues?query_id=219) and returns:

1. **Start here:** tickets nobody is working on, ranked for first-time contributors.
2. **Waiting for review:** tickets with an open Gerrit change, which you can review or test.

## How it works

Code owns the workflow; [TypeSafe](https://typesafe.ai) **Jev** supplies the judgments:

| Step | Done by |
|---|---|
| Fetch the Forge query (JSON API) | code |
| Drop tickets on hold, in progress or assigned | code |
| Move tickets with an open Gerrit change (`tr:<issue>`) to the review list | code |
| Judge each remaining ticket: `clarity` and `newcomer_fit` (Score), `needs_decision` and `testable` (Noul) | Jev, one request per ticket, questions in parallel |
| Add one fact: is the reported TYPO3 version still maintained (get.typo3.org)? | code |
| Combine into a rank (composite scoring, adjustable with `--weights`), flag tickets that may need a decision | code |

Without `TYPESAFE_API_KEY`, a transparent heuristic ranks the tickets, and the output says so.

## Install

```bash
claude plugin marketplace add dkd-dobberkau/typo3-work-finder
claude plugin install typo3-work-finder@typo3-work-finder
```

For Jev ranking, provide `TYPESAFE_API_KEY` in the environment, for example from 1Password:

```bash
TYPESAFE_API_KEY="$(op read 'op://<vault>/<item>/TYPESAFE_API_KEY')" python3 scripts/suggest.py
```

or via `export TYPESAFE_API_KEY=…` in your shell profile. Don't paste the key into a chat.
A run over query 219 sends about 57 Jev requests and takes about 15 seconds.

Then ask Claude "what could I contribute to TYPO3?", or run the script directly:

```bash
python3 scripts/suggest.py --limit 10
python3 scripts/suggest.py --json
python3 scripts/suggest.py --weights newcomer_fit=0.4,clarity=0.3,current=0.3
```

It pairs well with [typo3-contributor](https://github.com/dkd-dobberkau/typo3-contributor-skill) for the patch
and review workflow.

## Requirements

Python 3.9+ (standard library only), network access to forge.typo3.org, review.typo3.org and
api.typesafe.ai (optional).

## Tests

```bash
python3 tests/test_suggest.py
```

The tests are offline: Forge, Gerrit and Jev are faked, and the fixtures are synthetic.

## License

GPL-2.0-or-later. See `LICENSE`.
