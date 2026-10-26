"""Which system an evidence row describes.

Replicas are reported under the system they copy, so every name here maps to
the copied system's ``system_id``. Add rows to these tables (not branches in the
loaders) when a new source shape appears.
"""

# Flat SQL tables (inventory and single-system dumps) -> system_id.
SQL_TABLE_SYSTEMS = {
    "customer_profiles": "account_service",
    "customer_profiles_primary": "account_service",
    "customer_profiles_failover_replica": "account_service",
    "customer_search_documents": "search_service",
    "search_documents_primary": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}

# JSON collections that do not name their system -> system_id.
COLLECTION_SYSTEMS = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_reports": "analytics_platform",
    "support_conversations": "support_platform",
    "ticket_attachments": "support_platform",
    "customer_export_jobs": "export_service",
    "connector_configurations": "integration_service",
    "backup_catalog": "backup_service",
    "security_audit_events": "security_service",
    "retained_order_records": "legal_service",
    "deleted_customer_references": "identity_service",
}

# Check results that prove a Resource does not exist.
ABSENT_RESULTS = {"NOT_FOUND"}

# Service names used in logs that are not themselves gold system ids.
LOG_SERVICE_SYSTEMS = {
    "support_replica": "support_platform",
}


def log_system(record):
    """System for a log record: an explicit ``system`` field wins over the
    emitting service (a search_index_service check line can report on
    account_service)."""
    system = record.get("system") or record.get("service") or ""
    return LOG_SERVICE_SYSTEMS.get(system, system)
