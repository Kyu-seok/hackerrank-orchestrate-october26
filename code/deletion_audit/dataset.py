"""Participant dataset access: paths and the CSV tables under ``dataset/``."""

import csv
from collections import namedtuple
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
DEFAULT_REQUESTS = DATASET_DIR / "deletion_requests.csv"
DEFAULT_OUTPUT = REPO_ROOT / "output.csv"

Request = namedtuple(
    "Request", "case_id email requested_at reported_status reported_at audit_at request_text")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_requests(path):
    return [Request(**{k: row[k] for k in Request._fields}) for row in read_csv(path)]


class Dataset:
    """Lazily loaded participant tables. Timestamps stay ISO-8601 ``...Z`` strings,
    which compare correctly as strings."""

    def __init__(self, root=DATASET_DIR):
        self.root = Path(root)
        self._cache = {}

    def _table(self, name):
        if name not in self._cache:
            self._cache[name] = read_csv(self.root / name)
        return self._cache[name]

    @property
    def identities(self):
        return self._table("user_identities.csv")

    @property
    def audit_log(self):
        return self._table("user_audit_log.csv")

    @property
    def activities(self):
        return self._table("system_activity.csv")

    @property
    def rules(self):
        return self._table("deletion_rules.csv")

    @property
    def manifest(self):
        """{file_id: manifest row} for every Evidence file."""
        if "manifest" not in self._cache:
            self._cache["manifest"] = {r["file_id"]: r for r in self._table("evidence_files.csv")}
        return self._cache["manifest"]

    def path(self, relative):
        return self.root / relative
