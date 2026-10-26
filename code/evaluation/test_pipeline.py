"""End-to-end tests for the deletion-audit pipeline (test seam: CLI + scorer).

Run from the repo root:

    python3 -m unittest discover -s code/evaluation -p "test_*.py"

Each test runs ``code/main.py`` on a request file, then scores the written
answers with the scorer in ``code/evaluation/main.py``. Nothing here looks at
the pipeline's internal data structures.
"""

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
CASES = Path(__file__).resolve().parent / "cases"
PIPELINE = REPO_ROOT / "code" / "main.py"

_spec = importlib.util.spec_from_file_location("scorer", Path(__file__).resolve().parent / "main.py")
scorer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scorer)


def run_pipeline(requests=None, output=None):
    """Run the CLI and return the written answers as {case_id: (status, steps)}."""
    cmd = [sys.executable, str(PIPELINE)]
    if requests is not None:
        cmd += ["--requests", str(requests)]
    if output is not None:
        cmd += ["--output", str(output)]
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))
    return output


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def steps_for(rows, case_id):
    for row in rows:
        if row["case_id"] == case_id:
            return row["deletion_status"], json.loads(row["steps_json"])
    raise KeyError(case_id)


class SampleRun(unittest.TestCase):
    """The pipeline run once on the 32 labeled samples."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "samples.csv"
        run_pipeline(DATASET / "sample_deletion_requests.csv", cls.out)
        cls.rows = read_rows(cls.out)
        cls.result = scorer.score(scorer.load_answers(DATASET / "sample_output.csv"),
                                  scorer.load_answers(cls.out))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_one_row_per_case_sorted_by_case_id(self):
        ids = [r["case_id"] for r in self.rows]
        self.assertEqual(len(ids), 32)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(self.result["missing_cases"], [])

    def test_no_contract_or_ordering_errors(self):
        self.assertEqual(self.result["schema_errors"], {})

    def test_deleted_account_proven_absent_by_omission_is_complete(self):
        # account_001 never appears in evidence_54's primary or failover tables.
        status, steps = steps_for(self.rows, "case_01")
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(steps, [{"step_no": 1, "phase": "VERIFICATION", "system_id": "account_service",
                                  "resource_id": "account_001", "operation": "VERIFY_RECORD_ABSENT",
                                  "state": "ABSENT", "evidence_id": "evidence_54"}])

    def test_account_surviving_in_failover_replica_is_remediated(self):
        # A delete Claim says SUCCESS, but evidence_54's failover replica still holds the row.
        status, steps = steps_for(self.rows, "case_05")
        self.assertEqual(status, "INCOMPLETE")
        expected = [("FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_54"),
                    ("REMEDIATION", "DELETE_RECORD", "ABSENT", ""),
                    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "")]
        self.assertEqual([(s["phase"], s["operation"], s["state"], s["evidence_id"]) for s in steps], expected)
        self.assertEqual({(s["system_id"], s["resource_id"]) for s in steps},
                         {("account_service", "account_005")})

    def test_account_steps_match_labeled_samples(self):
        """Account steps (phase, operation, resource) match the sample answers.

        Known gaps, owned by later tickets: case_04's account_004 appears nowhere
        in participant data; case_10/29/30 request with a historical email
        (identity history); case_23/31/32 share a workflow slot with other cases
        whose accounts carry no identifiers, so the pick is a guess.
        """
        known_gaps = {"case_04", "case_10", "case_23", "case_29", "case_30", "case_31", "case_32"}
        self.assertEqual(sorted(set(self.mismatched_cases("account_service", ("phase", "operation", "resource_id")))
                                - known_gaps), [])

    def mismatched_cases(self, system_id, fields=("phase", "operation", "resource_id", "state", "evidence_id")):
        """Cases whose steps for ``system_id`` differ from the labeled answers.

        Steps are compared on ``fields`` only (not ``step_no``), so this measures
        the system's own step recall and precision; position in the whole
        sequence depends on the other systems too.
        """
        mismatched = []
        for row in read_rows(DATASET / "sample_output.csv"):
            case_id = row["case_id"]

            def key(steps):
                return sorted(tuple(s[f] for f in fields) for s in steps if s["system_id"] == system_id)
            if key(json.loads(row["steps_json"])) != key(steps_for(self.rows, case_id)[1]):
                mismatched.append(case_id)
        return mismatched

    def test_search_index_entry_steps_match_labeled_samples(self):
        """Every remaining search entry is reported, deleted and verified absent (rule_03).

        Known gap, owned by identity history (#3): case_29/30 entries carry only
        the Subject's old email.
        """
        known_gaps = {"case_29", "case_30"}
        self.assertEqual(sorted(set(self.mismatched_cases("search_service")) - known_gaps), [])

    def test_user_export_steps_match_labeled_samples(self):
        # export_001 (case_08) and export_7364 (case_23): DELETE FAILED Claims, still downloadable.
        self.assertEqual(self.mismatched_cases("export_service"), [])

    def test_search_entry_surviving_in_replica_reported_under_search_service(self):
        # case_16: evidence_05 holds search_1007 in customer_data_read_replica rows whose
        # origin_system is search_service; a DELETE SUCCESS Claim does not make it absent.
        status, steps = steps_for(self.rows, "case_16")
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn({"phase": "FINDING", "system_id": "search_service",
                       "resource_id": "search_1007", "operation": "REPORT_REMAINING_RECORD",
                       "state": "PRESENT", "evidence_id": "evidence_05"},
                      [{k: v for k, v in s.items() if k != "step_no"} for s in steps])


def _system_steps(steps, system_id):
    return [(s["phase"], s["operation"], s["resource_id"], s["evidence_id"])
            for s in steps if s["system_id"] == system_id]


class ConditionalRules(unittest.TestCase):
    """Rules whose condition is read from the record: support, analytics, email delivery."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "samples.csv"
        run_pipeline(DATASET / "sample_deletion_requests.csv", cls.out)
        cls.rows = read_rows(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_identifiable_analytics_profile_is_anonymized(self):
        # evidence_05 still holds analytics_4440 with the Subject's email, phone and hash.
        status, steps = steps_for(self.rows, "case_22")
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(_system_steps(steps, "analytics_platform"), [
            ("FINDING", "REPORT_EXPOSED_PII", "analytics_4440", "evidence_05"),
            ("REMEDIATION", "ANONYMIZE_RECORD", "analytics_4440", ""),
            ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "analytics_4440", "")])

    def test_identifiable_support_message_is_redacted_not_deleted(self):
        # evidence_03 handover: support_864 is a SUPPORT_MESSAGE still IDENTIFIABLE.
        status, steps = steps_for(self.rows, "case_11")
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(_system_steps(steps, "support_platform"), [
            ("FINDING", "REPORT_EXPOSED_PII", "support_864", "evidence_03"),
            ("REMEDIATION", "REDACT_RECORD", "support_864", ""),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_864", "")])

    def test_subject_only_support_attachment_is_deleted(self):
        # evidence_03 handover: support_4218 is a SUPPORT_ATTACHMENT still FOUND.
        _, steps = steps_for(self.rows, "case_13")
        self.assertEqual(_system_steps(steps, "support_platform"), [
            ("FINDING", "REPORT_REMAINING_RECORD", "support_4218", "evidence_03"),
            ("REMEDIATION", "DELETE_RECORD", "support_4218", ""),
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "support_4218", "")])

    def test_already_redacted_support_message_is_only_verified(self):
        # evidence_92 shows support_4715 with only the user_id reference left.
        status, steps = steps_for(self.rows, "case_26")
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(_system_steps(steps, "support_platform"), [
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_4715", "evidence_92")])

    def test_already_anonymized_analytics_profile_is_only_verified(self):
        # analytics_901 carries no identifier; only the case's anonymize Action activity
        # (no other request's workflow could own it) ties it to the Subject.
        status, steps = steps_for(self.rows, "case_04")
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(_system_steps(steps, "analytics_platform"), [
            ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "analytics_901", "evidence_56")])

    def test_support_and_analytics_steps_match_labeled_samples(self):
        """Support and analytics steps match the sample answers, except known gaps.

        Owned by other tickets: case_07's support_001 exists only in a PDF
        (extraction); case_10/12/29/30 reach their records through historical
        identifiers (identity history). Not derivable without guessing: the
        anonymized analytics of case_03/21/25/26/27/28 carry no identifier and
        their anonymize activity falls in a workflow slot shared with other
        Subjects' cases.
        """
        known_gaps = {"case_07", "case_10", "case_12", "case_29", "case_30",
                      "case_03", "case_21", "case_25", "case_26", "case_27", "case_28"}
        systems = ("support_platform", "analytics_platform")
        mismatched = []
        for row in read_rows(DATASET / "sample_output.csv"):
            case_id = row["case_id"]
            want = [s for s in json.loads(row["steps_json"]) if s["system_id"] in systems]
            got = [s for s in steps_for(self.rows, case_id)[1] if s["system_id"] in systems]
            strip = lambda ss: [{k: v for k, v in s.items() if k != "step_no"} for s in ss]  # noqa: E731
            if strip(want) != strip(got):
                mismatched.append(case_id)
        self.assertEqual(sorted(set(mismatched) - known_gaps), [])


class EvaluationCases(unittest.TestCase):
    """Our own cases: each folder under cases/ holds requests.csv and answers.csv."""

    def test_every_case_scores_perfectly(self):
        case_dirs = sorted(p for p in CASES.iterdir() if (p / "answers.csv").exists())
        self.assertTrue(case_dirs)
        for case_dir in case_dirs:
            with self.subTest(case=case_dir.name), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "pred.csv"
                run_pipeline(case_dir / "requests.csv", out)
                result = scorer.score(scorer.load_answers(case_dir / "answers.csv"), scorer.load_answers(out))
                self.assertEqual(result["schema_errors"], {})
                self.assertEqual(result["failures"], [])
                self.assertEqual(result["sequence_accuracy"], 1.0)


class FullRun(unittest.TestCase):
    """With no options the pipeline answers the full request set into the root output.csv."""

    def test_default_run_writes_root_submission(self):
        run_pipeline()
        rows = read_rows(REPO_ROOT / "output.csv")
        self.assertEqual(list(rows[0].keys()), ["case_id", "deletion_status", "steps_json"])
        expected_ids = sorted(r["case_id"] for r in read_rows(DATASET / "deletion_requests.csv"))
        self.assertEqual([r["case_id"] for r in rows], expected_ids)
        self.assertEqual(len(rows), 518)
        for row in rows:
            self.assertEqual(scorer.schema_errors(row["deletion_status"], row["steps_json"]), [], row["case_id"])


if __name__ == "__main__":
    unittest.main()
