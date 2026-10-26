"""Service logs and readback logs (``evidence/logs/*.log``).

Every line starts with a 20-character UTC timestamp followed by one of six body
formats (logfmt, JSON, bracket, syslog, pipe, cloud). Identifying keys usually sit
on a ``*_started`` line and the result on the ``*_completed`` line, so lines are
joined on (file, trace_id). Each line that names a ``resource_id`` becomes an
Observation timed by its own timestamp.
"""

import json
import re

from .model import ABSENT, PRESENT, EvidenceStore, Observation
from .systems import ABSENT_RESULTS, log_system

_KV = re.compile(r'(\w+)=("((?:[^"\\]|\\.)*)"|\S+)')
_BRACKET = re.compile(r"\[(\w+)\] \[(\w+)\] \[([\w-]+)\] (\w+): (.*)")
_SYSLOG = re.compile(r"<\d+>1 (\S+) (\S+) (\S+) - - (.*)")
_PIPE = re.compile(r"\| (\w+) \| (\w+) \| ([\w-]+) \| (\w+) \| (.*)")

# Keys on a trace's other lines that identify who the trace is about.
CONTEXT_KEYS = ("lookup_key", "match_key", "subject_key", "subject_ref", "scan_key",
                "owner_key", "correlation_key")
# Transport metadata that never describes the Resource.
NOISE_KEYS = {"ts", "fmt", "instance", "pod", "region", "host", "requestId", "function",
              "logger", "severity", "attempt", "duration_ms", "took_ms", "shard", "level"}


def _kvs(text):
    out = {}
    for m in _KV.finditer(text):
        out[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(2)
    return out


def parse_line(line):
    """Return a dict of the line's fields (with ``ts``), or None for a blank line."""
    line = line.rstrip("\n")
    if not line.strip():
        return None
    rec = {"ts": line[:20]}
    rest = line[21:]
    if rest.startswith("{"):
        rec.update(json.loads(rest))
        return rec
    m = _BRACKET.match(rest)
    if m:
        rec.update(_kvs(m.group(5)))
        rec.update(level=m.group(1), service=m.group(2), trace_id=m.group(3), event=m.group(4))
        return rec
    m = _SYSLOG.match(rest)
    if m:
        rec.update(_kvs(m.group(4)))
        rec.update(host=m.group(1), service=m.group(2), trace_id=m.group(3))
        return rec
    m = _PIPE.match(rest)
    if m:
        rec.update(_kvs(m.group(5)))
        rec.update(level=m.group(1), service=m.group(2), trace_id=m.group(3), event=m.group(4))
        return rec
    if rest.startswith("requestId="):
        outer = _kvs(rest)
        message = outer.pop("message", "").replace('\\"', '"')
        rec.update(outer)
        rec.update(_kvs(message))
        rec.update(trace_id=outer.get("requestId"), service=outer.get("function"))
        return rec
    rec.update(_kvs(rest))
    return rec


def presence_of(rec):
    """PRESENT/ABSENT stated by one log line, or None when it states neither."""
    status = str(rec.get("http_status", ""))
    rows = str(rec.get("rows", ""))
    result = str(rec.get("result", "")).upper()
    if status == "404" or rows == "0" or result in ABSENT_RESULTS:
        return ABSENT
    if status.startswith("5"):
        return None
    return PRESENT


def load(file_id, path, file_captured_at):
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = parse_line(line)
            if rec:
                records.append(rec)

    context = {}
    for rec in records:
        trace = rec.get("trace_id")
        if trace:
            ctx = context.setdefault(trace, {})
            for key in CONTEXT_KEYS:
                if key in rec:
                    ctx.setdefault(key, rec[key])

    store = EvidenceStore()
    for rec in records:
        resource_id = rec.get("resource_id")
        # A *_started line only announces a lookup; its outcome is on a later line.
        if not resource_id or str(rec.get("event", "")).endswith("_started"):
            continue
        presence = presence_of(rec)
        if presence is None:
            continue
        fields = {k: v for k, v in rec.items() if k not in NOISE_KEYS}
        for key, value in context.get(rec.get("trace_id"), {}).items():
            fields.setdefault(key, value)
        store.observations.append(Observation(
            evidence_id=file_id, observed_at=rec["ts"], file_captured_at=file_captured_at,
            system_id=log_system(rec), resource_id=resource_id, presence=presence,
            fields=fields, result=str(rec.get("result", "")).upper(), source="log:" + str(rec.get("event", ""))))
    return store
