"""LLM gateway: the only place the pipeline talks to a model (ADR 0001).

``Gateway.complete(purpose, request)`` takes a purpose label and a Messages API
request body and returns the model's structured (JSON) answer.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .dataset import REPO_ROOT

API_KEY_VAR = "ANTHROPIC_API_KEY"
USAGE_FILE = "usage.jsonl"
OFFLINE_VAR = "DELETION_AUDIT_OFFLINE"
CACHE_DIR_VAR = "DELETION_AUDIT_LLM_CACHE"
BASE_URL_VAR = "ANTHROPIC_BASE_URL"
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2026-10-21"
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
DEFAULT_CACHE_DIR = REPO_ROOT / "code" / "llm_cache"
DEFAULT_DOTENV = REPO_ROOT / ".env"


class GatewayError(RuntimeError):
    """A model call could not produce a usable result."""


class CacheMiss(GatewayError):
    """Offline (no API key) and the request has no cached result."""


def read_usage(cache_dir=None):
    """Every recorded real model call, oldest first (one dict per call)."""
    path = Path(cache_dir or os.environ.get(CACHE_DIR_VAR) or DEFAULT_CACHE_DIR) / USAGE_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cache_key(purpose, request):
    canonical = json.dumps({"purpose": purpose, "request": request}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class UrllibTransport:
    """POST /v1/messages with the standard library; returns the parsed response.

    Retries rate limits, overloads and server errors with exponential backoff.
    Error messages carry the HTTP status and the API's error message only, never
    the request headers.
    """

    def __init__(self, base_url=None, timeout=600, retries=3, retry_delay=2.0):
        self.url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/v1/messages"
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay

    def __call__(self, body, api_key):
        data = json.dumps(body).encode("utf-8")
        headers = {"content-type": "application/json", "x-api-key": api_key,
                   "anthropic-version": API_VERSION}
        attempt = 0
        while True:
            request = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                status, detail = err.code, _api_error_message(err)
            except (urllib.error.URLError, OSError) as err:
                status, detail = None, "connection failed (%s)" % type(err).__name__
            retryable = status is None or status in RETRYABLE_STATUS
            if not retryable or attempt >= self.retries:
                raise GatewayError("Claude API request failed (HTTP %s): %s" % (status or "-", detail))
            time.sleep(self.retry_delay * (2 ** attempt))
            attempt += 1


def _api_error_message(err):
    try:
        payload = json.loads(err.read().decode("utf-8"))
        return "%s: %s" % (payload["error"]["type"], payload["error"]["message"])
    except Exception:  # noqa: BLE001 - any unreadable body becomes the bare reason
        return str(err.reason)


class Gateway:
    """Cache-first access to the Messages API.

    ``env`` defaults to ``os.environ``; ``dotenv_path`` is an optional uncommitted
    ``.env`` read only for ``ANTHROPIC_API_KEY``. The key is held in memory and
    passed to the transport; it is never logged, cached or put in an error message.
    """

    def __init__(self, cache_dir=None, env=None, dotenv_path=DEFAULT_DOTENV, transport=None, offline=False):
        self._env = os.environ if env is None else env
        self.cache_dir = Path(cache_dir or self._env.get(CACHE_DIR_VAR) or DEFAULT_CACHE_DIR)
        self._offline = offline
        self._dotenv_path = Path(dotenv_path) if dotenv_path else None
        self._transport = transport or UrllibTransport(base_url=self._env.get(BASE_URL_VAR))

    @property
    def online(self):
        """True when a cache miss may call the model."""
        if self._offline or _truthy(self._env.get(OFFLINE_VAR)):
            return False
        return self._api_key() is not None

    def complete(self, purpose, request):
        """Structured (JSON) answer to a Messages API ``request``, cached by content hash."""
        key = cache_key(purpose, request)
        path = self.cache_dir / purpose / (key + ".json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["result"]
        if not self.online:
            raise CacheMiss(
                "No cached LLM result for purpose %r (cache key %s) and the gateway is offline "
                "(%s not set, or %s=1). Set %s in the environment or an uncommitted .env to "
                "call the model and fill the cache." % (purpose, key[:12], API_KEY_VAR, OFFLINE_VAR,
                                                        API_KEY_VAR))
        response = self._transport(request, self._api_key())
        record = self._record_usage(purpose, request, response, key)
        result = _structured_result(purpose, response)
        entry = {"purpose": purpose, "model": record["model"], "result": result,
                 "usage": {k: record[k] for k in ("input_tokens", "output_tokens")}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return result

    def _record_usage(self, purpose, request, response, key):
        usage = response.get("usage") or {}
        record = {
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "purpose": purpose,
            "model": response.get("model") or request.get("model"),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cache_key": key,
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_dir / USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def _api_key(self):
        value = self._env.get(API_KEY_VAR) or _dotenv_value(self._dotenv_path, API_KEY_VAR)
        return (value or "").strip() or None


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _dotenv_value(path, name):
    """Value of ``name`` in a simple KEY=VALUE .env file, or None."""
    if path is None or not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")
    return None


def _structured_result(purpose, response):
    stop = response.get("stop_reason")
    if stop not in ("end_turn", "stop_sequence"):
        raise GatewayError("Model call for purpose %r stopped with stop_reason=%r; nothing was cached."
                           % (purpose, stop))
    text = "".join(block.get("text", "") for block in response.get("content", [])
                   if block.get("type") == "text")
    try:
        return json.loads(text)
    except ValueError:
        raise GatewayError("Model call for purpose %r did not return JSON; nothing was cached." % purpose)
