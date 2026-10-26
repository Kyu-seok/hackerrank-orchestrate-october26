"""Load every Evidence item in the manifest into one EvidenceStore.

Loaders are registered by file extension. PDF and image evidence is handled by
the cached extraction ticket; until then those files contribute nothing.
"""

from . import json_records, logs, sql_dumps, text_records
from .model import ABSENT, PRESENT, EvidenceStore, Observation, Snapshot  # noqa: F401

LOADERS = {
    ".sql": sql_dumps.load,
    ".json": json_records.load,
    ".log": logs.load,
    ".txt": text_records.load,
}


def load_evidence(dataset):
    store = EvidenceStore()
    for file_id in sorted(dataset.manifest):
        row = dataset.manifest[file_id]
        path = dataset.path(row["file_path"])
        loader = LOADERS.get(path.suffix.lower())
        if loader is None:
            continue
        store.extend(loader(file_id, path, row["captured_at"]))
    return store
