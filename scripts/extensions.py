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
        if not isinstance(e, dict) or not e.get("name") or not (
            e.get("command") or e.get("mcp")
        ):
            problems.append(
                f"analysers[{i}]: 'name' and one of 'command' (CLI) or 'mcp' "
                "(server.tool) are required"
            )
            continue
        if e.get("command") and e.get("mcp"):
            problems.append(f"analysers[{i}] ({e['name']}): give 'command' OR 'mcp', not both")
            continue
        if e.get("command"):
            if _META_RE.search(str(e["command"])):
                problems.append(
                    f"analysers[{i}] ({e['name']}): command contains shell metacharacters - "
                    "REFUSED (plain argv only, ADR-009)"
                )
                continue
            e.setdefault("probe", str(e["command"]).split()[0])
        # mcp entries need no probe: no binary, no shell - the harness permission-gates
        # MCP calls and the exec guard never applies.
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
            if e.get("mcp"):
                mark, what = "mcp", f"mcp:{e['mcp']}"
            else:
                found = shutil.which(e["probe"]) is not None
                mark = "found" if found else "MISSING on PATH"
                what = e["command"]
            rep = f" replaces {','.join(e['replaces'])}" if e["replaces"] else ""
            print(f"- {e['name']} [{mark}] lenses={','.join(e['lenses']) or '-'}{rep} :: {what}")
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


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def _wizard(args: argparse.Namespace) -> None:
    """Interactive registration - fills the args in place. Plain stdin prompts (works in
    any terminal; no curses dependency)."""
    print("Register an analyser (Enter accepts the [default]; Ctrl-C aborts)")
    args.name = args.name or _ask("Tool name (e.g. cx)")
    while not args.name:
        args.name = _ask("Tool name is required")
    kind = _ask("CLI command or MCP tool? (cli/mcp)", "cli").lower()
    if kind.startswith("m"):
        args.mcp = _ask("MCP tool (server.toolname, e.g. atlassian.security_scan)")
    else:
        while True:
            args.command = _ask('Command (plain argv, e.g. "cxcli scan --format sarif -o {workspace}/data/cx.sarif {target}")')
            if not _META_RE.search(args.command or ""):
                break
            print("  REFUSED: no shell metacharacters (; | & $ ` < >) - plain argv only")
        args.probe = _ask("Probe binary on PATH", (args.command or "x").split()[0]) or None
    args.lenses = _ask("Lenses it serves (comma-separated)", "security")
    args.replaces = _ask("Bundled tools it replaces (comma-separated, blank for none)")
    if not args.mcp:
        args.output = _ask("Output format (sarif/json/text)", "sarif")
        if args.output == "sarif":
            args.severity_map = _ask("Severity map (k=v,.. blank for defaults)", "")


def _cmd_add_tool(args: argparse.Namespace) -> int:
    """Upsert a registry entry - flags, or an interactive wizard when flags are absent
    and stdin is a terminal (EXTENDING.md step 2)."""
    if args.interactive or (not args.name and sys.stdin.isatty()):
        try:
            _wizard(args)
        except (KeyboardInterrupt, EOFError):
            print("\naborted - nothing written")
            return 130
    if not args.name or not (args.command or args.mcp):
        print("need --name and one of --command / --mcp (or run with --interactive)",
              file=sys.stderr)
        return 2
    if args.command and args.mcp:
        print("give --command OR --mcp, not both", file=sys.stderr)
        return 2
    if args.command and _META_RE.search(args.command):
        print(
            "REFUSED: command contains shell metacharacters (; | & $ ` < >) - plain argv "
            "only (ADR-009); chain nothing",
            file=sys.stderr,
        )
        return 2
    file = args.file or default_file()
    entries = load(file)["registry"] if file.is_file() else []
    entry: dict = {"name": args.name}
    if args.mcp:
        entry["mcp"] = args.mcp
    else:
        entry["command"] = args.command
        entry["probe"] = args.probe or args.command.split()[0]
        entry["output"] = args.output
    entry["lenses"] = [s for s in (args.lenses or "").split(",") if s]
    entry["replaces"] = [s for s in (args.replaces or "").split(",") if s]
    if args.severity_map:
        entry["severity_map"] = dict(
            pair.split("=", 1) for pair in args.severity_map.split(",") if "=" in pair
        )
    entries = [e for e in entries if e.get("name") != args.name] + [entry]
    _write_registry(file, entries)
    print(f"registered {args.name} in {file}")
    if args.mcp:
        print(f"mcp tool {args.mcp}: ensure the server is wired in your project's .mcp.json "
              "and named under ## Integrations")
    else:
        found = shutil.which(entry["probe"]) is not None
        print(f"probe {entry['probe']}: {'found on PATH' if found else 'MISSING on PATH - install it or fix --probe'}")
        if entry.get("output") == "sarif":
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
        if e.get("mcp"):
            print(f"{e['name']:24} mcp      ({e['mcp']}) - presence not probed; verify the server in .mcp.json")
            continue
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
    p = sub.add_parser("add-tool", help="register an analyser (creates the contract if absent); no flags = interactive wizard")
    p.add_argument("--name", default=None)
    p.add_argument("--command", default=None, help="plain argv - no shell metacharacters")
    p.add_argument("--mcp", default=None, help="MCP tool as server.toolname (instead of --command)")
    p.add_argument("--interactive", action="store_true", help="force the wizard")
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
