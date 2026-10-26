"""One-time extraction of PDF and image evidence into the LLM cache.

Usage (from the repo root, with ANTHROPIC_API_KEY in the environment or an
uncommitted .env):

    python3 code/extract_evidence.py [FILE_ID ...]

Sends every PDF/PNG in dataset/evidence_files.csv (or only the given file ids)
to Claude Sonnet 5.5 with the prompt in code/deletion_audit/prompts/
evidence_extraction.md, and stores each structured answer in code/llm_cache/.
Files already in the cache are not sent again. Normal pipeline runs
(code/main.py) then read the cached records and never call the model for them.
Every real call is appended to code/llm_cache/usage.jsonl.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deletion_audit import llm  # noqa: E402
from deletion_audit.dataset import Dataset  # noqa: E402
from deletion_audit.evidence import documents  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract PDF/image evidence once into the LLM cache")
    parser.add_argument("file_ids", nargs="*", help="evidence file ids (default: every PDF and image)")
    args = parser.parse_args(argv)

    dataset = Dataset()
    wanted = set(args.file_ids)
    targets = [(fid, dataset.path(row["file_path"])) for fid, row in sorted(dataset.manifest.items())
               if documents.is_document(row["file_path"]) and (not wanted or fid in wanted)]
    unknown = wanted - {fid for fid, _ in targets}
    if unknown:
        print("error: not a PDF/image evidence id: %s" % ", ".join(sorted(unknown)), file=sys.stderr)
        return 2

    gateway = llm.Gateway()
    calls_before = len(llm.read_usage(gateway.cache_dir))
    missing = []
    for file_id, path in targets:
        before = len(llm.read_usage(gateway.cache_dir))
        try:
            extraction = documents.extract(gateway, path)
        except llm.CacheMiss:
            missing.append(file_id)
            continue
        except llm.GatewayError as err:
            print("error: %s (%s): %s" % (file_id, path.name, err), file=sys.stderr)
            return 1
        how = "extracted" if len(llm.read_usage(gateway.cache_dir)) > before else "cached"
        print("%s %s: %d record(s) [%s]" % (file_id, path.name, len(extraction.get("records", [])), how))

    llm.print_calls_since(calls_before, gateway.cache_dir)
    if missing:
        print("error: %d file(s) have no cached extraction and the gateway is offline: %s. "
              "Set %s (environment or an uncommitted .env) and rerun."
              % (len(missing), ", ".join(missing), llm.API_KEY_VAR), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
