"""Load every Evidence item in the manifest into one EvidenceStore.

Loaders are registered by file extension. PDF and image evidence comes from the
cached one-time extraction (``documents``); a file with no cached extraction
contributes nothing, and one warning on stderr names the files skipped and the
command that fills the cache.
"""

import dataclasses
import re
import sys

from .. import llm
from ..activities import link_activities
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
    _resolve_aliases(store, dataset)
    return store


_ALIAS = re.compile(r"\b(\S+) \(([^)]+)\)")


def _resolve_aliases(store, dataset):
    """Name the Resource of every record a document shows without a resource_id.

    A link-identity activity gives a Resource an alias in parentheses, e.g.
    "linked tombstone_17 (user_17) to ...". A record of the same system whose
    values include that alias is that Resource (the deleted-account registry
    screenshot shows only ``user_17``). Records left unnamed are dropped.
    """
    aliases = {}  # (system_id, alias) -> resource_id
    for act in link_activities(dataset):
        for resource_id, alias in _ALIAS.findall(act["details"]):
            if resource_id == act["resource_id"]:
                aliases[(act["target_system"], alias.strip().lower())] = resource_id

    def name(obs):
        if obs.resource_id:
            return obs
        names = {aliases[(obs.system_id, t)] for t in obs.tokens if (obs.system_id, t) in aliases}
        return dataclasses.replace(obs, resource_id=names.pop()) if len(names) == 1 else None

    store.rename(name)
