"""Reconstruct a Resource's state at the Audit cutoff.

Only evidence observed at or before ``audit_at`` counts (each record by its own
capture time). Direct Observations of the Resource decide; the latest one wins.
Absence by omission (a covering Snapshot that lacks the row) is used only when no
direct Observation exists, because snapshots are not reliably exhaustive. With
neither, the state is unknown and treated as PRESENT.
"""

from collections import namedtuple

from .evidence import ABSENT, PRESENT

# basis: "observation" | "omission" | "unknown"; proof: the Observation or Snapshot used.
Resolution = namedtuple("Resolution", "state basis proof")


def latest_by(items, time_attr):
    # Latest by time; on a tie the lowest evidence id wins.
    best = None
    for item in items:
        if best is None:
            best = item
            continue
        t, bt = getattr(item, time_attr), getattr(best, time_attr)
        if t > bt or (t == bt and item.evidence_id < best.evidence_id):
            best = item
    return best


def reconstruct(category, resource_id, store, audit_at):
    observations = [o for o in store.for_resource(category.system_id, resource_id)
                    if o.observed_at <= audit_at]
    if observations:
        latest_time = max(o.observed_at for o in observations)
        at_latest = [o for o in observations if o.observed_at == latest_time]
        # Conflicting reads at the same instant: any presence wins (unknown counts as present).
        present = [o for o in at_latest if o.presence == PRESENT]
        chosen = min(present or at_latest, key=lambda o: o.evidence_id)
        return Resolution(category.assess(chosen), "observation", chosen)

    omissions = [s for s in store.covering(category.system_id)
                 if s.captured_at <= audit_at and resource_id not in s.resource_ids]
    if omissions:
        return Resolution(ABSENT, "omission", latest_by(omissions, "captured_at"))
    return Resolution(PRESENT, "unknown", None)
