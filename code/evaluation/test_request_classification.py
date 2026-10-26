"""Deletion-request classification, end to end (CLI seams only).

Run from the repo root:

    python3 -m unittest discover -s code/evaluation -p "test_*.py"

The one-time command ``code/classify_requests.py`` is run against a throwaway
HTTP server on localhost that stands in for the Messages API
(``ANTHROPIC_BASE_URL``), with a fake key and a throwaway cache. The pipeline
CLI then reads that cache offline. Nothing touches the network.
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
FAKE_KEY = "sk-ant-test-0000-do-not-log"

DELETION = ("I am asking you to remove my account and the personal information linked to it.")
NOT_DELETION = "Please send me a copy of my last invoice. I want to keep my account."
SPANISH_DELETION = "Solicito la eliminación permanente de la cuenta asociada a este correo."


class FakeMessagesAPI:
    """Answers each classification batch like the model would: a decision per request id.

    A text counts as a deletion request unless it says it wants to keep the account.
    """

    def __init__(self):
        self.calls = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api.calls.append(body)
                items = json.loads(body["messages"][0]["content"][0]["text"])["requests"]
                decisions = [{"id": it["id"], "deletion_requested": "keep my account" not in it["text"],
                              "reason": "test double"} for it in items]
                reply = {"id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
                         "content": [{"type": "text", "text": json.dumps({"decisions": decisions})}],
                         "stop_reason": "end_turn", "usage": {"input_tokens": 900, "output_tokens": 40}}
                data = json.dumps(reply).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def base_env(cache_dir):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "DELETION_AUDIT_OFFLINE")}
    env["DELETION_AUDIT_LLM_CACHE"] = str(cache_dir)
    return env


def run_cli(args, env):
    return subprocess.run([sys.executable] + [str(a) for a in args], cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)


def write_requests(path, texts_by_case):
    """Requests for real samples (case_05: surviving account; case_15: active data flow) with our texts."""
    with open(DATASET / "sample_deletion_requests.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = {r["case_id"]: r for r in reader}
        fields = reader.fieldnames
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for case_id, text in sorted(texts_by_case.items()):
            writer.writerow(dict(rows[case_id], request_text=text))


def answers(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(f)}


class ClassificationCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cache = self.tmp / "llm_cache"
        self.requests = self.tmp / "requests.csv"
        write_requests(self.requests, {"case_05": DELETION, "case_15": NOT_DELETION, "case_09": DELETION,
                                       "case_22": SPANISH_DELETION})

    def tearDown(self):
        self._tmp.cleanup()

    def classify(self, api):
        env = base_env(self.cache)
        env.update(ANTHROPIC_API_KEY=FAKE_KEY, ANTHROPIC_BASE_URL=api.url)
        return run_cli([REPO_ROOT / "code" / "classify_requests.py", self.requests], env)

    def audit(self, *extra):
        out = self.tmp / "out.csv"
        env = base_env(self.cache)
        env["DELETION_AUDIT_OFFLINE"] = "1"
        done = run_cli([REPO_ROOT / "code" / "main.py", "--requests", self.requests, "--output", out] + list(extra),
                       env)
        return done, out

    def test_classified_requests_are_batched_and_non_deletion_is_not_applicable(self):
        with FakeMessagesAPI() as api:
            done = self.classify(api)
        self.assertEqual(done.returncode, 0, done.stderr)
        # Three distinct texts across four requests: one batched Haiku call.
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0]["model"], "claude-haiku-5-5")

        done, out = self.audit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("classification", done.stderr)
        got = answers(out)
        self.assertEqual(got["case_15"], ("NOT_APPLICABLE", []))
        self.assertEqual(got["case_05"][0], "INCOMPLETE")
        self.assertEqual(got["case_22"][0], "INCOMPLETE")  # Spanish deletion request is audited

    def test_rerun_makes_no_model_calls(self):
        with FakeMessagesAPI() as api:
            self.classify(api)
            done = self.classify(api)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(api.calls), 1)
        self.assertIn("0 new", done.stdout)

    def test_key_is_never_printed_or_written(self):
        with FakeMessagesAPI() as api:
            done = self.classify(api)
        self.assertNotIn(FAKE_KEY, done.stdout + done.stderr)
        for path in self.cache.rglob("*"):
            if path.is_file():
                self.assertNotIn(FAKE_KEY, path.read_text(encoding="utf-8"), path)

    def test_without_a_key_the_command_fails_clearly(self):
        done = run_cli([REPO_ROOT / "code" / "classify_requests.py", self.requests], base_env(self.cache))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ANTHROPIC_API_KEY", done.stderr)
        self.assertNotIn("Traceback", done.stderr)


class UnclassifiedRequests(unittest.TestCase):
    """Before the one-time command has run, the pipeline still answers every request."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.requests = self.tmp / "requests.csv"
        write_requests(self.requests, {"case_05": DELETION, "case_15": NOT_DELETION})
        self.env = base_env(self.tmp / "empty_cache")
        self.env["DELETION_AUDIT_OFFLINE"] = "1"
        self.out = self.tmp / "out.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_decisions_are_audited_as_deletion_requests_with_a_warning(self):
        done = run_cli([REPO_ROOT / "code" / "main.py", "--requests", self.requests, "--output", self.out],
                       self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("2 request(s) have no cached deletion-request classification", done.stderr)
        self.assertIn("python3 code/classify_requests.py", done.stderr)
        got = answers(self.out)
        self.assertEqual(got["case_05"][0], "INCOMPLETE")
        self.assertEqual(got["case_15"][0], "INCOMPLETE")

    def test_strict_run_fails_loudly_and_writes_nothing(self):
        done = run_cli([REPO_ROOT / "code" / "main.py", "--requests", self.requests, "--output", self.out,
                        "--strict"], self.env)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("case_05", done.stderr)
        self.assertIn("python3 code/classify_requests.py", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
