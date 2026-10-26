"""Registry of Resource categories: one row per kind of Resource the audit handles.

Each Category says which system it lives in, which deletion-rule data category
applies, its default Required treatment, and how to read a Resource's current
state from one Observation. Add a category with one ``register(...)`` call; the
rest of the pipeline (attribution, state, steps) is category-agnostic.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from . import conditional, treatments
from .flags import flag
from .states import ABSENT, ACTIVE, BLOCKED, DISABLED, PRESENT


@dataclass(frozen=True)
class Category:
    name: str                    # deletion_rules.csv data_category
    system_id: str
    resource_prefix: str         # resource_id prefix, e.g. "account_"
    treatment: treatments.Treatment
    assess: Callable             # Observation -> current state (e.g. PRESENT, ABSENT, ANONYMIZED)
    # Conditional rules: (observations, state, worker action type, **case) -> Required treatment,
    # where ``case`` holds ``audit_at`` and ``retained`` (see ``required``).
    decide: Optional[Callable] = None
    # Decided after the case's other Resources: its rule depends on what the case retains.
    after_retained: bool = False

    def required(self, observations, state, worker_action=None, audit_at="", retained=False):
        """Required treatment for one Resource (the fixed ``treatment`` unless the rule is conditional).

        ``retained``: the case keeps at least one RETAINED Resource referencing the Subject.
        """
        if self.decide is None:
            return self.treatment
        return self.decide(observations, state, worker_action, audit_at=audit_at, retained=retained)

    def owns(self, system_id, resource_id):
        return system_id == self.system_id and resource_id.startswith(self.resource_prefix)


REGISTRY = []


def register(category):
    REGISTRY.append(category)
    return category


def category_for(system_id, resource_id):
    for category in REGISTRY:
        if category.owns(system_id, resource_id):
            return category
    return None


def presence(observation):
    """State of a Resource whose only question is whether it still exists."""
    return ABSENT if observation.presence == ABSENT else PRESENT


USER_PROFILE = register(Category(
    name="USER_PROFILE", system_id="account_service", resource_prefix="account_",
    treatment=treatments.DELETE, assess=presence))


# -- Data flows and restore paths ----------------------------------------------
# Their state is a switch, not a Resource's presence: a connector is ACTIVE or
# DISABLED, a backup's restore path is ACTIVE (restorable) or BLOCKED. Sources
# state it as a check result (ACTIVE/DISABLED/BLOCKED), a flag (``enabled``,
# ``restore_allowed``: bool, 0/1 or "true"/"false"), a restore evaluation
# (``eligible``/``deletion_block``) or an authorization decision (``deny``).
def _switch(observation, flag_fields, off_state):
    """ACTIVE unless the Observation shows the switch off. Unknown counts as ACTIVE."""
    result = observation.result
    if result in (DISABLED, BLOCKED):
        return off_state
    if result == ACTIVE:
        return ACTIVE
    fields = observation.fields
    for name in flag_fields:
        on = flag(fields.get(name))
        if on is not None:
            return ACTIVE if on else off_state
    return ACTIVE


def data_flow_state(observation):
    return _switch(observation, ("enabled", "scheduler_registered"), DISABLED)


DATA_FLOW = register(Category(
    name="DATA_FLOW", system_id="integration_service", resource_prefix="data_flow_",
    treatment=treatments.DISABLE_FLOW, assess=data_flow_state))


def restore_state(observation):
    fields = observation.fields
    if str(fields.get("decision", "")).lower() == "deny" or flag(fields.get("deletion_block")):
        return BLOCKED
    return _switch(observation, ("restore_allowed", "eligible"), BLOCKED)


# Backups are always retained: the only treatment is blocking their restore path.
BACKUP_ARCHIVE = register(Category(
    name="BACKUP_ARCHIVE", system_id="backup_service", resource_prefix="backup_",
    treatment=treatments.BLOCK_RESTORE, assess=restore_state))

# Always-delete categories (rule_02/03/04/09/10). Rows found in a Replica are
# already reported under the copied system by the evidence loaders.
SEARCH_INDEX_ENTRY = register(Category(
    name="SEARCH_INDEX_ENTRY", system_id="search_service", resource_prefix="search_",
    treatment=treatments.DELETE, assess=presence))
USER_EXPORT = register(Category(
    name="USER_EXPORT", system_id="export_service", resource_prefix="export_",
    treatment=treatments.DELETE, assess=presence))
# Marketing profiles are linked only by a link-identity activity and a console
# screenshot; cache entries appear only in REFRESH_CACHE activities. Registered
# so attribution and state handle them as soon as evidence names them.
MARKETING_PROFILE = register(Category(
    name="MARKETING_PROFILE", system_id="marketing_platform", resource_prefix="marketing_",
    treatment=treatments.DELETE, assess=presence))
CACHE_ENTRY = register(Category(
    name="CACHE_ENTRY", system_id="cache_service", resource_prefix="cache_",
    treatment=treatments.DELETE, assess=presence))

# Conditional rules decided from the Resource's own fields (see conditional.py).
SUPPORT_MESSAGE = register(Category(
    name="SUPPORT_MESSAGE", system_id="support_platform", resource_prefix="support_",
    treatment=treatments.REDACT, assess=conditional.redaction, decide=conditional.support_treatment))

ANALYTICS_PROFILE = register(Category(
    name="ANALYTICS_PROFILE", system_id="analytics_platform", resource_prefix="analytics_",
    treatment=treatments.ANONYMIZE, assess=conditional.anonymization, decide=conditional.anonymize_treatment))

EMAIL_DELIVERY_LOG = register(Category(
    name="EMAIL_DELIVERY_LOG", system_id="email_delivery_service", resource_prefix="email_delivery_",
    treatment=treatments.REDACT, assess=conditional.redaction, decide=conditional.redact_treatment))

# Resources policy requires to keep (rules 12-13): verified present while the stated
# retention period or legal hold runs at the Audit cutoff, deleted once it has ended.
SECURITY_AUDIT_LOG = register(Category(
    name="SECURITY_AUDIT_LOG", system_id="security_service", resource_prefix="audit_record_",
    treatment=treatments.RETAIN, assess=presence, decide=conditional.retain_treatment))
LEGAL_HOLD_RECORD = register(Category(
    name="LEGAL_HOLD_RECORD", system_id="legal_service", resource_prefix="legal_hold_",
    treatment=treatments.RETAIN, assess=presence, decide=conditional.retain_treatment))

# The deleted account's identity Resource (rule_15): an Account tombstone keeping only
# the user_id while retained Resources still reference it, otherwise deleted.
ACCOUNT_TOMBSTONE = register(Category(
    name="ACCOUNT_TOMBSTONE", system_id="identity_service", resource_prefix="tombstone_",
    treatment=treatments.REDACT, assess=conditional.redaction, decide=conditional.tombstone_treatment,
    after_retained=True))
