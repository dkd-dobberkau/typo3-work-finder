---
name: typo3-work-finder
description: Use when someone wants to contribute to TYPO3 Core but does not know what to work on - looking for easy or newcomer-friendly Forge issues, a first contribution, something for a code sprint, or patches that need review or testing.
---

# Find a TYPO3 Core contribution

Skill directory: `${CLAUDE_SKILL_DIR}`. Scripts below are relative to it.

## Overview

`scripts/suggest.py` reads a Forge query (default 219, "Easy tasks") and returns two lists:
1. **Start here:** tickets nobody is working on, ranked for newcomers.
2. **Waiting for review:** tickets that already have an open Gerrit change. Reviewing and testing those is often the fastest useful contribution.

Code does the hard filtering: status, assignee, open Gerrit change. Ranking uses TypeSafe Jev judgments if `TYPESAFE_API_KEY` is set (clarity, newcomer fit, needs a decision, testable). Without a key it falls back to a heuristic, and the output says which mode ran.

## Run

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/suggest.py --limit 10
python3 ${CLAUDE_SKILL_DIR}/scripts/suggest.py --json            # full result incl. raw judgments
python3 ${CLAUDE_SKILL_DIR}/scripts/suggest.py --weights newcomer_fit=0.5,clarity=0.3,testable=0.2
python3 ${CLAUDE_SKILL_DIR}/scripts/suggest.py --query-id <other saved Forge query>
```

The script only reads; it never writes to Forge or Gerrit. With Jev it sends one request per candidate ticket, roughly 50–60 for query 219.

## Present the result

- Show the top 5 with the one-line reason from the judgments, e.g. "very clear, small, no decision needed, testable".
- Open the chosen ticket (`https://forge.typo3.org/issues/<id>.json`, plus `?include=journals` for comments). Check the premise: is it still reproducible on `main`, and did anybody comment that they are working on it?
- Suggest that the human comments on Forge ("I will create a patch for this") or asks in Slack `#typo3-cms-coredev`. The human posts it.
- Hand over to the `typo3-contributor` skill if it is installed: `references/patch.md` for a new patch, `references/review.md` for the review list.

## Common mistakes

| Mistake | Instead |
|---|---|
| Treating the rank as a verdict | It is a hint. Read the ticket; old "easy" labels are often wrong |
| Picking a ticket from the review list to patch again | Review or test the existing change instead |
| Starting work on a ticket for an unmaintained TYPO3 version | Reproduce on `main` first |
| Showing a heuristic ranking as if Jev had judged it | Say which mode ran (`ranking: jev` or `heuristic`) |
