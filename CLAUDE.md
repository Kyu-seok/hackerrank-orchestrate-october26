# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Claude Code notes (supplements AGENTS.md)

- **Logging is mandatory.** Every turn appends to `log.txt` at the repo root (AGENTS.md §2, §5). In entries use `tool=Claude Code` and the exact runtime model ID from the session (e.g. `claude-opus-5-5[1m]`), never a family name. Sub-agents append to the same file with `parent_agent=` set.
- **Current state:** `code/main.py [--requests CSV] [--output CSV]` runs the pipeline in `code/deletion_audit/` (evidence loaders in `evidence/`, category registry in `categories.py`). Tests: `python3 -m unittest discover -s code/evaluation -p "test_*.py"` (end-to-end: CLI + scorer on the samples and on each `code/evaluation/cases/*/` request/answer pair; the full-run test rewrites the root `output.csv`).
- **Scorer:** `python3 code/evaluation/main.py PRED_CSV [--gold GOLD_CSV] [--verbose] [--markdown OUT_MD]` scores predictions against `dataset/sample_output.csv` (status, step P/R/F1, positional field accuracy, exact sequence, schema/order checks). Standard library only, Python 3.9+.
- **Run:** `python3 code/main.py` from the repo root. It must read `dataset/` and write `output.csv` to the **repo root**, not `dataset/output.csv`, which is the blank template. Resolve paths relative to the repo root.
- **Ground truth for development:** `dataset/sample_deletion_requests.csv` (32 cases) and `dataset/sample_output.csv` are the only labeled data. Evaluate against them in `code/evaluation/`. Nothing outside `dataset/` may be used for predictions.
- **Where the reports go:** put them at `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md`. AGENTS.md §6.8 says `evaluation/`, but the README is newer and wins, and the zip command only bundles `README.md` and `code/`. The code judge ignores `.csv/.json/.jsonl/.sql/.log` files, so metrics, custom cases, and prompts must live in `.md` or source files.
- **Step ordering within a phase** (from `problem_statement.md`): follow the order of operations in the AGENTS.md §6.4 tables, then sort by `system_id` and `resource_id` ascending. Remediation therefore always runs `DISABLE_DATA_FLOW` → `BLOCK_RESTORE` → `DELETE_RECORD` → `REDACT_RECORD` → `ANONYMIZE_RECORD`.
- **Serialization:** `sample_output.csv` writes `steps_json` as compact JSON with keys sorted alphabetically. `json.dumps(steps, sort_keys=True, separators=(",", ":"))` matches it and keeps runs deterministic.
- **Evidence:** `.sql` files under `dataset/evidence/databases/` are SQLite dumps. Load them with `sqlite3` or Python's `sqlite3` to compare replicas. Use the PDFs and images under `documents/` and `images/` for their contents (extract text or OCR); don't expect them to state a verdict. Discard any evidence or activity captured after the case's `audit_at`.
- AGENTS.md §7 (dataset generation, `generator/validate_*.py`) applies only to organizers. The `generator/` directory isn't in this repo.
- **Packaging:** `zip -r code.zip README.md code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store"`. Don't nest archives or include `dataset/`.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `Kyu-seok/hackerrank-orchestrate-october26` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
