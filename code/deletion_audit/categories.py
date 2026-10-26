"""Registry of Resource categories: one row per kind of Resource the audit handles.

Each Category says which system it lives in, which deletion-rule data category
applies, its default Required treatment, and how to read a Resource's current
state from one Observation. Add a category with one ``register(...)`` call; the
rest of the pipeline (attribution, state, steps) is category-agnostic.
"""

from dataclasses import dataclass
from typing import Callable

from . import treatments
from .evidence import ABSENT, PRESENT


@dataclass(frozen=True)
class Category:
    name: str                    # deletion_rules.csv data_category
    system_id: str
    resource_prefix: str         # resource_id prefix, e.g. "account_"
    treatment: treatments.Treatment
    assess: Callable             # Observation -> current state (e.g. PRESENT, ABSENT, ANONYMIZED)

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
    """State of a record whose only question is whether it still exists."""
    return ABSENT if observation.presence == ABSENT else PRESENT


USER_PROFILE = register(Category(
    name="USER_PROFILE", system_id="account_service", resource_prefix="account_",
    treatment=treatments.DELETE, assess=presence))


# -- Data flows and restore paths ----------------------------------------------
# Their state is a switch, not a record's presence: a connector is ACTIVE or
# DISABLED, a backup's restore path is ACTIVE (restorable) or BLOCKED. Sources
# state it as a check result (ACTIVE/DISABLED/BLOCKED), a flag (``enabled``,
# ``restore_allowed``: bool, 0/1 or "true"/"false"), a restore evaluation
# (``eligible``/``deletion_block``) or an authorization decision (``deny``).
ACTIVE = "ACTIVE"
DISABLED = "DISABLED"
BLOCKED = "BLOCKED"


def _flag(value):
    """True/False for a boolean-like field value, None when absent or unreadable."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _switch(observation, flag_fields, off_state):
    """ACTIVE unless the Observation shows the switch off. Unknown counts as ACTIVE."""
    result = observation.result
    if result in (DISABLED, BLOCKED):
        return off_state
    if result == ACTIVE:
        return ACTIVE
    fields = observation.fields
    for name in flag_fields:
        flag = _flag(fields.get(name))
        if flag is not None:
            return ACTIVE if flag else off_state
    return ACTIVE


def data_flow_state(observation):
    return _switch(observation, ("enabled", "scheduler_registered"), DISABLED)


DATA_FLOW = register(Category(
    name="DATA_FLOW", system_id="integration_service", resource_prefix="data_flow_",
    treatment=treatments.DISABLE_FLOW, assess=data_flow_state))


def restore_state(observation):
    fields = observation.fields
    if str(fields.get("decision", "")).lower() == "deny" or _flag(fields.get("deletion_block")):
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
