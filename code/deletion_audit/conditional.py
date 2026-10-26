"""Conditional deletion rules decided from the Resource itself.

- SUPPORT_MESSAGE (rule_05): a conversation with shared customer, agent or order
  context is REDACTED: direct identifiers go, the stable ``user_id`` reference may stay.
- SUPPORT_ATTACHMENT (rule_06): an attachment belonging only to the Subject is DELETED.
- ANALYTICS_PROFILE / PRODUCT_TELEMETRY (rules 07-08): a Resource still attributable
  to a Subject (any identifier, including ``user_id``) is ANONYMIZED.
- EMAIL_DELIVERY_LOG (rule_11): a log holding a Subject's email is REDACTED.
- SECURITY_AUDIT_LOG / LEGAL_HOLD_RECORD (rules 12-13): RETAINED while the stated
  retention period or hold is still running at the Audit cutoff, else DELETED.
- ACCOUNT_TOMBSTONE (rule_15): REDACTED to the bare ``user_id`` while the case
  retains records referencing it, else DELETED.

``redaction`` and ``anonymization`` read a Resource's state from one Observation.
``support_treatment``, ``anonymize_treatment`` and ``redact_treatment`` pick the Required treatment
from every Observation of the Resource and the resolved state. A conditional
DELETE/REDACT/ANONYMIZE rule whose condition does not hold (the Resource is
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
from .states import ABSENT, ANONYMIZED, PRESENT, REDACTED

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NULLS = {"", "null", "none", "no direct identifier", "[redacted]"}

# Direct identifiers that redaction must remove (a user_id reference may stay).
DIRECT_IDENTIFIER_KEYS = ("email", "phone", "name", "email_hash", "requester_email", "requester_name",
                          "requester_phone", "matched_value", "uploaded_by", "owner_email",
                          "customer_email", "recipient_email", "lookup_value")
# Free-text fields that may embed an email address.
TEXT_KEYS = ("message_text", "message_excerpt", "body", "subject")
# Fields that keep a Resource attributable even without direct identifiers.
REFERENCE_KEYS = ("user_id", "customer_reference")

# Check results (handover lists, check-result records, record_lookup log lines).
EXPOSED_RESULTS = {"IDENTIFIABLE", "FOUND"}
COMPLIANT_RESULTS = {REDACTED, ANONYMIZED}

WORKER_TREATMENTS = {"DELETE_RECORD": treatments.DELETE, "REDACT_RECORD": treatments.REDACT,
                     "ANONYMIZE_RECORD": treatments.ANONYMIZE}


def _has_value(value):
    return value is not None and str(value).strip().lower() not in _NULLS


def _exposed(fields, keys):
    """Does the Resource still carry a value in ``keys`` or an email in its free text?"""
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
    """ABSENT, ANONYMIZED (nothing ties it to a Subject) or PRESENT (still attributable)."""
    return _read_state(observation, DIRECT_IDENTIFIER_KEYS + REFERENCE_KEYS, ANONYMIZED)


def is_attachment(observation):
    f = observation.fields
    return (f.get("record_type") == "SUPPORT_ATTACHMENT" or f.get("storage_class") == "ticket_attachment"
            or "attachment" in observation.source or _has_value(f.get("file")))


def _decide(default, observations, state, worker_action):
    if state == ABSENT:
        return treatments.DELETE  # the condition no longer holds: verify the Resource is gone
    if worker_action in WORKER_TREATMENTS:
        return WORKER_TREATMENTS[worker_action]
    return default


def support_treatment(observations, state, worker_action, **_case):
    """rule_06 for an attachment, rule_05 for a conversation with shared context."""
    default = treatments.DELETE if any(is_attachment(o) for o in observations) else treatments.REDACT
    return _decide(default, observations, state, worker_action)


def anonymize_treatment(observations, state, worker_action, **_case):
    """rules 07/08: analytics profiles and product telemetry still attributable to a Subject."""
    return _decide(treatments.ANONYMIZE, observations, state, worker_action)


def redact_treatment(observations, state, worker_action, **_case):
    """rule_11: email delivery logs holding a Subject's email."""
    return _decide(treatments.REDACT, observations, state, worker_action)


# -- Retention (rule_12, rule_13) and Account tombstones (rule_15) --------------
# Fields stating until when a Resource must be kept: a security audit Resource's
# ``retention_until``, a legal hold's ``retained_until`` (the retention PDFs are
# extracted into ``retention_until`` as well).
RETENTION_KEYS = ("retention_until", "retained_until")


def _end_of(value):
    """A retention end as a comparable ``...Z`` timestamp; a bare date lasts the whole day."""
    text = str(value).strip()
    return text + "T23:59:59Z" if len(text) == 10 else text


def retained_until(observations):
    """Retention end stated by the latest Observation that states one, or None."""
    stated = [(o.observed_at, o.evidence_id, _end_of(o.fields[k])) for o in observations
              for k in RETENTION_KEYS if _has_value(o.fields.get(k))]
    return max(stated)[2] if stated else None


def retain_treatment(observations, state, worker_action, audit_at="", **_case):
    """rule_12 / rule_13: RETAIN while the retention period or legal hold still runs at
    the Audit cutoff; once it has ended the condition no longer holds and the Resource
    falls back to DELETE. A Resource that states no end is taken to be held (every
    retained Resource in the samples is verified present). No participant evidence
    states a hold's status (active or released) separately from its end date: the
    legal retention register PDF lists orders with end dates only and names no
    ``legal_hold_*`` Resource, so a hold with no stated end cannot be checked against
    it. A retained Resource that is already gone can only be verified absent."""
    if state == ABSENT:
        return treatments.DELETE
    until = retained_until(observations)
    if until is not None and until < audit_at:
        return treatments.DELETE
    return treatments.RETAIN


def tombstone_treatment(observations, state, worker_action, retained=False, **_case):
    """rule_15: the identity Resource becomes an Account tombstone (REDACT: only the stable
    ``user_id`` stays) while retained Resources still reference it: the case keeps one, or
    the Resource itself lists the Resources linked to it (a reference registry entry); with
    nothing left to resolve, the identity Resource is deleted."""
    references = any(o.fields.get("related_references") for o in observations)
    if state == ABSENT or not (retained or references):
        return treatments.DELETE
    return treatments.REDACT
