"""JSON evidence under ``evidence/records``.

Shapes (dispatched by top-level keys):

- snapshot bundles ``{exported_at, snapshots:[{captured_at, data_store, collection, records}]}``:
  each snapshot is judged by its own ``captured_at`` and declares coverage of its data store;
  ``operational_record_history`` snapshots hold check results instead.
- service exports ``{exported_at, service_exports:{system:{kind:[entry]}}}``: per-entry ``observed_at``.
- check-result lists ``{exported_at, records:[{recorded_at, system, resource_id, result, ...}]}``.
- single collections ``{captured_at, collection, records}``.
"""

import json

from .model import ABSENT, PRESENT, EvidenceStore, Observation, Snapshot
from .systems import ABSENT_RESULTS, COLLECTION_SYSTEMS

CHECK_RESULT_COLLECTION = "operational_record_history"


def load(file_id, path, file_captured_at):
    doc = json.loads(path.read_text(encoding="utf-8"))
    store = EvidenceStore()

    def observe(observed_at, system, resource_id, presence, fields, result="", source=""):
        store.observations.append(Observation(
            evidence_id=file_id, observed_at=observed_at or file_captured_at,
            file_captured_at=file_captured_at, system_id=system, resource_id=resource_id,
            presence=presence, fields=fields, result=result, source=source))

    def observe_check(rec, default_time, source):
        result = (rec.get("result") or "").upper()
        observe(rec.get("recorded_at") or default_time, rec.get("system", ""), rec["resource_id"],
                ABSENT if result in ABSENT_RESULTS else PRESENT, rec, result, source)

    if "snapshots" in doc:
        for snap in doc["snapshots"]:
            source = "bundle:%s/%s" % (snap.get("data_store"), snap.get("collection"))
            if snap.get("collection") == CHECK_RESULT_COLLECTION:
                for rec in snap["records"]:
                    observe_check(rec, snap["captured_at"], source)
                continue
            system = snap["data_store"]
            for rec in snap["records"]:
                observe(snap["captured_at"], system, rec["resource_id"], PRESENT, rec, source=source)
            store.snapshots.append(Snapshot(
                evidence_id=file_id, captured_at=snap["captured_at"], file_captured_at=file_captured_at,
                system_id=system, resource_ids=frozenset(r["resource_id"] for r in snap["records"]),
                source=source))
    elif "service_exports" in doc:
        for system, kinds in doc["service_exports"].items():
            for kind, entries in kinds.items():
                for entry in entries:
                    absent = entry.get("status_code") == 404
                    observe(entry.get("observed_at"), system, entry["resource_id"],
                            ABSENT if absent else PRESENT, entry, source="export:%s/%s" % (system, kind))
    elif "records" in doc:
        default_time = doc.get("captured_at") or doc.get("exported_at")
        system = COLLECTION_SYSTEMS.get(doc.get("collection", ""))
        for rec in doc["records"]:
            if "system" in rec and "result" in rec:
                observe_check(rec, default_time, "checks")
            elif system:
                observe(default_time, system, rec["resource_id"], PRESENT, rec,
                        source="collection:" + doc["collection"])
    return store
