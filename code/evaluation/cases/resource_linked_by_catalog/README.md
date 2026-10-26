# Evaluation case: Resource linked only by a link-identity activity

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/resource_linked_by_catalog/requests.csv --output /tmp/link.csv
python3 code/evaluation/main.py /tmp/link.csv --gold code/evaluation/cases/resource_linked_by_catalog/answers.csv --verbose
```

## Scenario

Real dataset user `user_11` (Haruka Sato, `haruka.s1838@zoho.com`), re-audited with our own times:

| field | value |
| --- | --- |
| case_id | `eval_link_01` |
| requested_at | 2026-09-25T08:00:00Z |
| reported_at | 2026-09-26T08:00:00Z (workflow Claim: NOT_STARTED) |
| audit_at | 2026-09-28T12:00:00Z |

Evidence about the account `account_5762`:

| Evidence item | time | what it shows |
| --- | --- | --- |
| `evidence_01` | 2026-09-15T11:54:30Z | readback `profile_lookup_completed resource_id=account_5762 rows=0 http_status=404` (before `requested_at`, so it does not link the account to this case) |
| `activity_4000` | 2026-09-26T11:07:01Z | `LINK_RESOURCE_IDENTITY`: "Data catalog linked account_5762 (account_5762) to haruka.s1838@zoho.com and user_11." |

Inside the case window nothing carrying the Subject's identifiers mentions `account_5762`, and no
deletion-worker account action lands near `reported_at`. The link-identity activity is the only
attribution. Once linked, the latest Observation at or before the cutoff (the 404) proves it absent.

## Expected answer

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | VERIFICATION | account_service | account_5762 | VERIFY_RECORD_ABSENT | ABSENT | evidence_01 |

Without link attribution the pipeline answers `COMPLETE` with no steps.
