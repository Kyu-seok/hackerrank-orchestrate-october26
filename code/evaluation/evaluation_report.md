# Evaluation report

This report covers the deletion-audit pipeline as it produced the submitted `output.csv`. Token use and
cost are in [`usage_report.md`](usage_report.md).

## How it was measured

- **Scorer:** `code/evaluation/main.py`. It compares predicted rows with labeled answers on these measures:
  - status accuracy;
  - step precision, recall and F1 (steps compared as a multiset of `(phase, operation, system_id,
    resource_id, state, evidence_id)`);
  - positional field accuracy (gold and predicted steps aligned by index, each field scored);
  - sequence accuracy (the whole ordered `steps_json` matches exactly, and so does the status);
  - output-contract and ordering checks.
- **Labeled data:** the 32 public samples (`dataset/sample_deletion_requests.csv` scored against
  `dataset/sample_output.csv`) and our own evaluation cases under `code/evaluation/cases/`. The
  518 evaluation requests have no labels, so they get only the contract checks.
- **No model calls:** every run below is offline (`DELETION_AUDIT_OFFLINE=1`, `--strict`). LLM results
  come from the committed cache in `code/llm_cache/`, and `--strict` fails on any cache miss.

Commands:

```bash
DELETION_AUDIT_OFFLINE=1 python3 code/main.py --strict
DELETION_AUDIT_OFFLINE=1 python3 code/main.py --strict --requests dataset/sample_deletion_requests.csv --output /tmp/samples.csv
python3 code/evaluation/main.py /tmp/samples.csv --verbose --markdown /tmp/samples.md
python3 -m unittest discover -s code/evaluation -p "test_*.py"
```

## Status

| Check | Result |
| --- | --- |
| Final full run (`python3 code/main.py --strict`, offline) | 518 rows, sorted by `case_id`, header `case_id,deletion_status,steps_json` |
| Rows with scorer contract or ordering errors (all 518) | **0** |
| Status distribution (518) | INCOMPLETE 354, COMPLETE 154, NOT_APPLICABLE 10 |
| Steps written (518) | 3,162 (FINDING 722, REMEDIATION 722, VERIFICATION 1,718) |
| Sample status accuracy (32) | **100.0%** |
| Sample sequence accuracy (32) | **65.6%** (21 of 32 exact) |
| Sample step F1 (32) | **95.5%** |
| Our evaluation cases (7) | **7 of 7 exact**, 28 of 28 steps |
| Unit and end-to-end tests | all pass (`python3 -m unittest discover -s code/evaluation -p "test_*.py"`) |

The 10 `NOT_APPLICABLE` rows are `case_533` to `case_542`. Claude Haiku 5.5 classified their request texts
as asking only for something else: a phone or email change, a data download, an invoice copy, and so on.

## Sample accuracy (32 labeled cases)

Output of `python3 code/evaluation/main.py <samples.csv> --markdown`:

| Metric | Value |
| --- | --- |
| Cases scored | 32 |
| Missing predictions | 0 |
| Status accuracy | 100.0% |
| Sequence accuracy (exact steps_json) | 65.6% |
| Step precision | 97.8% (180/184) |
| Step recall | 93.3% (180/193) |
| Step F1 | 95.5% |
| Field accuracy (positional, all fields) | 90.9% |
| Field accuracy: `phase` | 95.3% |
| Field accuracy: `operation` | 88.1% |
| Field accuracy: `system_id` | 89.6% |
| Field accuracy: `resource_id` | 89.1% |
| Field accuracy: `state` | 88.6% |
| Field accuracy: `evidence_id` | 94.8% |
| Rows with schema errors | 0 |

Status confusion (gold -> predicted):

- COMPLETE -> COMPLETE: 10
- INCOMPLETE -> INCOMPLETE: 22

The samples include no `NOT_APPLICABLE` case. Our own case `not_a_deletion_request` covers that path.

Positional field accuracy is lower than step precision for a structural reason. When one expected
step is missing, every later step in that case shifts by one position, and the shifted steps score
as wrong even though they are correct.

## Our evaluation cases

Each folder under `code/evaluation/cases/` contains:

- `requests.csv`, our own request in the input format, built on real participant data;
- `answers.csv`, a hand-derived answer key in scorer format;
- `README.md`, which traces the expected answer back to the evidence.

The test `EvaluationCases.test_every_case_scores_perfectly` runs each case through the CLI and the scorer.

| Case | Request | Expected status | What it tests | Steps matched | Status | Sequence |
| --- | --- | --- | --- | --- | --- | --- |
| `email_changed_before_request` | `eval_history_01` | INCOMPLETE | The request uses the current email, but the only surviving account row (`account_8681`, `evidence_94`) carries the email from before the change. Only `user_audit_log.csv` history connects them. | 3/3 | 100% | 100% |
| `evidence_after_cutoff` | `eval_cutoff_01` | COMPLETE | A failover replica still holds the account one hour after `audit_at` (`evidence_54`). It must be ignored, and the answer must cite the latest snapshot before the cutoff (`evidence_10`). | 1/1 | 100% | 100% |
| `not_a_deletion_request` | `eval_not_deletion_01` | NOT_APPLICABLE | The customer asks for an invoice and a phone change and says to keep the account. The other fields look like a deletion case with an active data flow. The decision comes from a fixed cache entry. | 0/0 (`[]`) | 100% | 100% |
| `resource_linked_by_catalog` | `eval_link_01` | INCOMPLETE | A link-identity activity attributes `account_5762`. An extracted screenshot (`evidence_04`, 2026-09-26) shows the account and `support_9538` still live after an older 404. | 6/6 | 100% | 100% |
| `retention_expired` | `eval_retention_01` | INCOMPLETE | A security audit record whose retention date in an extracted PDF (`evidence_55`) has passed falls back from RETAIN to DELETE. The other five records stay verified present. | 8/8 | 100% | 100% |
| `sync_recreated_deleted_data` | `eval_sync_01` | INCOMPLETE | A delete Claim of SUCCESS, an active connector `data_flow_1121` that repopulated `search_4801`, and a later readback showing the search entry is still present. This is the headline failure. | 8/8 | 100% | 100% |
| `tombstone_in_screenshot` | `eval_tombstone_01` | COMPLETE | An Account tombstone known only from a screenshot with no direct identifiers (`evidence_42`), named through the catalog alias `tombstone_17 (user_17)`, is verified as redacted. | 2/2 | 100% | 100% |

## Known remaining misses (samples)

11 of the 32 samples do not match exactly. All 11 have the correct status. Together they miss 13 gold
steps and add 4 extra steps.

| Sample(s) | Difference | Why |
| --- | --- | --- |
| case_03, case_21, case_25, case_26, case_27, case_28 (COMPLETE) | Each misses one `VERIFY_RECORD_ANONYMIZED` for an analytics profile (`analytics_9406`, `5335`, `1895`, `4566`, `4574`, `6077`). | These profiles are already anonymized and carry no identifier. The only link to the case is a deletion-worker ANONYMIZE activity near `reported_at`, and several requests share that time window. The pipeline attributes such a profile only when exactly one Subject's case could own it. A looser rule would also attribute profiles to the wrong cases. |
| case_04 (COMPLETE) | Misses `VERIFY_RECORD_ABSENT account_004` citing `evidence_54`. | `account_004` appears nowhere in the participant data: no activity, no evidence row. It can only be guessed from the naming pattern `user_04` to `account_004`, and we do not hard-code such patterns. |
| case_18, case_20 (INCOMPLETE) | Each misses one `VERIFY_RECORD_PRESENT` (`audit_record_6645`, `audit_record_5569`). | These ids appear only in `sample_output.csv` and in no participant evidence or activity, so they cannot be derived. |
| case_07 (INCOMPLETE) | `support_001` is reported as exposed PII with REDACT. Gold reports it as a remaining record with DELETE (3 steps differ). | The support record is known only from the PDF `evidence_58`. The cached Sonnet extraction put `resource_id=support_001` on a `support_ticket` record that carries an order reference, which reads as shared order context, so rule_05 applies (REDACT). The attachment row itself came out with no resource id. Gold treats it as a Subject-only support attachment (rule_06, DELETE). |
| case_23 (INCOMPLETE) | Verifies `account_7015` absent where gold has `account_410`. | Neither account has an identifier in the evidence. Both are tied to cases only by deletion-worker activity timing, and the time window holds more than one request, so the joint assignment picks the wrong account. |

## Known limitations on the full run

- `case_61` is `COMPLETE` with no steps. The Subject is `user_07`, whose February request has no
  Resource with evidence inside its `[requested_at, audit_at]` window. The row passes the contract
  checks, but it cites no evidence. The answer key may expect the account to be verified absent.
- The classification decided the `NOT_APPLICABLE` rows. We checked that it matches every labeled
  sample, but we have no labels for the 518 requests.
- The deletion-request decision and the PDF/image readings are the only model outputs (ADR 0001).
  Everything else is deterministic: a rerun from the cache reproduces `output.csv` byte for byte.

## Deviations from the spec (issue #1)

These decisions follow the labeled samples where they contradict the spec's stories.

1. **Citation uses the file's manifest time.** An evidence file is citable only when its manifest
   `captured_at` is at or before `audit_at`. Each record's own time still counts for discovery and
   state. This differs from story 14, which judges each snapshot by its own capture time; the samples
   never cite a file captured after the cutoff, even for an inner snapshot taken before it.
2. **Absence by omission.** Absence can be proven by omission from a snapshot whose scope covers the
   system. Omission ranks below any direct observation, even a later one (stories 16, 19 and 20): the
   samples treat activity-only accounts as absent, but a row seen present elsewhere stays present.
3. **Attribution time window.** Identifier and link-identity attribution only counts observations
   inside `[requested_at, audit_at]` (stories 12 and 33). Without the lower bound, the samples
   over-attribute `object_19`, `account_6523` and `tombstone_17`.
4. **Treatment follows the deletion worker's action.** Where the deletion worker acted on a Resource,
   the type of that action selects the treatment. This matches all 32 samples, while a fixed category
   mapping does not (story 21: `analytics_9914` is deleted, `support_002` is deleted).
5. **Workflow-attributed Resources.** Resources with no identifier (deleted accounts, anonymized
   analytics) are tied to a case through the deletion-worker activities near `reported_at`. When cases
   tie, the pipeline prefers the action whose result agrees with `reported_status`. This is a
   tie-break only, never proof of state.
6. **Check activities are not loaded as Observations.** In the samples they are never inside the case
   window and never cited (story 17).
7. **Account tombstone.** The pipeline does not derive one from `user_identities.csv` for every
   deleted account (stories 31 and 32). It uses only explicit tombstone or registry records, as the
   samples do.
8. **Deletion-verification requests count as deletion requests.** A request to verify or confirm
   one's own deletion counts as a deletion request (samples `case_27` and `case_28`). The
   classification prompt says so explicitly.
9. **More evaluation cases.** The spec asked for four evaluation cases; there are seven.
10. **Report location.** The reports are in `code/evaluation/` rather than `evaluation/`
    (AGENTS.md §6.8), because the README is newer and its zip command only bundles `README.md` and `code/`.

## Failures found and improvements made

Each change was built test-first against the scorer on the samples. Sample scores after each ticket
merged:

| Step | Change | Status acc. | Step F1 | Sequence |
| --- | --- | --- | --- | --- |
| #2 tracer bullet | Pipeline CLI, evidence loaders, account records only | 40.6% | 15.0% (recall 8.8%) | — |
| #4 always-delete categories | Search, export, marketing and cache entries; Replica rows reported under the copied system | 68.8% | 46.4% (recall 31.6%) | — |
| #5 Data flows and restore risks | Subject-linked connectors disabled and backups blocked, never deleted | 81.2% | 63.4% | — |
| #6 conditional rules (merged on #5) | Support REDACT, attachments DELETE, analytics ANONYMIZE; a rule whose condition no longer holds yields a verification only | 81.2% | 74.3% (P 95.9%, R 60.6%) | — |
| #3 identity history + #7 LLM gateway | Historical emails, phones and hashes; link-identity attribution; workflow tie-break; cached LLM gateway | 93.8% | 87.4% | — |
| PDF/image extraction run (15 Sonnet 5.5 calls) | Screenshots and PDFs become Observations | 96.9% | 87.2% | 18.8% |
| #8 retention, legal hold, tombstones | RETAIN while the retention or hold period runs, else DELETE; tombstone REDACT; PDF/image records named through catalog aliases | 100% | 95.5% (recall 79.3% to 93.3%) | 65.6% |
| #9 + classification run (17 Haiku 5.5 calls) | NOT_APPLICABLE for non-deletion requests; prompt fix for "verify my deletion" | 100% | 95.5% | 65.6% |

"—" means the sequence accuracy was not recorded at that step. Failures found along the way and how
each was fixed:

- **Delete Claims are unreliable in both directions.** A delete reported as SUCCESS can leave the
  record present (`search_1007`, `account_5334`), and one reported as FAILED can leave it gone
  (`account_5037`). Action activities are therefore Claims only; state comes from observations.
- **Ghost copies in replicas.** A row in a failover, read or reporting replica now makes the Resource
  present under the system it copies (`case_05`, `case_16`).
- **Latest observation versus omission.** A later snapshot that merely omits a row no longer
  overrides an earlier direct observation of it (`case_05`, `case_24`).
- **Over-attribution.** Without a lower time bound, evidence from a Subject's other, earlier request
  leaked into a case. The `[requested_at, audit_at]` window fixed `case_07` and `case_17`.
- **Old identifiers.** Ghost copies under a pre-change email or email hash (`case_10`, `case_12`,
  `case_29`, `case_30`) are found through `user_audit_log.csv` history.
- **Tied workflow accounts.** Requests that share a `reported_at` competed for the same deleted
  account. The `reported_status` tie-break fixed `case_31` and `case_32`.
- **PDF/image evidence.** Before extraction, `support_001` (`evidence_58`) and the screenshot-only
  facts were invisible. Extraction raised status accuracy to 96.9%. It also showed that our own
  answer key for `eval_link_01` was wrong: the 2026-09-26 screenshot shows the account still live
  after a 404, so the key was corrected to INCOMPLETE.
- **Retention and tombstones.** Retained audit records and the identity tombstone were missing until
  #8. Adding them took sample sequence accuracy from 18.8% to 65.6%.
- **Classification misread.** The first Haiku run marked `case_27` and `case_28` ("verify my
  deletion") as not deletion requests. The prompt was fixed, the decisions were cleared and every
  text was reclassified. The discarded run's tokens are listed in `usage_report.md`.
- **Test isolation.** Two "no API key" CLI tests read a key from the repo-root `.env` and reached the
  real API. The gateway now honours `DELETION_AUDIT_DOTENV`, and those tests point it at a missing file.
