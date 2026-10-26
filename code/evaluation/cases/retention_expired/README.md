# Evaluation case: retention period ended before the audit

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/retention_expired/requests.csv --output /tmp/retention.csv
python3 code/evaluation/main.py /tmp/retention.csv --gold code/evaluation/cases/retention_expired/answers.csv --verbose
```

## Scenario

Real dataset user `user_03` (Oliver Bennett, `oliver-bennett@gmail.com`), the Subject of eval `case_45`
(audit 2026-09-06), re-audited a year later with our own cutoff:

| field | value |
| --- | --- |
| case_id | `eval_retention_01` |
| requested_at | 2026-09-03T04:00:00Z |
| reported_at | 2026-09-04T22:00:00Z (workflow Claim: COMPLETE) |
| audit_at | 2027-09-01T12:00:00Z |

Evidence:

| Evidence item | time | what it shows |
| --- | --- | --- |
| `evidence_55` (PDF, compliance journal extract) | 2026-09-05T06:30:00Z | `audit_record_003`, subject `user_03`, "Account closure recorded", **retain until 25 Aug 2027** |
| `evidence_37` (PNG, security audit explorer) | 2026-09-05T07:00:00Z | six account events `audit_record_001`..`006` for subject `user_03`, all present; no retention date shown |
| `activity_4010` | 2026-09-05T07:07:01Z | link-identity: `audit_record_003` belongs to oliver-bennett@ / `user_03` |

Both files are read from the committed extraction cache (`code/llm_cache/evidence_extraction/`).

## Expected answer

rule_12 retains a SECURITY_AUDIT_LOG record only "within the supplied retention period". The only
supplied period is the PDF's 2027-08-25 end for `audit_record_003`, which has passed at the cutoff,
so the RETAIN condition no longer holds and the record falls back to DELETE. It was last seen present
(`evidence_37`, the latest citable file), so it is a remaining record. The other five records state no
end, so they stay retained and are verified present (as every sample audit record is).

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | FINDING | security_service | audit_record_003 | REPORT_REMAINING_RECORD | PRESENT | evidence_37 |
| 2 | REMEDIATION | security_service | audit_record_003 | DELETE_RECORD | ABSENT | |
| 3 | VERIFICATION | security_service | audit_record_003 | VERIFY_RECORD_ABSENT | ABSENT | |
| 4-8 | VERIFICATION | security_service | audit_record_001, 002, 004, 005, 006 | VERIFY_RECORD_PRESENT | PRESENT | |

At `case_45`'s own cutoff (2026-09-06) the same six records are all verified present. The case fails
if retention is applied without reading the period (record kept forever) or if every audit record is
deleted.
