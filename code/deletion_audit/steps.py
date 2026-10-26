"""Turn per-Resource assessments into the case status and ordered ``steps_json``.

Status is INCOMPLETE when there is at least one finding, COMPLETE otherwise
(``reported_status`` is a Claim and is ignored). INCOMPLETE cases list findings
(citing evidence), then remediation and verification of every in-scope Resource
with empty evidence. COMPLETE cases list only verifications, each citing the
Evidence item that proves the current state; a verification with no citable
Evidence item (its proof was exported after the Audit cutoff) is left out, since
a COMPLETE case includes only evidence-backed verification steps (AGENTS.md 6.3).
"""

import json
from collections import namedtuple

from .treatments import OPERATION_ORDER, PHASE_ORDER, PHASE_STATE

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
NOT_APPLICABLE = "NOT_APPLICABLE"

# One in-scope Resource: what policy requires, whether it complies, and the citation.
Assessment = namedtuple("Assessment", "system_id resource_id treatment compliant evidence_id")


def _step(operation, system_id, resource_id, evidence_id):
    phase, state = PHASE_STATE[operation]
    return {"phase": phase, "operation": operation, "state": state, "system_id": system_id,
            "resource_id": resource_id, "evidence_id": evidence_id}


def build(assessments):
    """Return (status, steps) for a deletion case."""
    findings = [a for a in assessments if not a.compliant]
    status = INCOMPLETE if findings else COMPLETE
    steps = []
    for a in findings:
        steps.append(_step(a.treatment.finding, a.system_id, a.resource_id, a.evidence_id))
        steps.append(_step(a.treatment.remediation, a.system_id, a.resource_id, ""))
    for a in assessments:
        if status == COMPLETE and not a.evidence_id:
            continue
        evidence = "" if status == INCOMPLETE else a.evidence_id
        steps.append(_step(a.treatment.verification, a.system_id, a.resource_id, evidence))
    return status, order(steps)


def order(steps):
    """Contract order (phase, operation table order, system_id, resource_id), numbered from 1."""
    steps = sorted(steps, key=lambda s: (PHASE_ORDER[s["phase"]], OPERATION_ORDER[s["operation"]],
                                         s["system_id"], s["resource_id"]))
    return [dict(s, step_no=i) for i, s in enumerate(steps, start=1)]


def serialize(steps):
    return json.dumps(steps, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
