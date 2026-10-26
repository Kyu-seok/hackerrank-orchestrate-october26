# Evaluation case: request that does not ask for deletion

Files: `requests.csv` (one request), `answers.csv` (answer key, scorer format).

```text
python3 code/main.py --requests code/evaluation/cases/not_a_deletion_request/requests.csv --output /tmp/not_deletion.csv
python3 code/evaluation/main.py /tmp/not_deletion.csv --gold code/evaluation/cases/not_a_deletion_request/answers.csv --verbose
```

## Scenario

Real dataset user `user_15` (Lucía Torres, `lucia-torres@gmail.com`, the Subject of sample
`case_15`), with the same times as `case_15` but a different request:

| field | value |
| --- | --- |
| case_id | `eval_not_deletion_01` |
| requested_at | 2026-08-21T12:00:00Z |
| reported_at | 2026-08-22T12:00:00Z (workflow Claim: COMPLETE) |
| audit_at | 2026-09-15T12:00:00Z |
| request_text | "Could you send me a copy of the invoice for my last order and update the phone number on my profile? Please keep my account open; I am not asking you to delete anything." |

The customer asks for an invoice and a phone change and says to keep the account. The other
fields look like a deletion case: the workflow claims COMPLETE, and the evidence still shows
an active data flow `data_flow_9846` (`evidence_01`) for this Subject.

## Expected answer

`NOT_APPLICABLE` with `steps_json=[]`. No deletion was authorized, so nothing is audited.

If the request were audited as a deletion request, the answer would be `INCOMPLETE` with the
sample's `REPORT_ACTIVE_DATA_FLOW` / `DISABLE_DATA_FLOW` steps.

## Where the decision comes from

The decision is a fixed, hand-written cache entry,
`code/llm_cache/request_decisions/f7a84753423750a1e1dae6aade3439b35ac1ed6079f3a8a38ca3ff8077741178.json`
(the SHA-256 of the request text). It has `deletion_requested: false` and `model: fixture`.
The case therefore scores the same in offline mode, with no API key.
`code/classify_requests.py` treats the text as already decided and never sends it to the model.
