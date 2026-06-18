#!/usr/bin/env python3
"""
PreToolUse guard: keep agents structurally downstream of masking.

Blocks Read/Bash tool calls that target raw, un-masked data (anything under a `data/raw/`
or `/raw/` path). Agents must consume masked output (data/masked/, via scripts/ingest.py)
or synthetic data — never raw records, which would egress to the model provider as prompt
context (CLAUDE.md §5).

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr is fed back to the
model); exit 0 to allow. Fails open on any parse error so it can never brick a session.
"""
import json
import sys

RAW_MARKERS = ("data/raw/", "/raw/")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail open

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool == "Read":
        target = tool_input.get("file_path", "") or ""
    elif tool == "Bash":
        target = tool_input.get("command", "") or ""
    else:
        sys.exit(0)

    if any(marker in target for marker in RAW_MARKERS):
        sys.stderr.write(
            "Blocked: this targets raw, un-masked data (data/raw/). Agents must not read raw "
            "records into context (CLAUDE.md §5) — they would be sent to the model provider. "
            "Run `python -m scripts.ingest` to produce masked data under data/masked/, then use "
            "that (or synthetic data from scripts/gen_synthetic.py) instead.\n"
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
