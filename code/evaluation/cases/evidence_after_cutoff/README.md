# Evaluation case: evidence after the Audit cutoff

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/evidence_after_cutoff/requests.csv --output /tmp/cutoff.csv
python3 code/evaluation/main.py /tmp/cutoff.csv --gold code/evaluation/cases/evidence_after_cutoff/answers.csv --verbose
```

## Scenario

Real dataset user `user_05` (Leila Haddad, `leila.haddad@yahoo.com`, the Subject of sample
`case_05`), re-audited with our own times:

| field | value |
| --- | --- |
| case_id | `eval_cutoff_01` |
| requested_at | 2026-08-27T09:00:00Z |
| reported_at | 2026-08-28T09:03:00Z (workflow Claim: COMPLETE) |
| audit_at | **2026-09-02T22:00:00Z** |

Evidence about the Subject's account `account_005`:

| Evidence item | captured_at | what it shows |
| --- | --- | --- |
| `activity_3482` | 2026-08-28T09:11:01Z | Action activity: delete `account_005`, SUCCESS (a Claim, not proof) |
| `evidence_10` | 2026-08-27T12:00:00Z | read-replica dump covering `account_service`; no `account_005` row |
| `evidence_54` | 2026-09-02T23:00:00Z | failover replica still holds `account_005` with full PII (**one hour after the cutoff**) |
| `evidence_90` | 2026-09-05T07:18:01Z | inventory scoped to `account_service`, no rows (after the cutoff) |

## Expected answer

At the cutoff the latest covering snapshot (`evidence_10`) lacks the account, so the case is
`COMPLETE` with one verification citing `evidence_10`:

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | VERIFICATION | account_service | account_005 | VERIFY_RECORD_ABSENT | ABSENT | evidence_10 |

If `evidence_54` were counted, the failover ghost would turn the case `INCOMPLETE`
(`REPORT_REMAINING_RECORD` → `DELETE_RECORD` → `VERIFY_RECORD_ABSENT`), which is what sample
`case_05` (audit_at 2026-09-08) expects. The case therefore fails if anything captured after
`audit_at` leaks into state reconstruction or citation.
