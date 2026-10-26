"""Load every Evidence item in the manifest into one EvidenceStore.

Loaders are registered by file extension. PDF and image evidence comes from the
cached one-time extraction (``documents``); a file with no cached extraction
contributes nothing, and one warning on stderr names the files skipped and the
command that fills the cache.
"""

import sys

from .. import llm
from . import documents, json_records, logs, sql_dumps, text_records
from .model import ABSENT, PRESENT, EvidenceStore, Observation, Snapshot  # noqa: F401

LOADERS = {
    ".sql": sql_dumps.load,
    ".json": json_records.load,
    ".log": logs.load,
    ".txt": text_records.load,
}
LOADERS.update({suffix: documents.load for suffix in documents.MEDIA_TYPES})


def load_evidence(dataset):
    store = EvidenceStore()
    not_extracted = []
    for file_id in sorted(dataset.manifest):
        row = dataset.manifest[file_id]
        path = dataset.path(row["file_path"])
        loader = LOADERS.get(path.suffix.lower())
        if loader is None:
            continue
        try:
            store.extend(loader(file_id, path, row["captured_at"]))
        except llm.CacheMiss:
            not_extracted.append(file_id)
    if not_extracted:
        print("warning: %d PDF/image evidence file(s) have no cached extraction and were skipped (%s). "
              "Fill the cache once with: python3 code/extract_evidence.py (ANTHROPIC_API_KEY set)"
              % (len(not_extracted), ", ".join(not_extracted)), file=sys.stderr)
    return store
