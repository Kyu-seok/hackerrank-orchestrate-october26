"""Ghost Data deletion-audit pipeline.

Usage (from the repo root):
    python3 code/main.py [--requests REQUESTS_CSV] [--output OUTPUT_CSV]

Defaults: dataset/deletion_requests.csv -> output.csv at the repo root.
The dataset is always read from the repo root's dataset/ folder.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deletion_audit.dataset import DEFAULT_OUTPUT, DEFAULT_REQUESTS  # noqa: E402
from deletion_audit.pipeline import run  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit deletion requests and write output.csv")
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS,
                        help="request CSV (default: dataset/deletion_requests.csv)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="answer CSV to write (default: output.csv at the repo root)")
    args = parser.parse_args(argv)
    rows = run(args.requests, args.output)
    print("wrote %d rows to %s" % (len(rows), args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
