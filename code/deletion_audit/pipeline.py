"""Audit a request file and write the answer CSV."""

import csv

from . import classification, state, steps
from .activities import WorkerActions
from .attribution import Attributor
from .citation import cite
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

    def audit(self, request):
        """Return (deletion_status, steps) for one request."""
        if not classification.is_deletion_request(request):
            return steps.NOT_APPLICABLE, []
        assessments = []
        for category, resource_id in self.attributor.resources(request):
            resolution = state.reconstruct(category, resource_id, self.store, request.audit_at)
            treatment = category.required(
                [o for o in self.store.for_resource(category.system_id, resource_id)
                 if o.observed_at <= request.audit_at],
                resolution.state,
                self.worker_actions.latest_type(category.system_id, resource_id, request.audit_at))
            assessments.append(steps.Assessment(
                system_id=category.system_id, resource_id=resource_id, treatment=treatment,
                compliant=resolution.state == treatment.target,
                evidence_id=cite(category, resource_id, resolution, self.store, request.audit_at)))
        return steps.build(assessments)


def run(requests_path, output_path):
    requests = sorted(load_requests(requests_path), key=lambda r: r.case_id)
    auditor = Auditor(requests)
    rows = []
    for request in requests:
        status, case_steps = auditor.audit(request)
        rows.append((request.case_id, status, steps.serialize(case_steps)))
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        writer.writerows(rows)
    return rows
