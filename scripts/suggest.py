#!/usr/bin/env python3
"""Suggest TYPO3 Core contributions for newcomers from a Forge query.

Code owns the workflow: it fetches the Forge query (default 219 "Easy tasks"),
drops tickets that are taken, moves tickets with an open Gerrit change to a
review list, and ranks the rest. Ranking uses TypeSafe Jev judgments when
TYPESAFE_API_KEY is set, otherwise a transparent heuristic.

Usage:
  suggest.py [--query-id 219] [--limit 10] [--json] [--weights clarity=0.3,...] [--no-jev]

Read-only: it never writes to Forge or Gerrit.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FORGE = "https://forge.typo3.org"
GERRIT = "https://review.typo3.org"
MAJORS_API = "https://get.typo3.org/api/v1/major/"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
MAX_DESCRIPTION = 4000
SKIP_STATUSES = {"On Hold", "Closed", "Rejected", "Resolved"}
REVIEW_STATUSES = {"Under Review"}
DEFAULT_WEIGHTS = {"clarity": 0.30, "newcomer_fit": 0.35, "needs_decision": 0.20, "testable": 0.15}


class RetryableError(Exception):
    """HTTP 429/529 or a transient network error."""


# --- I/O (replaceable in tests) -----------------------------------------------------

def get_json(url):
    # Forge sits behind a bot check that blocks browser-like user agents.
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "curl/8"})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
    return json.loads(text.split("\n", 1)[1] if text.startswith(")]}'") else text)


def post_json(url, body, headers):
    request = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (429, 529):
            raise RetryableError(error.code) from error
        raise


def call_jev(state, questions, api_key, post=post_json, sleep=time.sleep, attempts=4):
    body = json.dumps({"state": state, "model": JEV_MODEL, "questions": questions})
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(attempts):
        try:
            return post(JEV_URL, body, headers)["answers"]
        except RetryableError:
            if attempt == attempts - 1:
                raise
            sleep(2 ** attempt)
    return {}


# --- domain logic (pure) -----------------------------------------------------------------

def parse_issue(raw):
    fields = {field["name"]: field.get("value") or "" for field in raw.get("custom_fields", [])}
    return {
        "id": raw["id"],
        "subject": raw["subject"],
        "tracker": raw["tracker"]["name"],
        "status": raw["status"]["name"],
        "category": (raw.get("category") or {}).get("name", ""),
        "description": raw.get("description") or "",
        "typo3_version": str(fields.get("TYPO3 Version", "")),
        "complexity": str(fields.get("Complexity", "")),
        "tags": str(fields.get("Tags", "")),
        "updated_on": raw.get("updated_on", "")[:10],
        "assigned_to": (raw.get("assigned_to") or {}).get("name"),
        "url": f"{FORGE}/issues/{raw['id']}",
    }


def triage(issues, open_changes):
    """Split into work (rank), review (has a patch) and skipped (taken)."""
    work, review, skipped = [], [], []
    for issue in issues:
        changes = open_changes.get(issue["id"], [])
        if issue["status"] in SKIP_STATUSES:
            skipped.append(dict(issue, skip_reason=f"status {issue['status']}"))
        elif issue["status"] == "In Progress" or issue["assigned_to"]:
            who = issue["assigned_to"] or "someone"
            skipped.append(dict(issue, skip_reason=f"in progress / assigned to {who}"))
        elif issue["status"] in REVIEW_STATUSES or changes:
            review.append(dict(issue, changes=changes))
        else:
            work.append(issue)
    return work, review, skipped


def jev_questions():
    return {
        "clarity": {
            "type": "score",
            "instructions": "How clearly does the TYPO3 issue in `issue` describe the problem or task, "
                            "the expected result and how to reproduce or verify it?",
            "criteria": [
                "Vague: unclear what is wrong or wanted.",
                "Partly clear: the problem is named but expected behaviour or reproduction is missing.",
                "Clear: problem and expected behaviour are described; reproduction needs some guessing.",
                "Very clear: problem, expected result and concrete reproduction or verification steps.",
            ],
        },
        "newcomer_fit": {
            "type": "score",
            "instructions": "How well could a first-time TYPO3 Core contributor, who knows PHP but not the "
                            "Core internals, solve the issue in `issue` in a few hours?",
            "criteria": [
                "Needs deep Core architecture knowledge or touches many subsystems.",
                "Needs good knowledge of one subsystem and careful design work.",
                "A contained change in one area, but needs some investigation first.",
                "A small, self-contained change (label, typo, single condition or method) a newcomer can find and fix.",
            ],
        },
        "needs_decision": {
            "type": "noul",
            "instructions": "Does the issue in `issue` first need a product, UX or architecture decision "
                            "by the Core team before anyone can implement it?",
        },
        "testable": {
            "type": "noul",
            "instructions": "Can the fix for the issue in `issue` plausibly be covered by an automated unit, "
                            "functional or end-to-end test?",
        },
    }


def jev_state(issue, maintained_majors=()):
    description = issue["description"]
    if len(description) > MAX_DESCRIPTION:
        description = description[:MAX_DESCRIPTION] + " […truncated]"
    return {"issue": {
        "subject": issue["subject"],
        "tracker": issue["tracker"],
        "category": issue["category"],
        "description": description,
        "reported_for_typo3_version": issue["typo3_version"],
        "version_still_maintained": issue["typo3_version"] in maintained_majors if maintained_majors else None,
        "complexity_label": issue["complexity"],
        "tags": issue["tags"],
    }}


def composite(answers, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    signals = {
        "clarity": answers["clarity"]["score"] / 3,
        "newcomer_fit": answers["newcomer_fit"]["score"] / 3,
        "needs_decision": 1 - answers["needs_decision"]["noul"],
        "testable": answers["testable"]["noul"],
    }
    total = sum(weights.get(name, 0) for name in signals)
    if total <= 0:
        return 0.0
    value = sum(weights.get(name, 0) * signal for name, signal in signals.items()) / total
    return max(0.0, min(1.0, value))


def heuristic(issue, maintained_majors=("main", "15", "14", "13")):
    text = issue["description"].lower()
    clarity = sum(marker in text for marker in ("steps to reproduce", "expected", "actual", "reproduce")) / 4
    size = {"no-brainer": 1.0, "easy": 0.6}.get(issue["complexity"], 0.3)
    decision = 0.0 if ("ux-decision" in issue["tags"] or "decision" in issue["tags"].lower()) else 1.0
    maintained = 1.0 if issue["typo3_version"] in maintained_majors else 0.3
    length = 1.0 if 100 <= len(issue["description"]) <= 3000 else 0.5
    return round(0.30 * clarity + 0.30 * size + 0.20 * decision + 0.10 * maintained + 0.10 * length, 4)


def maintained_majors_from(majors, today):
    lts = [m for m in majors if m.get("lts") and str(m.get("maintained_until", ""))[:10] >= today]
    result = {str(int(m["version"])) for m in lts}
    if lts:
        result.add(str(int(max(m["version"] for m in lts)) + 1))  # main
    return result


# --- orchestration ---------------------------------------------------------------------

def fetch_query(query_id, get=get_json):
    issues, offset = [], 0
    while True:
        page = get(f"{FORGE}/projects/typo3cms-core/issues.json?query_id={query_id}&limit=100&offset={offset}")
        issues.extend(page["issues"])
        offset += len(page["issues"])
        if not page["issues"] or offset >= page.get("total_count", 0):
            return issues


def fetch_open_changes(issue_ids, get=get_json):
    found = {}
    for issue_id in issue_ids:
        query = urllib.parse.quote(f"project:Packages/TYPO3.CMS status:open tr:{issue_id}")
        changes = get(f"{GERRIT}/changes/?q={query}&n=5")
        if changes:
            found[issue_id] = [change["_number"] for change in changes]
    return found


def run(query_id=219, api_key=None, weights=None, get_json=get_json, jev=call_jev, today=None):
    today = today or datetime.date.today().isoformat()
    issues = [parse_issue(raw) for raw in fetch_query(query_id, get_json)]
    try:
        maintained = maintained_majors_from(get_json(MAJORS_API), today)
    except Exception:  # version info is only a hint for the judgments
        maintained = set()
    # Also look up "Under Review" tickets so the review list can link the patch directly.
    candidates = [i for i in issues if i["status"] not in SKIP_STATUSES and not i["assigned_to"]]
    open_changes = fetch_open_changes([i["id"] for i in candidates], get_json)
    work, review, skipped = triage(issues, open_changes)

    if api_key and jev:
        questions = jev_questions()

        def judge(issue):
            answers = jev(jev_state(issue, maintained), questions, api_key)
            return dict(issue, answers=answers, rank=composite(answers, weights))

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            work = list(pool.map(judge, work))
        mode = "jev"
    else:
        work = [dict(issue, rank=heuristic(issue, tuple(maintained) or ("main", "15", "14", "13"))) for issue in work]
        mode = "heuristic"

    work.sort(key=lambda issue: issue["rank"], reverse=True)
    return {"query_id": query_id, "mode": mode, "work": work, "review": review, "skipped": skipped}


def render(result, limit=10):
    print(f"# Contribution suggestions (Forge query {result['query_id']}, ranking: {result['mode']})\n")
    print("## Start here\n")
    for position, issue in enumerate(result["work"][:limit], 1):
        print(f"{position}. **#{issue['id']} {issue['subject']}** — {issue['tracker']}, "
              f"{issue['category'] or 'no category'}, TYPO3 {issue['typo3_version'] or '?'} · rank {issue['rank']:.2f}")
        answers = issue.get("answers")
        if answers:
            print(f"   clarity {answers['clarity']['score']:.1f}/3 · newcomer_fit {answers['newcomer_fit']['score']:.1f}/3 · "
                  f"needs_decision {answers['needs_decision']['noul']:.2f} · testable {answers['testable']['noul']:.2f}")
        print(f"   {issue['url']}")
    if result["review"]:
        print(f"\n## Waiting for review or testing ({len(result['review'])})\n")
        for issue in result["review"][:limit]:
            changes = ", ".join(f"{GERRIT}/c/Packages/TYPO3.CMS/+/{n}" for n in issue["changes"]) or "see Forge"
            print(f"- #{issue['id']} {issue['subject']} — {changes}")
    print(f"\n{len(result['skipped'])} ticket(s) skipped (taken or on hold). Ranking is a hint: "
          "read the ticket and ask in #typo3-cms-coredev before investing a lot of time.")


def parse_weights(text):
    weights = {}
    for part in filter(None, (text or "").split(",")):
        name, _, value = part.partition("=")
        if name not in DEFAULT_WEIGHTS:
            raise SystemExit(f"unknown weight '{name}', use: {', '.join(DEFAULT_WEIGHTS)}")
        weights[name] = float(value)
    return weights or None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--query-id", type=int, default=219)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--weights", help="e.g. clarity=0.3,newcomer_fit=0.4,needs_decision=0.2,testable=0.1")
    parser.add_argument("--no-jev", action="store_true", help="use the heuristic even if TYPESAFE_API_KEY is set")
    args = parser.parse_args(argv)
    api_key = None if args.no_jev else os.environ.get("TYPESAFE_API_KEY")
    result = run(args.query_id, api_key, parse_weights(args.weights))
    if args.json:
        json.dump(result, sys.stdout, indent=1, ensure_ascii=False)
        print()
    else:
        render(result, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
