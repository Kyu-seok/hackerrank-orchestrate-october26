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

    def system_steps(self, case_id, system_id):
        return [(s["phase"], s["operation"], s["state"], s["resource_id"], s["evidence_id"])
                for s in steps_for(self.rows, case_id)[1] if s["system_id"] == system_id]

    def test_active_data_flow_is_reported_disabled_and_verified(self):
        # evidence_01 heartbeat: data_flow_9846 for lucia-torres@ still enabled and scheduled.
        self.assertEqual(steps_for(self.rows, "case_15")[0], "INCOMPLETE")
        self.assertEqual(self.system_steps("case_15", "integration_service"), [
            ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", "data_flow_9846", "evidence_01"),
            ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED", "data_flow_9846", ""),
            ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED", "data_flow_9846", "")])

    def test_restorable_backup_is_reported_blocked_and_verified_never_deleted(self):
        # evidence_93 inventory: backup_4978 for k.appiah88@ has restore_allowed=1. evidence_06
        # repeats it at 08:57 but was exported after audit_at, so it is never cited.
        self.assertEqual(steps_for(self.rows, "case_09")[0], "INCOMPLETE")
        self.assertEqual(self.system_steps("case_09", "backup_service"), [
            ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE", "backup_4978", "evidence_93"),
            ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED", "backup_4978", ""),
            ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED", "backup_4978", "")])
        for row in self.rows:
            for s in json.loads(row["steps_json"]):
                if s["system_id"] == "backup_service":
                    self.assertNotIn(s["operation"], ("DELETE_RECORD", "VERIFY_RECORD_ABSENT"), row["case_id"])

    def test_already_stopped_flow_and_blocked_backup_cite_the_check_that_proves_it(self):
        # evidence_92 service export: data_flow_6244 enabled=false, backup_3120 restore_allowed=false.
        status, steps = steps_for(self.rows, "case_26")
        got = [(s["phase"], s["operation"], s["state"], s["resource_id"], s["evidence_id"])
               for s in steps if s["system_id"] in ("integration_service", "backup_service")]
        self.assertEqual(got, [
            ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED", "data_flow_6244", "evidence_92"),
            ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED", "backup_3120", "evidence_92")])

    def test_flow_and_backup_steps_match_labeled_samples(self):
        """Every sample's integration_service and backup_service steps match the answers exactly.

        Known gap, owned by the identity-history ticket: case_29/30 request with a
        historical email, and their connectors select that old email.
        """
        known_gaps = {"case_29", "case_30"}
        gold = read_rows(DATASET / "sample_output.csv")
        systems = ("integration_service", "backup_service")
        mismatched = []
        for row in gold:
            want = [{k: v for k, v in s.items() if k != "step_no"}
                    for s in json.loads(row["steps_json"]) if s["system_id"] in systems]
            got = [{k: v for k, v in s.items() if k != "step_no"}
                   for s in steps_for(self.rows, row["case_id"])[1] if s["system_id"] in systems]
            if want != got:
                mismatched.append(row["case_id"])
        self.assertEqual(sorted(set(mismatched) - known_gaps), [])


class EvaluationCases(unittest.TestCase):
    """Our own cases: each folder under cases/ holds requests.csv and answers.csv."""

    # Answer-key steps a not-yet-merged ticket owns: {case folder: {(phase, operation,
    # system_id, resource_id, state, evidence_id)}}. The case must miss exactly these and
    # nothing else; delete the entry when the owning ticket lands (the test then fails).
    PENDING = {
        # Retained security audit records: retention ticket (#8).
        "sync_recreated_deleted_data": {
            ("VERIFICATION", "VERIFY_RECORD_PRESENT", "security_service", "audit_record_7301", "PRESENT", "")},
    }

    def test_every_case_scores_perfectly(self):
        case_dirs = sorted(p for p in CASES.iterdir() if (p / "answers.csv").exists())
        self.assertTrue(case_dirs)
        for case_dir in case_dirs:
            with self.subTest(case=case_dir.name), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "pred.csv"
                run_pipeline(case_dir / "requests.csv", out)
                result = scorer.score(scorer.load_answers(case_dir / "answers.csv"), scorer.load_answers(out))
                self.assertEqual(result["schema_errors"], {})
                pending = self.PENDING.get(case_dir.name)
                if pending is None:
                    self.assertEqual(result["failures"], [])
                    self.assertEqual(result["sequence_accuracy"], 1.0)
                    continue
                self.assertEqual(len(result["failures"]), 1)
                failure = result["failures"][0]
                self.assertEqual(failure["gold_status"], failure["pred_status"])
                self.assertEqual(failure["extra"], [])
                self.assertEqual(set(failure["missing"]), pending)


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
