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
  python -m scripts.extensions add-tool --name N --command "..." [--lenses ...]
      [--replaces ...] [--output sarif|json|text] [--severity-map k=v,..]  # easy registration
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


_MINIMAL_CONTRACT = """# Team extensions

## Analyser registry

```json
{"analysers": []}
```
"""


def _write_registry(file: Path, entries: list[dict]) -> None:
    """Rewrite (or append) the Analyser registry's json fence, preserving everything else."""
    block = "```json\n" + json.dumps({"analysers": entries}, indent=2) + "\n```"
    text = file.read_text(encoding="utf-8") if file.is_file() else _MINIMAL_CONTRACT
    if "## Analyser registry" in text:
        head, _, rest = text.partition("## Analyser registry")
        section, nl, tail = rest.partition("\n## ")
        if _JSON_FENCE_RE.search(section):
            section = _JSON_FENCE_RE.sub(block, section, count=1)
        else:
            section = section.rstrip() + "\n\n" + block + "\n"
        text = head + "## Analyser registry" + section + (nl + tail if tail else "")
    else:
        text = text.rstrip() + "\n\n## Analyser registry\n\n" + block + "\n"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def _cmd_add_tool(args: argparse.Namespace) -> int:
    """Upsert a registry entry from flags - the easy path (EXTENDING.md step 2)."""
    if _META_RE.search(args.command):
        print(
            "REFUSED: command contains shell metacharacters (; | & $ ` < >) - plain argv "
            "only (ADR-009); chain nothing",
            file=sys.stderr,
        )
        return 2
    file = args.file or default_file()
    entries = load(file)["registry"] if file.is_file() else []
    entry = {
        "name": args.name,
        "command": args.command,
        "probe": args.probe or args.command.split()[0],
        "lenses": [s for s in (args.lenses or "").split(",") if s],
        "replaces": [s for s in (args.replaces or "").split(",") if s],
        "output": args.output,
    }
    if args.severity_map:
        entry["severity_map"] = dict(
            pair.split("=", 1) for pair in args.severity_map.split(",") if "=" in pair
        )
    entries = [e for e in entries if e.get("name") != args.name] + [entry]
    _write_registry(file, entries)
    found = shutil.which(entry["probe"]) is not None
    print(f"registered {args.name} in {file}")
    print(f"probe {entry['probe']}: {'found on PATH' if found else 'MISSING on PATH - install it or fix --probe'}")
    if entry["output"] == "sarif":
        print("SARIF output converts via: python -m scripts.convert_sarif <report> --slug <slug> --scope <scope>")
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
    p = sub.add_parser("add-tool", help="register an analyser (creates the contract if absent)")
    p.add_argument("--name", required=True)
    p.add_argument("--command", required=True, help="plain argv - no shell metacharacters")
    p.add_argument("--probe", default=None, help="binary checked on PATH (default: first word)")
    p.add_argument("--lenses", default=None, help="comma-separated, e.g. security")
    p.add_argument("--replaces", default=None, help="bundled tools it supersedes, comma-separated")
    p.add_argument("--output", choices=("sarif", "json", "text"), default="text")
    p.add_argument("--severity-map", default=None, help="e.g. error=critical,warning=warning")
    p.set_defaults(fn=_cmd_add_tool)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
