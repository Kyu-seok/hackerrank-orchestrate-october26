"""Which Resources belong to a case's Subject.

1. Identifier match: an Observation of a registered category whose record
   carries any value of the Identifier set (customer reference = user_id, email,
   phone, email hash), observed inside the case window [requested_at, audit_at].
   The lower bound keeps a returning Subject's earlier case out of this one.
2. Workflow match, for categories every case covers (the account) when no
   identifier match exists. Deleted accounts often carry no identifier at all,
   so the deletion workflow is the only link: a deletion-worker Action activity
   on that system shortly before the case's ``reported_at``. Several cases can
   share a ``reported_at``, so candidates are resolved jointly over every known
   request: a Resource an identifier ties to another person, or that another
   case already matched, is excluded, and a case left with a single candidate
   claims it (repeated until nothing changes).
"""

from datetime import datetime, timedelta

from . import categories
from .activities import action_activities
from .identity import identifier_owners, resolve_subject

# The workflow's Action activity on the account lands within this window around reported_at.
WORKFLOW_BEFORE = timedelta(minutes=80)
WORKFLOW_AFTER = timedelta(minutes=10)
# Categories that every deletion case covers even without an identifier match.
ALWAYS_IN_SCOPE = (categories.USER_PROFILE,)

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _shift(text, delta):
    return (datetime.strptime(text, _FMT) + delta).strftime(_FMT)


class Attributor:
    """Built once over every known request so that workflow matches are resolved jointly."""

    def __init__(self, dataset, store, requests):
        self.dataset = dataset
        self.store = store
        self.actions = action_activities(dataset)
        self.owned_by = self._owners()
        self._plan = self._resolve(requests)

    def resources(self, request):
        """Sorted [(category, resource_id)] in scope for the case."""
        found = self._plan.get(request.case_id, set())
        return sorted(found, key=lambda cr: (cr[0].system_id, cr[1]))

    # -- identifier ownership --------------------------------------------------
    def _owners(self):
        """(system_id, resource_id) -> user_ids any identifier ties it to (at any time)."""
        owners = identifier_owners(self.dataset)
        owned = {}
        for obs in self.store.observations:
            if categories.category_for(obs.system_id, obs.resource_id) is None:
                continue
            users = set()
            for token in obs.tokens:
                users |= owners.get(token, set())
            if users:
                owned.setdefault((obs.system_id, obs.resource_id), set()).update(users)
        return owned

    def _identifier_matches(self, request, subject):
        """(registered matches, evidence ids holding any Subject-linked record) in the case window."""
        found, files = set(), set()
        for obs in self.store.observations:
            if not (request.requested_at <= obs.observed_at <= request.audit_at):
                continue
            if obs.tokens & subject.identifiers:
                files.add(obs.evidence_id)
                category = categories.category_for(obs.system_id, obs.resource_id)
                if category is not None:
                    found.add((category, obs.resource_id))
        return found, files

    def _co_located(self, category, resource_id, files, audit_at):
        """Is the Resource observed in an Evidence file that also holds a Subject-linked record?"""
        return any(o.evidence_id in files and o.observed_at <= audit_at
                   for o in self.store.for_resource(category.system_id, resource_id))

    # -- workflow matches -------------------------------------------------------
    def _workflow_candidates(self, category, request, subject):
        lo = _shift(request.reported_at, -WORKFLOW_BEFORE)
        hi = _shift(request.reported_at, WORKFLOW_AFTER)
        out = set()
        for act in self.actions:
            if lo <= act["event_time"] <= hi and category.owns(act["target_system"], act["resource_id"]):
                others = self.owned_by.get((category.system_id, act["resource_id"]), set()) - {subject.user_id}
                if not others:
                    out.add(act["resource_id"])
        return out

    def _resolve(self, requests):
        plan, subjects, linked_files = {}, {}, {}
        for request in requests:
            subject = resolve_subject(request.email, self.dataset)
            if subject is not None:
                subjects[request.case_id] = (request, subject)
                plan[request.case_id], linked_files[request.case_id] = \
                    self._identifier_matches(request, subject)

        for category in ALWAYS_IN_SCOPE:
            claimed = {}  # resource_id -> user_ids whose identifier match includes it
            for case_id, found in plan.items():
                for c, rid in found:
                    if c is category:
                        claimed.setdefault(rid, set()).add(subjects[case_id][1].user_id)
            options = {}  # case_id -> (all candidates, preferred candidates)
            for case_id, (request, subject) in subjects.items():
                if any(c is category for c, _ in plan[case_id]):
                    continue
                cands = {rid for rid in self._workflow_candidates(category, request, subject)
                         if not claimed.get(rid, set()) - {subject.user_id}}
                # Prefer candidates seen next to the Subject's other records.
                near = {rid for rid in cands
                        if self._co_located(category, rid, linked_files[case_id], request.audit_at)}
                options[case_id] = (cands, near)
            user_of = {case_id: subjects[case_id][1].user_id for case_id in options}
            first_action = {}
            for act in self.actions:  # sorted by time
                first_action.setdefault(act["resource_id"], act["event_time"])
            settled = _settle(options, user_of,
                              case_order=lambda c: (subjects[c][0].requested_at, c),
                              resource_order=lambda rid: (first_action.get(rid, ""), rid))
            for case_id, rids in settled.items():
                plan[case_id] |= {(category, rid) for rid in rids}
        return plan


def _settle(options, user_of, case_order, resource_order):
    """Give each open case one workflow Resource.

    A case left with exactly one candidate takes it away from cases of other
    Subjects; repeat until stable. Each case uses its preferred candidates while
    any remain, else all of its candidates. When only ambiguous cases are left,
    the earliest case (``case_order``) takes its earliest candidate
    (``resource_order``) and settling continues: the evidence cannot separate
    them, so the pick is a deterministic guess.
    """
    taken_from = {case_id: set() for case_id in options}
    chosen = {}

    def current(case_id):
        if case_id in chosen:
            return {chosen[case_id]}
        cands, near = options[case_id]
        near = near - taken_from[case_id]
        return near or (cands - taken_from[case_id])

    def claim(case_id, rid):
        changed = False
        for other in options:
            if user_of[other] != user_of[case_id] and rid not in taken_from[other]:
                taken_from[other].add(rid)
                changed = True
        return changed

    while True:
        changed = True
        while changed:
            changed = False
            for case_id in sorted(options):
                mine = current(case_id)
                if len(mine) == 1:
                    changed |= claim(case_id, next(iter(mine)))
        ambiguous = sorted((c for c in options if len(current(c)) > 1), key=case_order)
        if not ambiguous:
            break
        case_id = ambiguous[0]
        chosen[case_id] = min(current(case_id), key=resource_order)
        claim(case_id, chosen[case_id])
    return {case_id: current(case_id) for case_id in options}
