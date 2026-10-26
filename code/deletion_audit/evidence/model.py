"""Normalized evidence: Observations of Resources and the Snapshots that cover systems."""

import re
from dataclasses import dataclass, field

from ..states import ABSENT, PRESENT  # noqa: F401  (re-exported for the loaders)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_USER_ID = re.compile(r"\buser_\d+\b")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def _leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _leaves(v)
    elif value is not None:
        yield str(value)


def identifier_tokens(fields):
    """Every exact-match token in a record: whole lowercased values plus any
    email, ``user_N`` or sha256 embedded in free text. Exact tokens (never
    substrings) keep ``x.jr@`` and ``user_12`` decoys apart from ``x@``/``user_1``."""
    tokens = set()
    for leaf in _leaves(fields):
        text = leaf.strip().lower()
        if not text or text == "null":
            continue
        tokens.add(text)
        tokens.update(_EMAIL.findall(text))
        tokens.update(_USER_ID.findall(text))
        tokens.update(_SHA256.findall(text))
    return frozenset(tokens)


@dataclass(frozen=True)
class Observation:
    """A Resource's state as seen in one Evidence item at a known time.

    ``observed_at`` is the record's own capture time (a bundle snapshot's
    ``captured_at``, a log line's timestamp, an export entry's ``observed_at``);
    ``file_captured_at`` is the manifest capture time of the whole Evidence item.
    ``presence`` is PRESENT or ABSENT; ``result`` keeps a check result such as
    IDENTIFIABLE or DISABLED when the source states one.
    """

    evidence_id: str
    observed_at: str
    file_captured_at: str
    system_id: str
    resource_id: str
    presence: str
    fields: dict = field(default_factory=dict, compare=False, hash=False)
    result: str = ""
    source: str = ""

    @property
    def tokens(self):
        cached = self.__dict__.get("_tokens")
        if cached is None:
            cached = identifier_tokens(self.fields)
            object.__setattr__(self, "_tokens", cached)
        return cached


@dataclass(frozen=True)
class Snapshot:
    """A capture that declares full coverage of one system: any Resource of
    ``system_id`` missing from ``resource_ids`` was absent at ``captured_at``."""

    evidence_id: str
    captured_at: str
    file_captured_at: str
    system_id: str
    resource_ids: frozenset
    source: str = ""


@dataclass
class EvidenceStore:
    observations: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)

    def __post_init__(self):
        self._by_resource = None
        self._exported_by = {}

    def _changed(self):
        self._by_resource = None
        self._exported_by = {}

    def extend(self, other):
        self.observations.extend(other.observations)
        self.snapshots.extend(other.snapshots)
        self._changed()

    def rename(self, name_of):
        """Rename or drop Observations: ``name_of(obs)`` returns the Observation to keep
        (possibly with a new ``resource_id``) or None to drop it."""
        self.observations[:] = [kept for kept in map(name_of, self.observations) if kept is not None]
        self._changed()

    def for_resource(self, system_id, resource_id):
        if self._by_resource is None:
            index = {}
            for obs in self.observations:
                index.setdefault((obs.system_id, obs.resource_id), []).append(obs)
            self._by_resource = index
        return self._by_resource.get((system_id, resource_id), [])

    def observed_by(self, system_id, resource_id, audit_at):
        """Observations of the Resource recorded at or before the Audit cutoff (each by its own time)."""
        return [o for o in self.for_resource(system_id, resource_id) if o.observed_at <= audit_at]

    def covering(self, system_id):
        return [s for s in self.snapshots if s.system_id == system_id]

    def exported_by(self, audit_at):
        """The store as it existed at the Audit cutoff: only Evidence items whose manifest
        ``captured_at`` is at or before ``audit_at`` (the citable ones)."""
        view = self._exported_by.get(audit_at)
        if view is None:
            view = EvidenceStore([o for o in self.observations if o.file_captured_at <= audit_at],
                                 [s for s in self.snapshots if s.file_captured_at <= audit_at])
            self._exported_by[audit_at] = view
        return view
