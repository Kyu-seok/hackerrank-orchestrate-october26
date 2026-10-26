"""Tests for the token usage report command (code/usage_report.py), run as a CLI.

Run from the repo root:

    python3 -m unittest discover -s code/evaluation -p "test_*.py"

Each test builds a small LLM cache folder (usage.jsonl plus cache entries) and a
request file, runs the command, and reads the Markdown it writes. Expected
numbers are worked out by hand from the fixture and the documented prices
(Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50 per million input / output tokens).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND = REPO_ROOT / "code" / "usage_report.py"

# (model, purpose, input, output, cache_key, still cached?)
CALLS = [
    ("claude-sonnet-5-5", "evidence_extraction", 1000, 200, "a1", True),
    ("claude-sonnet-5-5", "evidence_extraction", 3000, 400, "a2", True),
    ("claude-haiku-5-5", "request_classification", 500, 100, "b1", False),  # superseded run
    ("claude-haiku-5-5", "request_classification", 600, 300, "b2", True),
]


class UsageReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cache = root / "llm_cache"
        cache.mkdir()
        with open(cache / "usage.jsonl", "w", encoding="utf-8") as f:
            for i, (model, purpose, inp, out, key, kept) in enumerate(CALLS):
                f.write(json.dumps({
                    "recorded_at": "2026-10-26T10:0%d:00Z" % i, "model": model, "purpose": purpose,
                    "input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0, "cache_key": key}) + "\n")
                if kept:
                    (cache / purpose).mkdir(exist_ok=True)
                    (cache / purpose / (key + ".json")).write_text("{}", encoding="utf-8")
        requests = root / "requests.csv"
        requests.write_text("case_id,email\n" + "".join("case_%d,x@example.com\n" % i for i in range(5)),
                            encoding="utf-8")
        cls.out = root / "usage_report.md"
        subprocess.run([sys.executable, str(COMMAND), "--cache-dir", str(cache), "--requests",
                        str(requests), "--output", str(cls.out)], check=True, cwd=str(REPO_ROOT))
        cls.report = cls.out.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_final_run_is_totalled_per_model_and_overall(self):
        self.assertIn("| claude-sonnet-5-5 | Anthropic | evidence_extraction | 2 | 4,000 | 600 | 4,600 "
                      "| $0.014000 |", self.report)
        self.assertIn("| claude-haiku-5-5 | Anthropic | request_classification | 1 | 600 | 300 | 900 "
                      "| $0.000210 |", self.report)
        self.assertIn("| **Overall** | | | 3 | 4,600 | 900 | 5,500 | $0.014210 |", self.report)

    def test_final_run_is_averaged_over_every_request(self):
        # 5 requests; final run: 4,600 input + 900 output tokens, $0.014210.
        self.assertIn("| Requests in the final run | 5 |", self.report)
        self.assertIn("| Average input tokens per request | 920.0 |", self.report)
        self.assertIn("| Average output tokens per request | 180.0 |", self.report)
        self.assertIn("| Average total tokens per request | 1,100.0 |", self.report)
        self.assertIn("| Estimated cost per request (USD) | $0.002842 |", self.report)

    def test_superseded_calls_are_listed_separately_and_in_the_grand_total(self):
        # The classification call whose cache entry is gone is not in the final run, but shown.
        final, superseded = self.report.split("## Superseded calls", 1)
        self.assertIn("| claude-haiku-5-5 | Anthropic | request_classification | 1 | 500 | 100 | 600 "
                      "| $0.000100 |", superseded)
        self.assertNotIn("| 500 | 100 |", final)
        self.assertIn("| **All recorded calls** | | | 4 | 5,100 | 1,000 | 6,100 | $0.014310 |", superseded)

    def test_report_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            again = Path(tmp) / "again.md"
            subprocess.run([sys.executable, str(COMMAND), "--cache-dir", str(self.out.parent / "llm_cache"),
                            "--requests", str(self.out.parent / "requests.csv"), "--output", str(again)],
                           check=True, cwd=str(REPO_ROOT))
            self.assertEqual(again.read_text(encoding="utf-8"), self.report)


if __name__ == "__main__":
    unittest.main()
