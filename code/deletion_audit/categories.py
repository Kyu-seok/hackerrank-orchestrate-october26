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
