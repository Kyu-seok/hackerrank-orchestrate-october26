# Evaluation case: Account tombstone known only from a screenshot and a catalog alias

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/tombstone_in_screenshot/requests.csv --output /tmp/tombstone.csv
python3 code/evaluation/main.py /tmp/tombstone.csv --gold code/evaluation/cases/tombstone_in_screenshot/answers.csv --verbose
```

## Scenario

Real dataset user `user_17` (`leonie.g9352@outlook.com`), with the times of eval `case_46`
(her March request; sample `case_17` is her later, separate September request):

| field | value |
| --- | --- |
| case_id | `eval_tombstone_01` |
| requested_at | 2026-03-08T03:00:00Z |
| reported_at | 2026-03-09T21:00:00Z (workflow Claim: COMPLETE) |
| audit_at | 2026-03-11T08:00:00Z |

Evidence:

| Evidence item | time | what it shows |
| --- | --- | --- |
| `evidence_42` (PNG, "Customer Reference Registry") | 2026-03-10T06:00:00Z | customer key `user_17`, status "Retained reference", 4 linked records (`ORD-20263245`, `CS-3245`, `CS-3378`, `FIN-7742`); no name, email or phone shown. No resource id on screen. |
| `activity_4011` | 2026-03-10T06:07:01Z | link-identity: "Data catalog linked tombstone_17 (user_17) to leonie.g9352@outlook.com and user_17." |
| `evidence_67` (readback log) | 2026-03-10T06:18:01Z | `profile_lookup_completed resource_id=account_6523 rows=0 http_status=404`, lookup key leonie.g9352@ |

The screenshot is read from the committed extraction cache. Its identity record carries no
resource id; the catalog alias `tombstone_17 (user_17)` names it.

## Expected answer

rule_15: the account is deleted and only the stable `user_id` remains to keep references to the
retained order, support and finance records resolvable, so the identity record is an Account
tombstone (REDACT). The registry entry shows no direct identifier, so it is already compliant.

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | VERIFICATION | account_service | account_6523 | VERIFY_RECORD_ABSENT | ABSENT | evidence_67 |
| 2 | VERIFICATION | identity_service | tombstone_17 | VERIFY_RECORD_REDACTED | REDACTED | evidence_42 |

Without alias resolution the tombstone has no Observation, is treated as present with nothing
retained, and is wrongly reported as a remaining record to delete with no evidence.
