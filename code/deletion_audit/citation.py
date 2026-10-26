"""Choose the Evidence item a finding or a COMPLETE verification cites.

A file is citable only when its manifest ``captured_at`` is at or before the
Audit cutoff (a bundle exported after the cutoff is never cited, even for an
inner snapshot taken before it). Among citable files that show the Resource in
its resolved state, the latest file wins; ties go to the lowest id. An omission
cites the latest citable covering Snapshot. Only when no file qualifies is the
deciding record cited by its own capture time.
"""

from .evidence import ABSENT
from .state import latest_by


def _citable(items, audit_at):
    return [i for i in items if i.file_captured_at <= audit_at]


def _omission_proof(category, resource_id, store, audit_at):
    snapshots = [s for s in _citable(store.covering(category.system_id), audit_at)
                 if s.captured_at <= audit_at and resource_id not in s.resource_ids]
    return latest_by(snapshots, "file_captured_at")


def cite(category, resource_id, resolution, store, audit_at):
    """Evidence id proving ``resolution``, or "" when nothing citable exists."""
    best = None
    if resolution.basis == "observation":
        observations = _citable(
            [o for o in store.for_resource(category.system_id, resource_id) if o.observed_at <= audit_at],
            audit_at)
        agreeing = [o for o in observations if category.assess(o) == resolution.state]
        best = latest_by(agreeing or observations, "file_captured_at")
    if best is None and resolution.state == ABSENT:
        # The deciding Observation sits in a file exported after the cutoff (or the
        # state came from omission): cite a covering Snapshot that lacks the row.
        best = _omission_proof(category, resource_id, store, audit_at)
    if best is None:
        # Last resort: the record that decided the state. Its own capture time is
        # within the cutoff even though its file was exported later (a bundle
        # snapshot taken at audit_at), so it is the only proof that exists.
        best = resolution.proof
    return best.evidence_id if best else ""
