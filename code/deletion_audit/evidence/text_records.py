"""Plain-text check lists, e.g. the shift handover
``- <ts> | <system> | <resource_id> | <record_type> | <result> | <subject_reference>``."""

import re

from .model import ABSENT, PRESENT, EvidenceStore, Observation
from .systems import ABSENT_RESULTS

_LINE = re.compile(r"^- (\S+) \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| (.*)$")


def load(file_id, path, file_captured_at):
    store = EvidenceStore()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        ts, system, resource_id, record_type, result, subject = m.groups()
        fields = {"system": system, "resource_id": resource_id, "record_type": record_type,
                  "result": result, "subject_reference": subject.strip()}
        store.observations.append(Observation(
            evidence_id=file_id, observed_at=ts, file_captured_at=file_captured_at,
            system_id=system, resource_id=resource_id,
            presence=ABSENT if result.upper() in ABSENT_RESULTS else PRESENT,
            fields=fields, result=result.upper(), source="text"))
    return store
