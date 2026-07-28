"""
scripts/extensions.py - the company extensions contract, parsed and surfaced (ADR-009).

A working project may carry `docs/team-extensions.md` (template:
`docs/templates/team-extensions.md`): standing instructions, close actions, an analyser
registry (a fenced ```json block) and named integrations. The engage step-0 probe runs
`show` so the open surfaces the contract; reviewers consult the registry for lens routing.

SECURITY DESIGN (the reason this script is deliberately dumb):
- This script NEVER executes a registry command. Tool presence is checked with
  `shutil.which()` on the probe binary name only - no subprocess, ever. A model-writable
  file that an allow-listed script executed would be a guard bypass; existence checks are
  side-effect-free.
- Registry commands must be plain argv: any shell metacharacter (; | & $ ` > <) REFUSES the
  entry at validation, so a command smuggled into the contract cannot chain anything even
  when the session later runs it (the exec guard still applies to the session's invocation
  as normal - plain binaries free, interpreter-wrapped commands need the human-curated
  CST_COMPANY_ALLOW prefixes from protected settings).
- Extensions are ADDITIVE ONLY. Nothing parsed here can waive a gate; the operating guide
  binds Morgan to that rule, and this parser carries no mechanism to express a waiver.

Usage (consent-free team tooling):
  python -m scripts.extensions show   [--file PATH]   # summary for the open probe
  python -m scripts.extensions check  [--file PATH]   # registry tools: found / missing
Default file: $CLAUDE_PROJECT_DIR/docs/team-extensions.md (silent no-op exit 0 if absent -
projects without extensions stay zero-cost).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

_SECTIONS = ("Standing instructions", "Close actions", "Analyser registry", "Integrations")
_META_RE = re.compile(r"[;|&$`<>]")
_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def default_file() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return (Path(root) if root else Path.cwd()) / "docs" / "team-extensions.md"


def split_sections(text: str) -> dict[str, str]:
    """Body text per recognised H2 heading (exact-match, template contract)."""
    out: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                out[current] = "\n".join(lines).strip()
            heading = line[3:].strip()
            current = heading if heading in _SECTIONS else None
            lines = []
        elif current:
            lines.append(line)
    if current:
        out[current] = "\n".join(lines).strip()
    return out


def parse_registry(section: str) -> tuple[list[dict], list[str]]:
    """(valid analyser entries, problems). Refuses unsafe commands; never executes."""
    m = _JSON_FENCE_RE.search(section or "")
    if not m:
        return [], [] if not (section or "").strip() else ["Analyser registry: no ```json block found"]
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        return [], [f"Analyser registry: invalid JSON ({exc})"]
    entries = data.get("analysers")
    if not isinstance(entries, list):
        return [], ["Analyser registry: 'analysers' must be a list"]
    valid: list[dict] = []
    problems: list[str] = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not e.get("name") or not e.get("command"):
            problems.append(f"analysers[{i}]: 'name' and 'command' are required")
            continue
        if _META_RE.search(str(e["command"])):
            problems.append(
                f"analysers[{i}] ({e['name']}): command contains shell metacharacters - "
                "REFUSED (plain argv only, ADR-009)"
            )
            continue
        e.setdefault("probe", str(e["command"]).split()[0])
        e.setdefault("lenses", [])
        e.setdefault("replaces", [])
        e.setdefault("output", "text")
        valid.append(e)
    return valid, problems


def load(file: Path) -> dict:
    text = file.read_text(encoding="utf-8", errors="replace")
    sections = split_sections(text)
    registry, problems = parse_registry(sections.get("Analyser registry", ""))
    return {"sections": sections, "registry": registry, "problems": problems}


def _cmd_show(args: argparse.Namespace) -> int:
    file = args.file or default_file()
    if not file.is_file():
        return 0  # no extensions - zero-cost silence
    data = load(file)
    print(f"TEAM-EXTENSIONS: {file}")
    for name in ("Standing instructions", "Close actions", "Integrations"):
        body = data["sections"].get(name)
        if body:
            print(f"--- {name} ---")
            print(body)
    if data["registry"]:
        print("--- Analyser registry ---")
        for e in data["registry"]:
            found = shutil.which(e["probe"]) is not None
            mark = "found" if found else "MISSING on PATH"
            rep = f" replaces {','.join(e['replaces'])}" if e["replaces"] else ""
            print(f"- {e['name']} [{mark}] lenses={','.join(e['lenses']) or '-'}{rep} :: {e['command']}")
    for p in data["problems"]:
        print(f"EXTENSIONS-INVALID: {p}")
    print(
        "(Extensions are ADDITIVE only - they never waive a disclaimer, gate, guard or the "
        "code chain. Close actions are OFFERS at the gate.)"
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    file = args.file or default_file()
    if not file.is_file():
        print("no team-extensions file - nothing to check")
        return 0
    data = load(file)
    missing = 0
    for e in data["registry"]:
        found = shutil.which(e["probe"]) is not None
        print(f"{e['name']:24} {'found' if found else 'MISSING'}  ({e['probe']})")
        missing += 0 if found else 1
    for p in data["problems"]:
        print(f"EXTENSIONS-INVALID: {p}")
        missing += 1
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(prog="python -m scripts.extensions")
    ap.add_argument("--file", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").set_defaults(fn=_cmd_show)
    sub.add_parser("check").set_defaults(fn=_cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
