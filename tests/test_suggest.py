"""Tests for scripts/suggest.py (offline: Forge, Gerrit and Jev are faked)."""
import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("suggest", ROOT / "scripts" / "suggest.py")
suggest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suggest)

QUERY = json.loads((ROOT / "tests" / "fixtures" / "forge-query.json").read_text())


def issues():
    return [suggest.parse_issue(raw) for raw in QUERY["issues"]]


def by_id(items, issue_id):
    return next(item for item in items if item["id"] == issue_id)


class ParseTest(unittest.TestCase):
    def test_fields(self):
        issue = by_id(issues(), 1004)
        self.assertEqual(issue["subject"], "Scheduler task label wrong")
        self.assertEqual(issue["status"], "In Progress")
        self.assertEqual(issue["complexity"], "easy")
        self.assertEqual(issue["typo3_version"], "14")
        self.assertEqual(issue["assigned_to"], "Somebody")
        self.assertEqual(issue["url"], "https://forge.typo3.org/issues/1004")

    def test_unassigned(self):
        self.assertIsNone(by_id(issues(), 1001)["assigned_to"])


class TriageTest(unittest.TestCase):
    def test_buckets(self):
        work, review, skipped = suggest.triage(issues(), open_changes={1006: [96999]})
        self.assertEqual(sorted(i["id"] for i in work), [1001, 1002, 1005])
        # Under Review status or an open Gerrit change -> review list
        self.assertEqual(sorted(i["id"] for i in review), [1003, 1006])
        self.assertEqual(by_id(review, 1006)["changes"], [96999])
        # assigned / in progress -> skipped with a reason
        self.assertEqual([(i["id"], i["skip_reason"]) for i in skipped], [(1004, "in progress / assigned to Somebody")])


class QuestionsTest(unittest.TestCase):
    def test_question_set(self):
        questions = suggest.jev_questions()
        self.assertEqual(set(questions), {"clarity", "newcomer_fit", "needs_decision", "testable"})
        self.assertEqual(questions["needs_decision"]["type"], "noul")
        self.assertEqual(questions["testable"]["type"], "noul")
        for name in ("clarity", "newcomer_fit"):
            self.assertEqual(questions[name]["type"], "score")
            self.assertTrue(2 <= len(questions[name]["criteria"]) <= 10)

    def test_state_is_bounded(self):
        issue = dict(by_id(issues(), 1001), description="x" * 20000)
        state = suggest.jev_state(issue)
        self.assertLessEqual(len(state["issue"]["description"]), suggest.MAX_DESCRIPTION + 20)
        self.assertEqual(state["issue"]["subject"], issue["subject"])


class RankingTest(unittest.TestCase):
    def answers(self, clarity, newcomer, decision, testable):
        return {
            "clarity": {"type": "score", "score": clarity},
            "newcomer_fit": {"type": "score", "score": newcomer},
            "needs_decision": {"type": "noul", "noul": decision},
            "testable": {"type": "noul", "noul": testable},
        }

    def test_composite_prefers_clear_small_testable(self):
        good = suggest.composite(self.answers(3, 3, 0.05, 0.9))
        vague = suggest.composite(self.answers(0.5, 1, 0.8, 0.3))
        self.assertGreater(good, 0.85)
        self.assertGreater(good - vague, 0.4)
        self.assertTrue(0.0 <= vague <= good <= 1.0)

    def test_unmaintained_version_ranks_lower(self):
        answers = self.answers(3, 3, 0.05, 0.9)
        self.assertGreater(suggest.composite(answers, current=True), suggest.composite(answers, current=False))
        # unknown maintenance info is neutral
        self.assertAlmostEqual(suggest.composite(answers, current=None), suggest.composite(answers, current=True))

    def test_custom_weights(self):
        answers = self.answers(0, 3, 0.0, 0.0)
        self.assertAlmostEqual(suggest.composite(answers, {"newcomer_fit": 1.0}), 1.0)

    def test_heuristic_fallback_without_key(self):
        items = {i["id"]: suggest.heuristic(i) for i in issues()}
        self.assertGreater(items[1001], items[1002])  # no-brainer with repro steps beats vague ux-decision
        self.assertGreater(items[1006], items[1005])  # repro steps + maintained version beat TYPO3 8
        self.assertTrue(all(0.0 <= value <= 1.0 for value in items.values()))


class EndToEndTest(unittest.TestCase):
    def test_run_with_fake_services(self):
        calls = {"jev": 0}

        def fake_get_json(url):
            if "forge.typo3.org" in url:
                return QUERY
            if "get.typo3.org" in url:
                return [{"version": 14.0, "lts": 14.3, "maintained_until": "2029-06-30"},
                        {"version": 13.0, "lts": 13.4, "maintained_until": "2027-12-31"}]
            if "review.typo3.org" in url:
                if "1006" in url:
                    return [{"_number": 96999}]
                if "1003" in url:
                    return [{"_number": 96111}]
                return []
            raise AssertionError(url)

        def fake_jev(state, questions, api_key):
            calls["jev"] += 1
            clear = "Steps to reproduce" in state["issue"]["description"]
            return {
                "clarity": {"type": "score", "score": 3 if clear else 0.5},
                "newcomer_fit": {"type": "score", "score": 3 if state["issue"]["complexity_label"] == "no-brainer" else 1.5},
                "needs_decision": {"type": "noul", "noul": 0.9 if "ux-decision" in state["issue"]["tags"] else 0.1},
                "testable": {"type": "noul", "noul": 0.8 if clear else 0.3},
            }

        result = suggest.run(query_id=219, api_key="test", get_json=fake_get_json, jev=fake_jev, today="2026-10-01")
        self.assertEqual(calls["jev"], 3)  # only the work list is scored
        self.assertEqual([item["id"] for item in result["work"]][0], 1001)
        self.assertEqual(result["mode"], "jev")
        self.assertEqual(sorted(i["id"] for i in result["review"]), [1003, 1006])
        self.assertEqual(by_id(result["review"], 1003)["changes"], [96111])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            suggest.render(result, limit=2)
        text = buffer.getvalue()
        self.assertIn("https://forge.typo3.org/issues/1001", text)
        self.assertIn("Waiting for review", text)
        self.assertIn("https://review.typo3.org/c/Packages/TYPO3.CMS/+/96111", text)
        self.assertIn("clarity", text)

    def test_decision_warning(self):
        issue = {"id": 1, "subject": "S", "tracker": "Feature", "category": "", "typo3_version": "14", "url": "u",
                 "rank": 0.8, "current": True, "answers": {
                     "clarity": {"score": 3}, "newcomer_fit": {"score": 3},
                     "needs_decision": {"noul": 0.6}, "testable": {"noul": 0.9}}}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            suggest.render({"query_id": 219, "mode": "jev", "work": [issue], "review": [], "skipped": []})
        self.assertIn("may need a Core team decision first", buffer.getvalue())

    def test_run_without_key_uses_heuristic(self):
        result = suggest.run(query_id=219, api_key=None,
                             get_json=lambda url: QUERY if "forge" in url else [],
                             jev=None, today="2026-10-01")
        self.assertEqual(result["mode"], "heuristic")
        self.assertTrue(result["work"])


class JevRequestTest(unittest.TestCase):
    def test_request_body_and_retry(self):
        sent = []

        def fake_post(url, body, headers):
            sent.append((url, json.loads(body), headers))
            if len(sent) == 1:
                raise suggest.RetryableError(429)
            return {"answers": {"testable": {"type": "noul", "noul": 0.7}}}

        answers = suggest.call_jev({"issue": {}}, {"testable": {"type": "noul", "instructions": "x"}},
                                   api_key="k", post=fake_post, sleep=lambda seconds: None)
        self.assertEqual(answers["testable"]["noul"], 0.7)
        url, body, headers = sent[-1]
        self.assertEqual(url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual(len(sent), 2)


if __name__ == "__main__":
    unittest.main()
