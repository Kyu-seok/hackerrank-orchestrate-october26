# Deterministic core, LLM only at the unstructured edges

Scoring rewards exact steps, cited evidence IDs and step order, so identity resolution, resource state reconstruction, rule application, step ordering and status decisions are plain Python and give the same output on every run. An LLM is used only where the input is unstructured: reading `request_text` to decide whether deletion was requested, and extracting facts from PDF and image evidence. Its results are cached so reruns are repeatable and the token usage report stays small.

## Considered Options

- **LLM-first agent** that reads each case's evidence and writes `steps_json`, with code only validating the format: rejected because it is non-deterministic and expensive across 518 cases.
- **No LLM at all** (rules and OCR only): rejected because multilingual request text and screenshot/PDF evidence are hard to interpret reliably with rules.
