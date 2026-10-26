"""Ghost Data deletion-audit pipeline.

Usage (from the repo root):
    python3 code/main.py [--requests REQUESTS_CSV] [--output OUTPUT_CSV]

Defaults: dataset/deletion_requests.csv -> output.csv at the repo root.
The dataset is always read from the repo root's dataset/ folder.

No model is called here: LLM results come from code/llm_cache/. A request
whose text has no cached deletion-request classification is audited as a
deletion request and named in a warning; --strict fails instead. Fill the
cache once with: python3 code/classify_requests.py (ANTHROPIC_API_KEY set).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deletion_audit.dataset import DEFAULT_OUTPUT, DEFAULT_REQUESTS  # noqa: E402
from deletion_audit.pipeline import ClassificationMissing, run  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit deletion requests and write output.csv")
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS,
                        help="request CSV (default: dataset/deletion_requests.csv)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="answer CSV to write (default: output.csv at the repo root)")
    parser.add_argument("--strict", action="store_true",
                        help="fail if any request has no cached deletion-request classification")
    args = parser.parse_args(argv)
    try:
        rows = run(args.requests, args.output, strict=args.strict)
    except ClassificationMissing as err:
        print("error: %s" % err, file=sys.stderr)
        return 1
    print("wrote %d rows to %s" % (len(rows), args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
