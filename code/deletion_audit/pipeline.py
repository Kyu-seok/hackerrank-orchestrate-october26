"""Audit a request file and write the answer CSV."""

import csv
import sys

from . import classification, steps, treatments
from .activities import WorkerActions
from .attribution import Attributor
from .citation import resolve
from .dataset import Dataset, load_requests
from .evidence import load_evidence

KNOWN_REQUEST_FILES = ("sample_deletion_requests.csv", "deletion_requests.csv")


class Auditor:
    """Audits requests against the whole dataset.

    Workflow attribution is resolved jointly over every request the dataset
    knows (samples and evaluation set) plus the requests being audited, so a
    case's answer does not depend on which request file it was run from.
    """

    def __init__(self, requests, dataset=None):
        self.dataset = dataset or Dataset()
        self.store = load_evidence(self.dataset)
        known = {r.case_id: r for name in KNOWN_REQUEST_FILES
                 for r in load_requests(self.dataset.path(name))}
        known.update({r.case_id: r for r in requests})
        self.attributor = Attributor(self.dataset, self.store, list(known.values()))
        self.worker_actions = WorkerActions(self.dataset)
        self.classifier = classification.Classifier()
        self.unclassified = []

    def audit(self, request):
        """Return (deletion_status, steps) for one request."""
        deletion_requested = self.classifier.decide(request)
        if deletion_requested is None:
            # No cached decision: audit it as a deletion request, and say so (see run()).
            self.unclassified.append(request.case_id)
        elif not deletion_requested:
            return steps.NOT_APPLICABLE, []
        assessments = []
        # Rules that depend on what the case retains (the Account tombstone) are decided last.
        in_scope = sorted(self.attributor.resources(request), key=lambda cr: cr[0].after_retained)
        for category, resource_id in in_scope:
            retained = any(a.treatment is treatments.RETAIN for a in assessments)
            resolution, evidence_id = resolve(category, resource_id, self.store, request.audit_at)
            action = self.worker_actions.latest(category.system_id, resource_id, request.audit_at)
            treatment = category.required(
                self.store.observed_by(category.system_id, resource_id, request.audit_at),
                resolution.state, action["event_type"] if action else None,
                audit_at=request.audit_at, retained=retained)
            compliant = resolution.state == treatment.target
            if not evidence_id and not compliant and action and action["reported_result"] != "SUCCESS":
                # Only a file exported after the cutoff shows the remaining record. A finding must
                # cite a participant-visible item from before the cutoff: the deletion worker's
                # unsuccessful attempt on it. (A COMPLETE case drops an uncited verification.)
                evidence_id = action["activity_id"]
            assessments.append(steps.Assessment(
                system_id=category.system_id, resource_id=resource_id, treatment=treatment,
                compliant=compliant, evidence_id=evidence_id))
        return steps.build(assessments)


class ClassificationMissing(RuntimeError):
    """``strict`` run and some request texts have no cached deletion-request decision."""


FILL_COMMAND = "python3 code/classify_requests.py"


def run(requests_path, output_path, strict=False):
    """Audit every request and write the answer CSV.

    A request whose text has no cached deletion-request decision is audited as a
    deletion request and named in one stderr warning. With ``strict`` the run
    instead raises ``ClassificationMissing`` before writing anything.
    """
    requests = sorted(load_requests(requests_path), key=lambda r: r.case_id)
    auditor = Auditor(requests)
    if strict:
        missing = [r.case_id for r in requests if auditor.classifier.decide(r) is None]
        if missing:
            raise ClassificationMissing(
                "%d request(s) have no cached deletion-request classification (%s). Fill the cache "
                "once with: %s (ANTHROPIC_API_KEY set)" % (len(missing), _summary(missing), FILL_COMMAND))
    rows = []
    for request in requests:
        status, case_steps = auditor.audit(request)
        rows.append((request.case_id, status, steps.serialize(case_steps)))
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        writer.writerows(rows)
    if auditor.unclassified:
        print("warning: %d request(s) have no cached deletion-request classification and were audited "
              "as deletion requests (%s). Fill the cache once with: %s (ANTHROPIC_API_KEY set); "
              "pass --strict to fail instead." % (len(auditor.unclassified), _summary(auditor.unclassified),
                                                  FILL_COMMAND), file=sys.stderr)
    return rows


def _summary(case_ids, limit=10):
    shown = ", ".join(case_ids[:limit])
    return shown + (", ... (+%d more)" % (len(case_ids) - limit) if len(case_ids) > limit else "")
