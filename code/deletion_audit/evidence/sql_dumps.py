"""SQLite snapshot dumps (``evidence/databases/*.sql``).

Every row is a PRESENT Observation. Each dump also yields Snapshots: for
inventory dumps the systems listed in ``snapshot_scope``; for replica and
single-system dumps every system that has a table in the dump.
"""

import json
import re
import sqlite3

from .model import PRESENT, EvidenceStore, Observation, Snapshot
from .systems import SQL_TABLE_SYSTEMS

_CAPTURED = re.compile(r"^-- Captured at: (\S+)", re.M)


def load(file_id, path, file_captured_at):
    text = path.read_text(encoding="utf-8")
    match = _CAPTURED.search(text)
    captured_at = match.group(1) if match else file_captured_at

    con = sqlite3.connect(":memory:")
    try:
        con.executescript(text)
        tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        scope = {}
        if "snapshot_scope" in tables:
            scope = dict(con.execute("SELECT origin_system, captured_at FROM snapshot_scope"))
            if scope:
                captured_at = max(scope.values())
        store = EvidenceStore()
        seen = {}  # system_id -> set(resource_id)
        for table in tables:
            if table == "snapshot_scope":
                continue
            cols = [c[1] for c in con.execute('PRAGMA table_info("%s")' % table)]
            fixed_system = SQL_TABLE_SYSTEMS.get(table)
            if fixed_system:
                seen.setdefault(fixed_system, set())
            for row in con.execute('SELECT * FROM "%s"' % table):
                rec = dict(zip(cols, row))
                if "record_json" in rec:
                    fields = json.loads(rec["record_json"])
                    system = rec.get("origin_system")
                else:
                    fields = rec
                    system = fixed_system
                if not system:
                    continue
                seen.setdefault(system, set()).add(rec["resource_id"])
                store.observations.append(Observation(
                    evidence_id=file_id, observed_at=captured_at, file_captured_at=file_captured_at,
                    system_id=system, resource_id=rec["resource_id"], presence=PRESENT,
                    fields=fields, source="sql:" + table))
    finally:
        con.close()

    covered = scope.keys() if scope else seen.keys()
    for system in sorted(covered):
        store.snapshots.append(Snapshot(
            evidence_id=file_id, captured_at=scope.get(system, captured_at),
            file_captured_at=file_captured_at, system_id=system,
            resource_ids=frozenset(seen.get(system, ())), source="sql"))
    return store
