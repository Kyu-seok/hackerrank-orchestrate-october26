"""Tests for the LLM gateway (test seam 2): one ``complete(purpose, request)`` call.

Run from the repo root:

    python3 -m unittest discover -s code/evaluation -p "test_*.py"

No test touches the Anthropic API: model calls go to a fake transport, or to a
throwaway HTTP server on localhost for the built-in urllib transport.
"""

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deletion_audit import llm  # noqa: E402

FAKE_KEY = "sk-ant-test-0000-do-not-log"
REQUEST = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Extract the facts."}],
}


class FakeTransport:
    """Stands in for the Messages API: returns a canned response and counts calls."""

    def __init__(self, text='{"answer": 42}', stop_reason="end_turn", usage=None):
        self.calls = []
        self.response = {
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason,
            "usage": usage or {"input_tokens": 1200, "output_tokens": 80},
        }

    def __call__(self, body, api_key):
        self.calls.append((body, api_key))
        return self.response


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cache = self.root / "cache"
        self.dotenv = self.root / ".env"  # absent unless a test writes it

    def tearDown(self):
        self._tmp.cleanup()

    def gateway(self, env=None, transport=None):
        return llm.Gateway(cache_dir=self.cache, env=env or {}, dotenv_path=self.dotenv,
                           transport=transport or FakeTransport())

    def test_offline_cache_miss_fails_loudly_without_calling_the_model(self):
        transport = FakeTransport()
        gateway = self.gateway(env={}, transport=transport)
        with self.assertRaises(llm.CacheMiss) as raised:
            gateway.complete("evidence_extraction", REQUEST)
        message = str(raised.exception)
        self.assertIn("evidence_extraction", message)
        self.assertIn("ANTHROPIC_API_KEY", message)
        self.assertEqual(transport.calls, [])

    def test_real_call_result_is_cached_and_later_served_offline(self):
        transport = FakeTransport(text='{"deletion_requested": true}')
        online = self.gateway(env={"ANTHROPIC_API_KEY": FAKE_KEY}, transport=transport)
        self.assertEqual(online.complete("request_classification", REQUEST), {"deletion_requested": True})
        self.assertEqual(len(transport.calls), 1)
        sent_body, sent_key = transport.calls[0]
        self.assertEqual(sent_body, REQUEST)
        self.assertEqual(sent_key, FAKE_KEY)

        # Same request again: served from the cache, no second call, no key needed.
        self.assertEqual(online.complete("request_classification", REQUEST), {"deletion_requested": True})
        offline_transport = FakeTransport()
        offline = self.gateway(env={}, transport=offline_transport)
        self.assertEqual(offline.complete("request_classification", REQUEST), {"deletion_requested": True})
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(offline_transport.calls, [])

    def test_a_different_request_or_purpose_is_a_different_cache_entry(self):
        online = self.gateway(env={"ANTHROPIC_API_KEY": FAKE_KEY})
        online.complete("request_classification", REQUEST)
        offline = self.gateway(env={})
        changed = dict(REQUEST, messages=[{"role": "user", "content": "Something else."}])
        with self.assertRaises(llm.CacheMiss):
            offline.complete("request_classification", changed)
        with self.assertRaises(llm.CacheMiss):
            offline.complete("evidence_extraction", REQUEST)

    def test_every_real_call_is_recorded_in_the_usage_record_and_cache_hits_are_not(self):
        transport = FakeTransport(usage={"input_tokens": 1500, "output_tokens": 95})
        online = self.gateway(env={"ANTHROPIC_API_KEY": FAKE_KEY}, transport=transport)
        online.complete("evidence_extraction", REQUEST)
        online.complete("evidence_extraction", REQUEST)  # cache hit
        online.complete("request_classification", dict(REQUEST, model="claude-haiku-5-5"))
        calls = llm.read_usage(self.cache)
        self.assertEqual([(c["purpose"], c["model"], c["input_tokens"], c["output_tokens"]) for c in calls],
                         [("evidence_extraction", "claude-sonnet-5-5", 1500, 95),
                          ("request_classification", "claude-sonnet-5-5", 1500, 95)])

    def test_the_api_key_is_never_written_anywhere(self):
        online = self.gateway(env={"ANTHROPIC_API_KEY": FAKE_KEY})
        online.complete("evidence_extraction", REQUEST)
        written = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertTrue(written)
        for path in written:
            self.assertNotIn(FAKE_KEY, path.read_text(encoding="utf-8"), path)

    def test_the_key_can_come_from_an_uncommitted_dotenv_file(self):
        self.dotenv.write_text('# local secrets\nOTHER=1\nexport ANTHROPIC_API_KEY="%s"\n' % FAKE_KEY,
                               encoding="utf-8")
        transport = FakeTransport()
        self.gateway(env={}, transport=transport).complete("evidence_extraction", REQUEST)
        self.assertEqual([key for _, key in transport.calls], [FAKE_KEY])

    def test_offline_switch_serves_only_from_cache_even_with_a_key(self):
        transport = FakeTransport()
        gateway = self.gateway(env={"ANTHROPIC_API_KEY": FAKE_KEY, "DELETION_AUDIT_OFFLINE": "1"},
                               transport=transport)
        with self.assertRaises(llm.CacheMiss):
            gateway.complete("evidence_extraction", REQUEST)
        self.assertEqual(transport.calls, [])

    def test_unusable_responses_fail_and_are_not_cached(self):
        for transport in (FakeTransport(stop_reason="refusal"), FakeTransport(stop_reason="max_tokens"),
                          FakeTransport(text="not json")):
            with self.subTest(stop_reason=transport.response["stop_reason"]):
                online = self.gateway(env={"ANTHROPIC_API_KEY": FAKE_KEY}, transport=transport)
                with self.assertRaises(llm.GatewayError) as raised:
                    online.complete("evidence_extraction", REQUEST)
                self.assertNotIsInstance(raised.exception, llm.CacheMiss)
                self.assertNotIn(FAKE_KEY, str(raised.exception))
                with self.assertRaises(llm.CacheMiss):
                    self.gateway(env={}).complete("evidence_extraction", REQUEST)
        # The tokens were still spent, so each failed call is still in the usage record.
        self.assertEqual(len(llm.read_usage(self.cache)), 3)


class LocalMessagesApi:
    """A localhost stand-in for POST /v1/messages that replays scripted (status, body) replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                api.requests.append((self.path, dict(self.headers), json.loads(body)))
                status, reply = api.replies.pop(0)
                data = json.dumps(reply).encode("utf-8")
                self.send_response(status)
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


class UrllibTransportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_transport_posts_the_request_with_the_key_in_a_header(self):
        ok = FakeTransport(text='{"ok": true}').response
        with LocalMessagesApi([(200, ok)]) as api:
            gateway = llm.Gateway(cache_dir=self.cache, dotenv_path=None,
                                  env={"ANTHROPIC_API_KEY": FAKE_KEY, "ANTHROPIC_BASE_URL": api.url})
            self.assertEqual(gateway.complete("evidence_extraction", REQUEST), {"ok": True})
        path, headers, body = api.requests[0]
        headers = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(path, "/v1/messages")
        self.assertEqual(headers["x-api-key"], FAKE_KEY)
        self.assertEqual(headers["anthropic-version"], "2026-10-21")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(body, REQUEST)

    def test_overload_is_retried_and_a_client_error_fails_without_leaking_the_key(self):
        ok = FakeTransport(text='{"ok": true}').response
        overloaded = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
        invalid = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad schema"}}
        with LocalMessagesApi([(529, overloaded), (200, ok), (400, invalid)]) as api:
            transport = llm.UrllibTransport(base_url=api.url, retry_delay=0)
            self.assertEqual(transport(REQUEST, FAKE_KEY)["content"][0]["text"], '{"ok": true}')
            with self.assertRaises(llm.GatewayError) as raised:
                transport(REQUEST, FAKE_KEY)
        self.assertEqual(len(api.requests), 3)
        message = str(raised.exception)
        self.assertIn("400", message)
        self.assertIn("bad schema", message)
        self.assertNotIn(FAKE_KEY, message)


if __name__ == "__main__":
    unittest.main()
