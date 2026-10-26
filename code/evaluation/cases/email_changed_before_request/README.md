# Evaluation case: email changed before the request

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/email_changed_before_request/requests.csv --output /tmp/history.csv
python3 code/evaluation/main.py /tmp/history.csv --gold code/evaluation/cases/email_changed_before_request/answers.csv --verbose
```

## Scenario

Real dataset user `user_41` (Javier Ríos) changed email on 2026-05-28 (`audit_293`/`audit_294`):
old `javier.r940897@outlook.com`, current `javier.r9408@outlook.com`. Our request uses the
**current** email (dataset `case_43` uses the old one):

| field | value |
| --- | --- |
| case_id | `eval_history_01` |
| email | `javier.r9408@outlook.com` (current) |
| requested_at | 2026-09-15T11:00:00Z |
| reported_at | 2026-09-16T11:00:00Z (workflow Claim: NOT_STARTED) |
| audit_at | 2026-09-26T11:00:00Z |

Evidence about the Subject's account `account_8681`:

| Evidence item | time | what it shows |
| --- | --- | --- |
| `activity_3885` | 2026-09-18T09:58:34Z | Action activity: delete `account_8681`, SUCCESS (a Claim, not proof) |
| `evidence_94` | line 2026-09-26T09:21:55Z, file 10:38:56Z | readback `profile_lookup_completed resource_id=account_8681 rows=1 http_status=200 email=javier.r940897@outlook.com` |

No record anywhere carries the current email, phone or hash. No deletion-worker account action
lands near `reported_at`, so the workflow cannot supply the account either: only the old email,
recovered from `user_audit_log.csv`, links the surviving row to the Subject.

## Expected answer

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | FINDING | account_service | account_8681 | REPORT_REMAINING_RECORD | PRESENT | evidence_94 |
| 2 | REMEDIATION | account_service | account_8681 | DELETE_RECORD | ABSENT | |
| 3 | VERIFICATION | account_service | account_8681 | VERIFY_RECORD_ABSENT | ABSENT | |

Without identity history the pipeline answers `COMPLETE` with no steps (the ghost is missed).
