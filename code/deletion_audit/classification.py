"""Does ``request_text`` ask for deletion? (ADR 0001: one of the two LLM edges.)

Claude Haiku 5.5 reads request texts in batches through the LLM gateway and
answers, per text, a structured ``deletion_requested`` boolean plus a short
reason (prompt: ``prompts/request_classification.md``). Each answer is stored
as one decision file keyed by the SHA-256 of the request text, under
``<llm cache>/request_decisions/``, so identical texts share one decision and a
rerun makes no model call.

``Classifier.fill(texts)`` is the one-time pass (``code/classify_requests.py``)
that calls the model for texts without a decision. ``Classifier.decide(request)``
is what normal pipeline runs use: cache only, ``True``/``False``, or ``None``
when no decision is cached.
"""

import hashlib
import json
from pathlib import Path

from . import llm

PURPOSE = "request_classification"
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 8000
BATCH_SIZE = 25
DECISIONS_DIR = "request_decisions"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "request_classification.md"

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decisions"],
    "properties": {"decisions": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "deletion_requested", "reason"],
        "properties": {"id": {"type": "string"},
                       "deletion_requested": {"type": "boolean"},
                       "reason": {"type": "string"}},
    }}},
}


def text_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_request(texts):
    """The Messages API request classifying ``texts`` (one batch); ids are ``r1``, ``r2``, ..."""
    items = [{"id": "r%d" % (i + 1), "text": text} for i, text in enumerate(texts)]
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": PROMPT_PATH.read_text(encoding="utf-8"),
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        "messages": [{"role": "user", "content": [{"type": "text", "text": json.dumps(
            {"requests": items}, ensure_ascii=False, indent=1)}]}],
    }


class Classifier:
    """Deletion-request decisions, read from and written to the LLM cache directory."""

    def __init__(self, gateway=None):
        self.gateway = gateway or llm.Gateway(offline=True)
        self.dir = self.gateway.cache_dir / DECISIONS_DIR

    def cached(self, text):
        """The stored decision ``{"deletion_requested", "reason", ...}`` for ``text``, or None."""
        path = self.dir / (text_key(text) + ".json")
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def decide(self, request):
        """True/False from the cache, or None when this request text was never classified."""
        decision = self.cached(request.request_text)
        return None if decision is None else bool(decision["deletion_requested"])

    def fill(self, texts, batch_size=BATCH_SIZE, attempts=3):
        """Classify every text with no cached decision, in batches. Returns the number of new
        decisions. Raises ``llm.CacheMiss`` when offline and ``llm.GatewayError`` when the model
        leaves texts undecided after ``attempts`` passes (each retry is a new, smaller batch)."""
        pending = sorted({t for t in texts if self.cached(t) is None})
        written = 0
        for _ in range(attempts):
            if not pending:
                break
            undecided = []
            for start in range(0, len(pending), batch_size):
                batch = pending[start:start + batch_size]
                result = self.gateway.complete(PURPOSE, build_request(batch))
                by_id = {d.get("id"): d for d in result.get("decisions", [])
                         if isinstance(d.get("deletion_requested"), bool)}
                for i, text in enumerate(batch):
                    decision = by_id.get("r%d" % (i + 1))
                    if decision is None:
                        undecided.append(text)
                        continue
                    self._store(text, decision["deletion_requested"], decision.get("reason", ""))
                    written += 1
            pending = undecided
        if pending:
            raise llm.GatewayError("The model left %d request text(s) undecided after %d attempts."
                                   % (len(pending), attempts))
        return written

    def _store(self, text, deletion_requested, reason):
        self.dir.mkdir(parents=True, exist_ok=True)
        entry = {"deletion_requested": deletion_requested, "reason": reason, "model": MODEL,
                 "request_text": text}
        (self.dir / (text_key(text) + ".json")).write_text(
            json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
