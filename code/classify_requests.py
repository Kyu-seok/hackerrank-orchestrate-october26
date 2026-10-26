"""One-time deletion-request classification into the LLM cache.

Usage (from the repo root, with ANTHROPIC_API_KEY in the environment or an
uncommitted .env):

    python3 code/classify_requests.py [REQUEST_CSV ...]

Default request files: dataset/deletion_requests.csv,
dataset/sample_deletion_requests.csv and every
code/evaluation/cases/*/requests.csv. Every distinct request_text without a
cached decision is sent to Claude Haiku 5.5 in batches with the prompt in
code/deletion_audit/prompts/request_classification.md; each answer
(deletion_requested + short reason) is stored in
code/llm_cache/request_decisions/. Texts already decided are not sent again,
so a rerun makes no model calls. Normal pipeline runs (code/main.py) read the
decisions and never call the model. Every real call is appended to
code/llm_cache/usage.jsonl.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deletion_audit import classification, llm  # noqa: E402
from deletion_audit.dataset import DATASET_DIR, REPO_ROOT, load_requests  # noqa: E402

DEFAULT_FILES = ([DATASET_DIR / "deletion_requests.csv", DATASET_DIR / "sample_deletion_requests.csv"]
                 + sorted((REPO_ROOT / "code" / "evaluation" / "cases").glob("*/requests.csv")))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Classify request texts once into the LLM cache")
    parser.add_argument("request_files", nargs="*", type=Path,
                        help="request CSVs (default: full set, samples and evaluation cases)")
    args = parser.parse_args(argv)

    requests = [r for path in (args.request_files or DEFAULT_FILES) for r in load_requests(path)]
    texts = {r.request_text for r in requests}
    gateway = llm.Gateway()
    classifier = classification.Classifier(gateway)
    calls_before = len(llm.read_usage(gateway.cache_dir))
    try:
        written = classifier.fill(texts)
    except llm.CacheMiss:
        missing = sum(1 for t in texts if classifier.cached(t) is None)
        print("error: %d request text(s) have no cached classification and the gateway is offline. "
              "Set %s (environment or an uncommitted .env) and rerun." % (missing, llm.API_KEY_VAR),
              file=sys.stderr)
        return 1
    except llm.GatewayError as err:
        print("error: %s" % err, file=sys.stderr)
        return 1

    decisions = [classifier.cached(r.request_text) for r in requests]
    not_deletion = sorted(r.case_id for r, d in zip(requests, decisions) if not d["deletion_requested"])
    print("%d request(s), %d distinct text(s): %d new decision(s), %d already cached"
          % (len(requests), len(texts), written, len(texts) - written))
    print("not deletion requests (%d): %s" % (len(not_deletion), ", ".join(not_deletion) or "-"))
    calls = llm.read_usage(gateway.cache_dir)[calls_before:]
    if calls:
        print("model calls this run: %d, input tokens %d, output tokens %d" % (
            len(calls), sum(c["input_tokens"] for c in calls), sum(c["output_tokens"] for c in calls)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
