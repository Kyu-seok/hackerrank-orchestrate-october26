"""``system_activity.csv`` split by what each activity can prove.

- Action activities (the deletion worker's delete/redact/anonymize/disable/block/
  retain attempts) are Claims: their ``reported_result`` is never proof of state.
- Check activities inspect a Resource and yield Observations (data flows, restores).
- Link-identity activities tie a Resource to a Subject.
"""

ACTION_TYPES = frozenset({"DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD",
                          "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "RETAIN_RECORD"})
CHECK_TYPES = frozenset({"CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS"})
LINK_TYPES = frozenset({"LINK_RESOURCE_IDENTITY"})

ACTION_SOURCE = "deletion_worker"


def action_activities(dataset):
    """Deletion-worker Action activities, sorted by time then id (the CSV is not time-sorted)."""
    acts = [a for a in dataset.activities
            if a["event_type"] in ACTION_TYPES and a["source_system"] == ACTION_SOURCE]
    return sorted(acts, key=lambda a: (a["event_time"], a["activity_id"]))


class WorkerActions:
    """Latest deletion-worker Action type per Resource, as of a cutoff."""

    def __init__(self, dataset):
        self._by_resource = {}
        for act in action_activities(dataset):
            self._by_resource.setdefault((act["target_system"], act["resource_id"]), []).append(act)

    def latest_type(self, system_id, resource_id, audit_at):
        acts = [a for a in self._by_resource.get((system_id, resource_id), ()) if a["event_time"] <= audit_at]
        return acts[-1]["event_type"] if acts else None
