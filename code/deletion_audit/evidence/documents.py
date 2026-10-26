"""PDF and image evidence, read once by a vision model and cached (ADR 0001).

``extract(gateway, path)`` sends one file and the prompt in
``prompts/evidence_extraction.md`` to Claude Sonnet 5.5 through the LLM gateway
and returns snapshot-shaped records. The one-time command
``code/extract_evidence.py`` runs it for every PDF and image in the manifest.

``load`` is the evidence loader for ``.pdf``/``.png`` files on normal runs: it
asks a cache-only gateway for the same request, so no model is called, and
turns each record into a PRESENT/ABSENT Observation captured at the file's
manifest time. A file without a cached extraction raises ``llm.CacheMiss``.
"""

import base64
from pathlib import Path

from .. import llm
from .model import ABSENT, PRESENT, EvidenceStore, Observation

PURPOSE = "evidence_extraction"
MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evidence_extraction.md"
MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}

SYSTEM_IDS = [
    "account_service", "search_service", "analytics_platform", "support_platform", "export_service",
    "integration_service", "backup_service", "security_service", "legal_service", "identity_service",
    "object_storage", "marketing_platform", "cache_service", "email_delivery_service", "archive_service",
]
_TEXT_OR_NULL = {"anyOf": [{"type": "string"}, {"type": "null"}]}
IDENTIFIER_FIELDS = ("name", "email", "phone", "email_hash", "user_id", "order_id", "ticket_id",
                     "file_name", "status", "retention_until", "notes")
RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["system_id", "resource_id", "record_type", "state", "related_references"]
                + list(IDENTIFIER_FIELDS),
    "properties": dict(
        {"system_id": {"type": "string", "enum": SYSTEM_IDS},
         "resource_id": {"type": "string"},
         "record_type": {"type": "string"},
         "state": {"type": "string", "enum": [PRESENT, ABSENT]},
         "related_references": {"type": "array", "items": {"type": "string"}}},
        **{name: _TEXT_OR_NULL for name in IDENTIFIER_FIELDS}),
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["document_kind", "records"],
    "properties": {"document_kind": {"type": "string"},
                   "records": {"type": "array", "items": RECORD_SCHEMA}},
}


def is_document(path):
    return Path(path).suffix.lower() in MEDIA_TYPES


def build_request(path):
    """The Messages API request for one evidence file. Its content hash is the cache key,
    so the file bytes, the prompt and the schema all decide whether a cached answer applies."""
    path = Path(path)
    media_type = MEDIA_TYPES[path.suffix.lower()]
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    block_type = "document" if media_type == "application/pdf" else "image"
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": PROMPT_PATH.read_text(encoding="utf-8"),
        "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        "messages": [{"role": "user", "content": [
            {"type": block_type, "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": "Evidence file: %s\nTranscribe every record it shows." % path.name},
        ]}],
    }


def extract(gateway, path):
    """Snapshot-shaped records for one PDF/image: ``{"document_kind", "records": [...]}``."""
    return gateway.complete(PURPOSE, build_request(path))


def load(file_id, path, file_captured_at, gateway=None):
    gateway = gateway or llm.Gateway(offline=True)
    extraction = extract(gateway, path)
    store = EvidenceStore()
    for rec in extraction.get("records", []):
        if not rec.get("system_id"):
            continue
        # A record the document shows without its resource_id keeps resource_id "": the
        # store resolves it through a link-identity alias or drops it (see evidence.load_evidence).
        fields = {k: v for k, v in rec.items() if v not in (None, "", [])}
        store.observations.append(Observation(
            evidence_id=file_id, observed_at=file_captured_at, file_captured_at=file_captured_at,
            system_id=rec["system_id"], resource_id=rec.get("resource_id") or "",
            presence=ABSENT if rec.get("state") == ABSENT else PRESENT,
            fields=fields, source="extraction:%s" % rec.get("record_type", "")))
    return store
