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

        Known gaps: case_04's account_004 appears nowhere in participant data;
        case_23 shares its workflow slot with three other NOT_STARTED cases but
        only three FAILED account actions exist and none carries an identifier,
        so its pick is a guess.
        """
        known_gaps = {"case_04", "case_23"}
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

        case_29/30 entries carry only the Subject's old email (identity history).
        """
        self.assertEqual(self.mismatched_cases("search_service"), [])

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

        case_29/30 request with a historical email and their connectors select that
        old email (identity history).
        """
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
        self.assertEqual(mismatched, [])

    def test_security_audit_record_within_retention_is_verified_present(self):
        # evidence_03 handover (10-01T12:00 = audit_at): audit_record_9394 FOUND for user_32,
        # retained under rule_12, so it is only verified present, never deleted.
        self.assertEqual(self.system_steps("case_11", "security_service"), [
            ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT", "audit_record_9394", "")])

    def test_retained_audit_record_in_complete_case_cites_its_evidence(self):
        # evidence_92 service export holds audit_record_3737 (subject user_21, retention 2031+).
        self.assertEqual(steps_for(self.rows, "case_21")[0], "COMPLETE")
        self.assertEqual(self.system_steps("case_21", "security_service"), [
            ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT", "audit_record_3737", "evidence_92")])

    def test_security_audit_steps_match_labeled_samples(self):
        """Every sample's security_service steps match the answers exactly.

        Not derivable: audit_record_6645 (case_18) and audit_record_5569 (case_20)
        appear nowhere in participant data.
        """
        known_gaps = {"case_18", "case_20"}
        self.assertEqual(sorted(set(self.mismatched_cases("security_service")) - known_gaps), [])

    def test_account_tombstone_with_identifiers_is_redacted_and_verified(self):
        # evidence_51: tombstone_9178 (user_542) still carries name, email, phone and hash while
        # audit_record_7068 is retained, so the tombstone keeps only the user_id (rule_15).
        status, steps = steps_for(self.rows, "case_32")
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(self.system_steps("case_32", "identity_service"), [
            ("FINDING", "REPORT_EXPOSED_PII", "PRESENT", "tombstone_9178", "evidence_51"),
            ("REMEDIATION", "REDACT_RECORD", "REDACTED", "tombstone_9178", ""),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED", "tombstone_9178", "")])

    def test_identity_steps_match_labeled_samples(self):
        # case_31: tombstone_440 already redacted (evidence_51) -> verified only.
        self.assertEqual(self.mismatched_cases("identity_service"), [])


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

        Owned by another ticket: case_07's support_001 exists only in a PDF
        (extraction). case_10/12/29/30 reach their records through historical
        identifiers (identity history). Not derivable without guessing: the
        anonymized analytics of case_03/21/25/26/27/28 carry no identifier and
        their anonymize activity falls in a workflow slot shared with other
        Subjects' cases.
        """
        known_gaps = {"case_07",
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

    # Answer-key steps a not-yet-merged ticket owns: {case folder: {(phase, operation,
    # system_id, resource_id, state, evidence_id)}}. The case must miss exactly these and
    # nothing else; delete the entry when the owning ticket lands (the test then fails).
    PENDING = {}

    def assert_case_scores_perfectly(self, case_dir):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pred.csv"
            run_pipeline(case_dir / "requests.csv", out)
            result = scorer.score(scorer.load_answers(case_dir / "answers.csv"), scorer.load_answers(out))
            self.assertEqual(result["schema_errors"], {})
            pending = self.PENDING.get(case_dir.name)
            if pending is None:
                self.assertEqual(result["failures"], [])
                self.assertEqual(result["sequence_accuracy"], 1.0)
                return
            self.assertEqual(len(result["failures"]), 1)
            failure = result["failures"][0]
            self.assertEqual(failure["gold_status"], failure["pred_status"])
            self.assertEqual(failure["extra"], [])
            self.assertEqual(set(failure["missing"]), pending)

    def test_every_case_scores_perfectly(self):
        case_dirs = sorted(p for p in CASES.iterdir() if (p / "answers.csv").exists())
        self.assertTrue(case_dirs)
        for case_dir in case_dirs:
            with self.subTest(case=case_dir.name):
                self.assert_case_scores_perfectly(case_dir)

    def test_ghost_under_old_email_found_from_current_email(self):
        # Requested with the current email; only the pre-change email finds the surviving account.
        self.assert_case_scores_perfectly(CASES / "email_changed_before_request")

    def test_resource_linked_by_catalog_activity_is_attributed(self):
        # A link-identity activity and the evidence_04 screenshot tie account_5762 to the Subject;
        # the screenshot (2026-09-26) shows it still live after an older 404.
        self.assert_case_scores_perfectly(CASES / "resource_linked_by_catalog")

    def test_security_audit_record_past_its_retention_period_is_deleted(self):
        # evidence_55 (extracted PDF) keeps audit_record_003 until 2027-08-25; audited 2027-09-01.
        self.assert_case_scores_perfectly(CASES / "retention_expired")

    def test_tombstone_known_only_from_a_screenshot_and_its_catalog_alias_is_verified_redacted(self):
        # evidence_42 shows user_17's retained reference with linked records and no direct
        # identifiers; activity_4011 names it tombstone_17 (alias user_17).
        self.assert_case_scores_perfectly(CASES / "tombstone_in_screenshot")

    def test_retained_audit_record_survives_a_sync_recreation_case(self):
        # audit_record_7301 (evidence_01 rows=1, user_14) is verified present next to the remediation.
        self.assert_case_scores_perfectly(CASES / "sync_recreated_deleted_data")

    def test_request_that_does_not_ask_for_deletion_is_not_applicable(self):
        # The Subject has an active data flow (sample case_15), but asks for an invoice and a
        # phone change; the committed classification cache entry says no deletion was requested.
        self.assert_case_scores_perfectly(CASES / "not_a_deletion_request")


class AuditCutoffCitations(unittest.TestCase):
    """Never cite an Evidence item captured after the case's audit_at (AGENTS.md section 6.6)."""

    # The only record showing each account sits in a bundle exported after audit_at:
    # case_126's account_8819 (evidence_12, exported 2026-08-19, audit_at 2026-08-17) and
    # case_532's account_3146 (evidence_49, exported 2026-01-31, audit_at 2026-01-29T12:00).
    CASE_IDS = ("case_126", "case_532")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        requests = Path(cls.tmp.name) / "requests.csv"
        with open(DATASET / "deletion_requests.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if r["case_id"] in cls.CASE_IDS]
            fieldnames = reader.fieldnames
        with open(requests, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        cls.requests = requests
        cls.out = run_pipeline(requests, Path(cls.tmp.name) / "pred.csv")
        cls.pred = scorer.load_answers(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_record_known_only_from_a_later_export_is_never_cited(self):
        self.assertEqual(sorted(self.pred), list(self.CASE_IDS))
        self.assertEqual(scorer.cutoff_errors(self.pred, self.requests), {})
        for case_id, (status, raw) in self.pred.items():
            self.assertEqual(scorer.schema_errors(status, raw), [], case_id)

    def test_remaining_record_finding_cites_the_failed_delete_from_before_the_cutoff(self):
        status, steps = steps_for(read_rows(self.out), "case_126")
        self.assertEqual(status, "INCOMPLETE")
        finding = [s for s in steps if s["resource_id"] == "account_8819" and s["phase"] == "FINDING"]
        self.assertEqual([(s["operation"], s["evidence_id"]) for s in finding],
                         [("REPORT_REMAINING_RECORD", "activity_3114")])

    def test_complete_case_leaves_out_a_verification_it_cannot_cite(self):
        status, steps = steps_for(read_rows(self.out), "case_532")
        self.assertEqual(status, "COMPLETE")
        self.assertNotIn("account_3146", [s["resource_id"] for s in steps])


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
        self.assertEqual(scorer.cutoff_errors(scorer.load_answers(REPO_ROOT / "output.csv"),
                                              DATASET / "deletion_requests.csv"), {})


if __name__ == "__main__":
    unittest.main()
