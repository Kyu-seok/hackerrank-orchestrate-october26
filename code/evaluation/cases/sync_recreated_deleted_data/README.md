# Evaluation case: sync recreated deleted data

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/sync_recreated_deleted_data/requests.csv --output /tmp/sync.csv
python3 code/evaluation/main.py /tmp/sync.csv --gold code/evaluation/cases/sync_recreated_deleted_data/answers.csv --verbose
```

## Scenario

Real dataset user `user_14` (Aditi Jain, `jain.aditi@gmail.com`). The dataset holds a full
deletion workflow for her on 2026-08-25 that no request file covers (eval `case_39` is an earlier,
separate request from 2026-08-05), so we supply the request:

| field | value |
| --- | --- |
| case_id | `eval_sync_01` |
| requested_at | 2026-08-24T09:00:00Z |
| reported_at | 2026-08-25T12:00:00Z (workflow Claim: COMPLETE) |
| audit_at | 2026-09-15T12:00:00Z |

What happened, in time order:

| Evidence item | time | what it shows |
| --- | --- | --- |
| `activity_4002` | 2026-08-07T08:07:01Z | Link-identity: `data_flow_1121` belongs to jain.aditi@ / user_14 (before the request) |
| `activity_3430` | 2026-08-25T10:45:32Z | Action: delete `account_8926` (Claim, reported FAILED) |
| `activity_3434` | 2026-08-25T12:44:24Z | `SYNC_RECORD`: active connector `data_flow_1121` **repopulated downstream resource `search_4801`** |
| `activity_3437` | 2026-08-25T13:03:53Z | Action: delete `search_4801` (Claim, FAILED) |
| `evidence_01` 11:53:09 | 2026-09-15 | `search_service index_query_completed result=hit` for `search_4801`, correlation_key jain.aditi@ |
| `evidence_01` 11:53:56 | 2026-09-15 | `audit_record_7301` read, `rows=1` (Subject's security audit record) |
| `evidence_01` 11:54:45 | 2026-09-15 | `connector_heartbeat` for `data_flow_1121`: `enabled=true scheduler_registered=true`, trace keyed by jain.aditi@ |
| `evidence_01` 11:57:27 | 2026-09-15 | `profile_lookup_completed rows=0 http_status=404` for `account_8926` |

`evidence_01` (manifest captured 2026-09-15T11:59:39Z) is the latest citable file for each Resource.

## Expected answer

The connector is still enabled and the search entry it recreated is still served, so the case is
`INCOMPLETE` despite the workflow's COMPLETE Claim. The flow is disabled before the search entry is
deleted (contract remediation order), the account is already gone, and the security audit record is
retained:

| step | phase | system_id | resource_id | operation | state | evidence_id |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | FINDING | search_service | search_4801 | REPORT_REMAINING_RECORD | PRESENT | evidence_01 |
| 2 | FINDING | integration_service | data_flow_1121 | REPORT_ACTIVE_DATA_FLOW | ACTIVE | evidence_01 |
| 3 | REMEDIATION | integration_service | data_flow_1121 | DISABLE_DATA_FLOW | DISABLED | |
| 4 | REMEDIATION | search_service | search_4801 | DELETE_RECORD | ABSENT | |
| 5 | VERIFICATION | account_service | account_8926 | VERIFY_RECORD_ABSENT | ABSENT | |
| 6 | VERIFICATION | search_service | search_4801 | VERIFY_RECORD_ABSENT | ABSENT | |
| 7 | VERIFICATION | security_service | audit_record_7301 | VERIFY_RECORD_PRESENT | PRESENT | |
| 8 | VERIFICATION | integration_service | data_flow_1121 | VERIFY_DATA_FLOW_DISABLED | DISABLED | |

This mirrors the shape of samples `case_15` (active connector) and `case_17` (restore risk), which
also read their evidence from `evidence_01`. The case fails if the connector is missed, if the
search entry is trusted as deleted, or if the flow is not disabled before the dependent delete.
