"""The Resource states of the output contract (AGENTS.md section 6.4).

A record is PRESENT or ABSENT, or kept in a compliant form (REDACTED,
ANONYMIZED). A Data flow is ACTIVE or DISABLED; a backup's restore path is
ACTIVE (restorable) or BLOCKED.
"""

PRESENT = "PRESENT"
ABSENT = "ABSENT"
REDACTED = "REDACTED"
ANONYMIZED = "ANONYMIZED"
ACTIVE = "ACTIVE"
DISABLED = "DISABLED"
BLOCKED = "BLOCKED"
