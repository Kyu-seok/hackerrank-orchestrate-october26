"""Resolve a Resource's state at the Audit cutoff together with the Evidence item that proves it.

State comes from every record by its own capture time, including an inner
snapshot of a bundle exported after the cutoff (the labeled samples verify
retained records known only from such a bundle, e.g. case_09's
``audit_record_4902``).

Citation is stricter (AGENTS.md section 6.6: never cite an Evidence item
captured after ``audit_at``). A file is citable only when its manifest
``captured_at`` is at or before the Audit cutoff. Among citable files that show
the Resource, the latest file agreeing with the resolved state wins (else the
latest citable one); ties go to the lowest id. An absence cites the latest
citable covering Snapshot that lacks the row. When no citable file exists the
citation is empty and the caller decides (see ``pipeline.Auditor.audit``).
"""

from .states import ABSENT
from .state import latest_by, reconstruct


def _omission_proof(category, resource_id, store, audit_at):
    snapshots = [s for s in store.covering(category.system_id)
                 if s.captured_at <= audit_at and resource_id not in s.resource_ids]
    return latest_by(snapshots, "file_captured_at")


def _proof(category, resource_id, resolution, citable, audit_at):
    """Latest citable Evidence item showing ``resolution``'s state, or None."""
    best = None
    if resolution.basis == "observation":
        observations = citable.observed_by(category.system_id, resource_id, audit_at)
        agreeing = [o for o in observations if category.assess(o) == resolution.state]
        best = latest_by(agreeing or observations, "file_captured_at")
    if best is None and resolution.state == ABSENT:
        # The deciding Observation sits in a file exported after the cutoff (or the
        # state came from omission): cite a citable covering Snapshot that lacks the row.
        best = _omission_proof(category, resource_id, citable, audit_at)
    return best


def resolve(category, resource_id, store, audit_at):
    """(Resolution, citable evidence id proving it, or "" when no citable file exists)."""
    resolution = reconstruct(category, resource_id, store, audit_at)
    best = _proof(category, resource_id, resolution, store.exported_by(audit_at), audit_at)
    return resolution, best.evidence_id if best else ""
