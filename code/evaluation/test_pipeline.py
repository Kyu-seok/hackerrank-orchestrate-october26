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


if __name__ == "__main__":
    unittest.main()
