# Evaluation case: Resource linked by a link-identity activity, contradicted by a later screenshot

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/resource_linked_by_catalog/requests.csv --output /tmp/link.csv
python3 code/evaluation/main.py /tmp/link.csv --gold code/evaluation/cases/resource_linked_by_catalog/answers.csv --verbose
```

## Scenario

Real dataset user `user_11` (Haruka Sato, `haruka.s1838@zoho.com`; phone before 2026-05-17
`+81 90 6156 0005`), re-audited with our own times:

| field | value |
| --- | --- |
| case_id | `eval_link_01` |
| requested_at | 2026-09-25T08:00:00Z |
| reported_at | 2026-09-26T08:00:00Z (workflow Claim: NOT_STARTED) |
| audit_at | 2026-09-28T12:00:00Z |

Evidence, in time order:

| Evidence item | time | what it shows |
| --- | --- | --- |
| `activity_3485` / `activity_3489` | 2026-08-28 | deletion-worker DELETE of `account_5762` and `support_9538`, both reported FAILED (Claims) |
| `evidence_01` | 2026-09-15T11:51:46Z | `attachment_pii_scan resource_id=support_9538 matched_value="+81 90 6156 0005" file=delivery_confirmation_32.pdf` (the Subject's old phone in a support attachment) |
| `evidence_01` | 2026-09-15T11:54:30Z | readback `profile_lookup_completed resource_id=account_5762 rows=0 http_status=404` |
| `evidence_04` (PNG, account admin console) | 2026-09-26T11:00:00Z | live customer profile `account_5762` for Haruka Sato, `user_11`, current email and phone, orders up to 18 Sep, and support ticket `CS-8538 / support_9538` (customer replied 24 Sep) |
| `activity_4000` | 2026-09-26T11:07:01Z | link-identity: "Data catalog linked account_5762 (account_5762) to haruka.s1838@zoho.com and user_11." |

`evidence_01` is before `requested_at`, so it does not attribute anything to this case on its own.
Inside the case window the link-identity activity ties `account_5762` to the Subject, and the
screenshot `evidence_04` (read from the committed extraction cache) names both `account_5762` and
`support_9538` next to the Subject's identifiers.

## Expected answer

The latest Observation of each Resource at or before the cutoff is the 2026-09-26 screenshot, which
shows both still live, so it overrides the 404 of 2026-09-15: the account is a remaining record
(rule_01). `support_9538` is a support attachment holding the Subject's (old) phone, and the deletion
worker's own action on it is a delete, so it is a remaining attachment (rule_06) rather than a message
to redact. The case is `INCOMPLETE` despite nothing in the workflow claiming success.

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | FINDING | account_service | account_5762 | REPORT_REMAINING_RECORD | PRESENT | evidence_04 |
| 2 | FINDING | support_platform | support_9538 | REPORT_REMAINING_RECORD | PRESENT | evidence_04 |
| 3 | REMEDIATION | account_service | account_5762 | DELETE_RECORD | ABSENT | |
| 4 | REMEDIATION | support_platform | support_9538 | DELETE_RECORD | ABSENT | |
| 5 | VERIFICATION | account_service | account_5762 | VERIFY_RECORD_ABSENT | ABSENT | |
| 6 | VERIFICATION | support_platform | support_9538 | VERIFY_RECORD_ABSENT | ABSENT | |

History: before the PDF/image extraction cache was committed this key expected `COMPLETE` with a
single `VERIFY_RECORD_ABSENT` citing `evidence_01`, because the pipeline could not read the
screenshot. Reading `evidence_04` showed the account still live at 2026-09-26, after the 404, so the
key was corrected. Without the screenshot or the link activity the account would be judged on the
stale 404 alone.
