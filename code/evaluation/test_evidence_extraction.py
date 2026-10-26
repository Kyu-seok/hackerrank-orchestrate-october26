"""PDF/image evidence extraction, end to end (test seam 1: CLI + output).

Run from the repo root:

    python3 -m unittest discover -s code/evaluation -p "test_*.py"

The one-time extraction is simulated: ``documents.extract`` (the function the
extraction command runs per file) is driven by a fake transport into a
throwaway cache, and the pipeline CLI is pointed at that cache with
``DELETION_AUDIT_LLM_CACHE``. Nothing touches the network.
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
sys.path.insert(0, str(REPO_ROOT / "code"))

from deletion_audit import llm  # noqa: E402
from deletion_audit.evidence import documents  # noqa: E402

FAKE_KEY = "sk-ant-test-0000-do-not-log"
ACCOUNT_CONSOLE = DATASET / "evidence" / "images" / "account_admin_console_20260926.png"  # evidence_04

# What a vision model reads off evidence_04 (Customer Operations console, captured 2026-09-26).
ACCOUNT_CONSOLE_EXTRACTION = {
    "document_kind": "customer account admin console",
    "records": [{
        "system_id": "account_service", "resource_id": "account_5762", "record_type": "customer_profile",
        "state": "PRESENT", "name": "Haruka Sato", "email": "haruka.s1838@zoho.com",
        "phone": "+81 90 7610 2507", "email_hash": None, "user_id": "user_11", "order_id": None,
        "ticket_id": None, "file_name": None, "status": "Silver", "retention_until": None,
        "related_references": ["ORD-20265762", "ORD-20265518", "CS-8538", "support_9538"],
        "notes": "Live customer profile with orders and support history.",
    }],
}


class CannedExtraction:
    def __init__(self, result):
        self.text = json.dumps(result)
        self.calls = 0

    def __call__(self, body, api_key):
        self.calls += 1
        return {"model": body["model"], "content": [{"type": "text", "text": self.text}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 1800, "output_tokens": 300}}


def offline_env(cache_dir):
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["DELETION_AUDIT_LLM_CACHE"] = str(cache_dir)
    env["DELETION_AUDIT_OFFLINE"] = "1"
    return env


def write_requests(path, case_ids):
    with open(DATASET / "deletion_requests.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["case_id"] in case_ids]
        fields = reader.fieldnames
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_cli(args, env):
    return subprocess.run([sys.executable] + [str(a) for a in args], cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)


def answers(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(f)}


class ExtractedEvidenceInThePipeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cache = self.tmp / "llm_cache"
        self.requests = self.tmp / "requests.csv"
        # case_34: Haruka Sato (user_11) asked for deletion on 2026-09-24; audit at 2026-09-27T13:00.
        write_requests(self.requests, {"case_34"})

    def tearDown(self):
        self._tmp.cleanup()

    def audit(self):
        out = self.tmp / "out.csv"
        done = run_cli([REPO_ROOT / "code" / "main.py", "--requests", self.requests, "--output", out],
                       offline_env(self.cache))
        self.assertEqual(done.returncode, 0, done.stderr)
        return answers(out)["case_34"]

    def test_screenshot_showing_a_live_account_is_cited_as_the_remaining_record(self):
        gateway = llm.Gateway(cache_dir=self.cache, env={"ANTHROPIC_API_KEY": FAKE_KEY}, dotenv_path=None,
                              transport=CannedExtraction(ACCOUNT_CONSOLE_EXTRACTION))
        documents.extract(gateway, ACCOUNT_CONSOLE)

        status, steps = self.audit()
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(
            [(s["phase"], s["system_id"], s["resource_id"], s["operation"], s["evidence_id"]) for s in steps],
            [("FINDING", "account_service", "account_5762", "REPORT_REMAINING_RECORD", "evidence_04"),
             ("REMEDIATION", "account_service", "account_5762", "DELETE_RECORD", ""),
             ("VERIFICATION", "account_service", "account_5762", "VERIFY_RECORD_ABSENT", "")])


class ExtractionCommand(unittest.TestCase):
    """``code/extract_evidence.py``: the one-time pass that fills the extraction cache."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "llm_cache"

    def tearDown(self):
        self._tmp.cleanup()

    def run_command(self, *file_ids):
        env = offline_env(self.cache)
        env.pop("DELETION_AUDIT_OFFLINE")
        return run_cli([REPO_ROOT / "code" / "extract_evidence.py"] + list(file_ids), env)

    def test_without_a_key_it_fails_clearly_and_writes_nothing(self):
        done = self.run_command()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ANTHROPIC_API_KEY", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertFalse(any(self.cache.rglob("*.json")) if self.cache.exists() else False)

    def test_already_extracted_files_are_served_from_the_cache_without_a_key(self):
        gateway = llm.Gateway(cache_dir=self.cache, env={"ANTHROPIC_API_KEY": FAKE_KEY}, dotenv_path=None,
                              transport=CannedExtraction(ACCOUNT_CONSOLE_EXTRACTION))
        documents.extract(gateway, ACCOUNT_CONSOLE)
        done = self.run_command("evidence_04")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("evidence_04", done.stdout)
        self.assertIn("1 record", done.stdout)


if __name__ == "__main__":
    unittest.main()
