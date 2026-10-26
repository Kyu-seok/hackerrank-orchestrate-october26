"""Conditional deletion rules decided from the record itself.

- SUPPORT_MESSAGE (rule_05): a conversation with shared customer, agent or order
  context is REDACTED: direct identifiers go, the stable ``user_id`` reference may stay.
- SUPPORT_ATTACHMENT (rule_06): an attachment belonging only to the Subject is DELETED.
- ANALYTICS_PROFILE / PRODUCT_TELEMETRY (rules 07-08): a record still attributable
  to a user (any identifier, including ``user_id``) is ANONYMIZED.
- EMAIL_DELIVERY_LOG (rule_11): a log holding a user email is REDACTED.

``redaction`` and ``anonymization`` read a Resource's state from one Observation.
``support_treatment``, ``anonymize_treatment`` and ``redact_treatment`` pick the Required treatment
from every Observation of the Resource and the resolved state. A conditional
DELETE/REDACT/ANONYMIZE rule whose condition does not hold (the record is
already gone, already redacted or no longer attributable) leaves only a
verification of the current state.

Sample-derived signal: in every labeled sample the deletion worker's Action
activity type on the Resource names the treatment the answer expects (e.g. the
legacy support replica contact ``support_002`` and ``analytics_9914`` are
deleted, not redacted/anonymized). The activity's *result* is a Claim and never
proof of state, but its *type* is used as the treatment when present.
"""

import re

from . import treatments
from .evidence import ABSENT, PRESENT

REDACTED = "REDACTED"
ANONYMIZED = "ANONYMIZED"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NULLS = {"", "null", "none", "no direct identifier", "[redacted]"}

# Direct identifiers that redaction must remove (a user_id reference may stay).
DIRECT_IDENTIFIER_KEYS = ("email", "phone", "name", "email_hash", "requester_email", "requester_name",
                          "requester_phone", "matched_value", "uploaded_by", "owner_email",
                          "customer_email", "recipient_email", "lookup_value")
# Free-text fields that may embed an email address.
TEXT_KEYS = ("message_text", "message_excerpt", "body", "subject")
# Fields that keep a record attributable even without direct identifiers.
REFERENCE_KEYS = ("user_id", "customer_reference")

# Check results (handover lists, check-result records, record_lookup log lines).
EXPOSED_RESULTS = {"IDENTIFIABLE", "FOUND"}
COMPLIANT_RESULTS = {"REDACTED", "ANONYMIZED"}

WORKER_TREATMENTS = {"DELETE_RECORD": treatments.DELETE, "REDACT_RECORD": treatments.REDACT,
                     "ANONYMIZE_RECORD": treatments.ANONYMIZE}


def _has_value(value):
    return value is not None and str(value).strip().lower() not in _NULLS


def _exposed(fields, keys):
    """Does the record still carry a value in ``keys`` or an email in its free text?"""
    if any(_has_value(fields.get(k)) for k in keys):
        return True
    if str(fields.get("direct_identifiers", "")) == "1":
        return True
    return any(_EMAIL.search(str(fields.get(k) or "")) for k in TEXT_KEYS)


def _read_state(observation, keys, compliant):
    if observation.presence == ABSENT:
        return ABSENT
    if observation.result in EXPOSED_RESULTS:
        return PRESENT
    if observation.result in COMPLIANT_RESULTS:
        return compliant
    if str(observation.fields.get("rows", "")) not in ("", "0") or observation.fields.get("marker_found") == "false":
        return PRESENT  # a lookup returned the live row (or its deletion marker is missing)
    return PRESENT if _exposed(observation.fields, keys) else compliant


def redaction(observation):
    """ABSENT, REDACTED (no direct identifiers left) or PRESENT (identifiers exposed)."""
    return _read_state(observation, DIRECT_IDENTIFIER_KEYS, REDACTED)


def anonymization(observation):
    """ABSENT, ANONYMIZED (nothing ties it to a user) or PRESENT (still attributable)."""
    return _read_state(observation, DIRECT_IDENTIFIER_KEYS + REFERENCE_KEYS, ANONYMIZED)


def is_attachment(observation):
    f = observation.fields
    return (f.get("record_type") == "SUPPORT_ATTACHMENT" or f.get("storage_class") == "ticket_attachment"
            or "attachment" in observation.source or _has_value(f.get("file")))


def _decide(default, observations, state, worker_action):
    if state == ABSENT:
        return treatments.DELETE  # the condition no longer holds: verify the record is gone
    if worker_action in WORKER_TREATMENTS:
        return WORKER_TREATMENTS[worker_action]
    return default


def support_treatment(observations, state, worker_action):
    """rule_06 for an attachment, rule_05 for a conversation with shared context."""
    default = treatments.DELETE if any(is_attachment(o) for o in observations) else treatments.REDACT
    return _decide(default, observations, state, worker_action)


def anonymize_treatment(observations, state, worker_action):
    """rules 07/08: analytics profiles and product telemetry still attributable to a user."""
    return _decide(treatments.ANONYMIZE, observations, state, worker_action)


def redact_treatment(observations, state, worker_action):
    """rule_11: email delivery logs holding a user email."""
    return _decide(treatments.REDACT, observations, state, worker_action)
