"""Required treatments and the contract operations each one uses.

A treatment fixes the compliant final state of a Resource and the finding,
remediation and verification operations used when it is (or is not) in that
state. Operation/state pairs follow AGENTS.md section 6.4.
"""

from collections import namedtuple

from .states import ABSENT, ACTIVE, ANONYMIZED, BLOCKED, DISABLED, PRESENT, REDACTED

Treatment = namedtuple("Treatment", "name target finding remediation verification")

DELETE = Treatment("DELETE", ABSENT, "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
REDACT = Treatment("REDACT", REDACTED, "REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
ANONYMIZE = Treatment("ANONYMIZE", ANONYMIZED, "REPORT_EXPOSED_PII", "ANONYMIZE_RECORD",
                      "VERIFY_RECORD_ANONYMIZED")
RETAIN = Treatment("RETAIN", PRESENT, None, None, "VERIFY_RECORD_PRESENT")
DISABLE_FLOW = Treatment("DISABLE_FLOW", DISABLED, "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                         "VERIFY_DATA_FLOW_DISABLED")
BLOCK_RESTORE = Treatment("BLOCK_RESTORE", BLOCKED, "REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                          "VERIFY_RESTORE_BLOCKED")

# Contract table order: phase, then operation order within the phase.
OPERATIONS = (
    ("REPORT_REMAINING_RECORD", "FINDING", PRESENT),
    ("REPORT_EXPOSED_PII", "FINDING", PRESENT),
    ("REPORT_ACTIVE_DATA_FLOW", "FINDING", ACTIVE),
    ("REPORT_RESTORE_RISK", "FINDING", ACTIVE),
    ("DISABLE_DATA_FLOW", "REMEDIATION", DISABLED),
    ("BLOCK_RESTORE", "REMEDIATION", BLOCKED),
    ("DELETE_RECORD", "REMEDIATION", ABSENT),
    ("REDACT_RECORD", "REMEDIATION", REDACTED),
    ("ANONYMIZE_RECORD", "REMEDIATION", ANONYMIZED),
    ("VERIFY_RECORD_ABSENT", "VERIFICATION", ABSENT),
    ("VERIFY_RECORD_PRESENT", "VERIFICATION", PRESENT),
    ("VERIFY_RECORD_REDACTED", "VERIFICATION", REDACTED),
    ("VERIFY_RECORD_ANONYMIZED", "VERIFICATION", ANONYMIZED),
    ("VERIFY_DATA_FLOW_DISABLED", "VERIFICATION", DISABLED),
    ("VERIFY_RESTORE_BLOCKED", "VERIFICATION", BLOCKED),
)
PHASE_STATE = {op: (phase, state) for op, phase, state in OPERATIONS}
PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OPERATION_ORDER = {op: i for i, (op, _, _) in enumerate(OPERATIONS)}
