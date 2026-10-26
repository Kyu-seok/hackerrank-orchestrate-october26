"""Score predicted deletion-audit answers against labeled answers.

Usage:
    python3 code/evaluation/main.py PRED_CSV [--gold GOLD_CSV] [--verbose] [--markdown OUT_MD]
                                    [--requests REQUESTS_CSV]

Only cases present in the gold file are scored. Gold defaults to
dataset/sample_output.csv. Metrics:

- status accuracy: predicted deletion_status equals gold.
- step precision/recall/F1: steps compared as a multiset of
  (phase, operation, system_id, resource_id, state, evidence_id), ignoring step_no.
- field accuracy: gold and predicted steps aligned by position; each of the six
  step fields scored separately. Missing predicted steps score zero.
- sequence accuracy: the full ordered steps_json equals gold exactly.
- schema errors: predicted rows that break the output contract.
- cutoff errors (``--requests``, no gold needed): cited Evidence items captured
  after the case's ``audit_at`` (manifest ``captured_at`` for a file_id, the
  activity's ``event_time``, the audit entry's ``event_time``).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
DEFAULT_GOLD = DATASET / "sample_output.csv"

STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
STEP_FIELDS = ("phase", "operation", "system_id", "resource_id", "state", "evidence_id")
STEP_KEYS = set(STEP_FIELDS) | {"step_no"}

# Operation -> (phase, state), in the order the problem statement's table lists them.
OPERATIONS = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}
PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OPERATION_ORDER = {op: i for i, op in enumerate(OPERATIONS)}


def load_answers(path: Path) -> dict[str, tuple[str, str]]:
    """Return {case_id: (deletion_status, raw steps_json)}."""
    with path.open(newline="", encoding="utf-8") as f:
        return {row["case_id"]: (row["deletion_status"], row["steps_json"]) for row in csv.DictReader(f)}


def parse_steps(raw: str) -> list[dict] | None:
    try:
        steps = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        return None
    return steps


def schema_errors(status: str, raw: str) -> list[str]:
    """Check one predicted row against the output contract."""
    errors = []
    if status not in STATUSES:
        errors.append(f"unknown status {status!r}")
    steps = parse_steps(raw)
    if steps is None:
        return errors + ["steps_json is not a JSON array of objects"]
    if status == "NOT_APPLICABLE" and steps:
        errors.append("NOT_APPLICABLE must have []")
    for i, step in enumerate(steps, start=1):
        if set(step) != STEP_KEYS:
            errors.append(f"step {i}: keys {sorted(step)}")
            continue
        if step["step_no"] != i:
            errors.append(f"step {i}: step_no is {step['step_no']}")
        expected = OPERATIONS.get(step["operation"])
        if expected is None:
            errors.append(f"step {i}: unknown operation {step['operation']}")
        elif (step["phase"], step["state"]) != expected:
            errors.append(f"step {i}: {step['operation']} needs phase/state {expected}")
        if status == "COMPLETE" and step["phase"] != "VERIFICATION":
            errors.append(f"step {i}: COMPLETE allows only VERIFICATION steps")
        if status == "COMPLETE" and not step["evidence_id"]:
            errors.append(f"step {i}: COMPLETE steps must cite evidence")
        if status == "INCOMPLETE" and step["phase"] != "FINDING" and step["evidence_id"]:
            errors.append(f"step {i}: INCOMPLETE remediation/verification must have empty evidence_id")
    if status == "INCOMPLETE" and not any(s.get("phase") == "FINDING" for s in steps):
        errors.append("INCOMPLETE has no FINDING step")

    def sort_key(s: dict) -> tuple:
        return (PHASE_ORDER.get(s.get("phase"), 9), OPERATION_ORDER.get(s.get("operation"), 99),
                str(s.get("system_id")), str(s.get("resource_id")))

    if all(set(s) == STEP_KEYS for s in steps) and steps != sorted(steps, key=sort_key):
        errors.append("steps are not in phase/operation/system_id/resource_id order")
    return errors


def _times(path: Path, id_field: str, time_field: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return {row[id_field]: row[time_field] for row in csv.DictReader(f)}


def evidence_times(dataset: Path = DATASET) -> dict[str, str]:
    """Capture time of every citable Evidence item: file_id, activity_id and audit_id."""
    times = _times(dataset / "evidence_files.csv", "file_id", "captured_at")
    times.update(_times(dataset / "system_activity.csv", "activity_id", "event_time"))
    times.update(_times(dataset / "user_audit_log.csv", "audit_id", "event_time"))
    return times


def cutoff_errors(pred: dict, requests: Path, dataset: Path = DATASET) -> dict[str, list[str]]:
    """{case_id: errors} for steps citing an unknown Evidence item or one captured after audit_at."""
    audit_at = _times(requests, "case_id", "audit_at")
    times = evidence_times(dataset)
    errors = {}
    for case_id, (_, raw) in sorted(pred.items()):
        for i, step in enumerate(parse_steps(raw) or [], start=1):
            evidence_id = step.get("evidence_id")
            if not evidence_id or case_id not in audit_at:
                continue
            captured = times.get(evidence_id)
            if captured is None:
                errors.setdefault(case_id, []).append(f"step {i}: unknown evidence {evidence_id}")
            elif captured > audit_at[case_id]:
                errors.setdefault(case_id, []).append(
                    f"step {i}: {evidence_id} captured {captured}, after audit_at {audit_at[case_id]}")
    return errors


def step_tuple(step: dict) -> tuple:
    return tuple(step.get(field) for field in STEP_FIELDS)


def score(gold: dict, pred: dict) -> dict:
    status_hits = 0
    sequence_hits = 0
    matched = gold_total = pred_total = 0
    field_hits = Counter()
    field_total = 0
    confusion = Counter()
    failures = []
    schema = {}

    for case_id in sorted(gold):
        gold_status, gold_raw = gold[case_id]
        gold_steps = parse_steps(gold_raw) or []
        pred_status, pred_raw = pred.get(case_id, ("<missing>", "[]"))
        pred_steps = parse_steps(pred_raw) or []

        if case_id in pred:
            errs = schema_errors(pred_status, pred_raw)
            if errs:
                schema[case_id] = errs

        confusion[(gold_status, pred_status)] += 1
        status_ok = pred_status == gold_status
        status_hits += status_ok

        gold_bag = Counter(step_tuple(s) for s in gold_steps)
        pred_bag = Counter(step_tuple(s) for s in pred_steps)
        matched += sum((gold_bag & pred_bag).values())
        gold_total += len(gold_steps)
        pred_total += len(pred_steps)

        field_total += len(gold_steps)
        for i, g in enumerate(gold_steps):
            p = pred_steps[i] if i < len(pred_steps) else {}
            for field in STEP_FIELDS:
                field_hits[field] += field in p and p[field] == g[field]

        sequence_ok = status_ok and [step_tuple(s) for s in gold_steps] == [step_tuple(s) for s in pred_steps]
        sequence_hits += sequence_ok
        if not sequence_ok:
            failures.append({
                "case_id": case_id,
                "gold_status": gold_status,
                "pred_status": pred_status,
                "missing": sorted((gold_bag - pred_bag).elements()),
                "extra": sorted((pred_bag - gold_bag).elements()),
            })

    n = len(gold)
    precision = matched / pred_total if pred_total else 0.0
    recall = matched / gold_total if gold_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "cases": n,
        "missing_cases": sorted(set(gold) - set(pred)),
        "status_accuracy": status_hits / n if n else 0.0,
        "sequence_accuracy": sequence_hits / n if n else 0.0,
        "step_precision": precision,
        "step_recall": recall,
        "step_f1": f1,
        "steps_matched": matched,
        "steps_gold": gold_total,
        "steps_pred": pred_total,
        "field_accuracy": {f: field_hits[f] / field_total if field_total else 0.0 for f in STEP_FIELDS},
        "field_accuracy_overall": sum(field_hits.values()) / (field_total * len(STEP_FIELDS)) if field_total else 0.0,
        "confusion": confusion,
        "failures": failures,
        "schema_errors": schema,
    }


def render(result: dict, verbose: bool) -> str:
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    lines = [
        f"| Metric | Value |",
        f"| --- | --- |",
        f"| Cases scored | {result['cases']} |",
        f"| Missing predictions | {len(result['missing_cases'])} |",
        f"| Status accuracy | {pct(result['status_accuracy'])} |",
        f"| Sequence accuracy (exact steps_json) | {pct(result['sequence_accuracy'])} |",
        f"| Step precision | {pct(result['step_precision'])} ({result['steps_matched']}/{result['steps_pred']}) |",
        f"| Step recall | {pct(result['step_recall'])} ({result['steps_matched']}/{result['steps_gold']}) |",
        f"| Step F1 | {pct(result['step_f1'])} |",
        f"| Field accuracy (positional, all fields) | {pct(result['field_accuracy_overall'])} |",
    ]
    for field, value in result["field_accuracy"].items():
        lines.append(f"| Field accuracy: `{field}` | {pct(value)} |")
    lines.append(f"| Rows with schema errors | {len(result['schema_errors'])} |")

    lines += ["", "Status confusion (gold -> predicted):", ""]
    for (g, p), count in sorted(result["confusion"].items()):
        lines.append(f"- {g} -> {p}: {count}")

    if verbose:
        if result["schema_errors"]:
            lines += ["", "Schema errors:", ""]
            for case_id, errs in result["schema_errors"].items():
                lines.append(f"- {case_id}: " + "; ".join(errs))
        if result["failures"]:
            lines += ["", "Cases not matching exactly:", ""]
            for f in result["failures"]:
                lines.append(f"- {f['case_id']}: gold {f['gold_status']}, predicted {f['pred_status']}")
                for step in f["missing"]:
                    lines.append(f"  - missing {step}")
                for step in f["extra"]:
                    lines.append(f"  - extra   {step}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pred", type=Path, help="predicted answers CSV (case_id,deletion_status,steps_json)")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="labeled answers CSV")
    parser.add_argument("--verbose", action="store_true", help="list schema errors and per-case step differences")
    parser.add_argument("--markdown", type=Path, help="also write the rendered results to this file")
    parser.add_argument("--requests", type=Path,
                        help="request CSV of the predictions: also check no step cites evidence after audit_at")
    args = parser.parse_args(argv)

    pred = load_answers(args.pred)
    result = score(load_answers(args.gold), pred)
    text = render(result, args.verbose)
    if args.requests:
        late = cutoff_errors(pred, args.requests)
        text += f"\n\nRows citing evidence after audit_at (all {len(pred)} rows): {len(late)}"
        for case_id, errs in late.items():
            text += f"\n- {case_id}: " + "; ".join(errs)
    print(text)
    if args.markdown:
        args.markdown.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
