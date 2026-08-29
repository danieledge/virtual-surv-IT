"""
scripts/extensions.py - the company extensions contract, parsed and surfaced (ADR-009).

A working project may carry `docs/team-extensions.md` (template:
`docs/templates/team-extensions.md`): standing instructions, close actions, an analyser
registry (a fenced ```json block) and named integrations. The engage step-0 probe runs
`show` so the open surfaces the contract; reviewers consult the registry for lens routing.

TWO TIERS (2026-08-27, plan-org-extensions). The project file answers "this repo is
different"; an ORG file at `~/.config/virt-surv-it/team-extensions.md` (honouring
XDG_CONFIG_HOME, the same machine-config home as installer.json) answers "this is how our
organisation works". The owner's case for it: "wouldn't want a user to have to set up a
standard workflow in every project" - a compliance function with fifteen repositories was
otherwise authoring the same contract fifteen times, and a standard nobody can apply
centrally is not a standard.

Resolution is `project > org`, the same precedence chain resolve_preferences already uses -
but merged PER SECTION, because the sections mean different things:
  - Standing instructions / Close actions: CONCATENATE, org first. Both apply; an org's
    Confluence write-up and a project's "copy the pack to the share" are both wanted.
  - Analyser registry / Integrations: MERGE BY NAME, project wins on collision - which is
    what lets an org register the corporate scanner once while one project pins its own.
Every entry carries its ORIGIN through to `show`. An extension whose source is invisible is
an extension nobody can debug.

Deliberately NOT in the plugin tree: config there is overwritten by the next update, which
is the one failure mode this location exists to avoid.

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
# C9 (2026-08 audit): \n and \r were missing from the blocked set - in an actual shell,
# a bare newline separates statements exactly like `;` does, so "safe" argv split on
# whitespace by str.split() at registration time was no defense against a command string
# that hides a second statement on its own line for whatever eventually runs it as a
# shell command (an agent's Bash tool, a future script). `;` was refused; `\n` achieving
# the identical effect was not - closing that gap here, not narrowing the plain-argv
# contract.
_META_RE = re.compile(r"[;|&$`<>\n\r]")
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


# A close action an ORG declares mandatory, written as a leading token on its bullet:
#     - [required:confluence] Write a Confluence page in space SURV summarising the work.
# The id is what the engagement records against, so matching is exact rather than fuzzy
# text comparison - an action whose wording was tidied must not silently stop counting.
_REQUIRED_RE = re.compile(r"^\s*[-*]\s*\[required:([a-z0-9][a-z0-9_-]{0,31})\]\s*(.+?)\s*$", re.I)


def required_close_actions(org_text: str) -> list:
    """[(id, text)] for close actions the ORG marked required.

    ORG TIER ONLY, and the caller enforces that by passing only the org body. A project
    must not be able to impose a gate on itself: an engagement inventing its own
    pass condition is not a control, it is a way to look compliant. The org file is
    administered by whoever sets the standard; the project file is written by whoever is
    doing the work, and those are different people for a reason.

    This is the ONE place an extension can add something a close must satisfy. It remains
    additive in the strict sense - it can only ADD a requirement, never remove or weaken
    one - and it cannot express anything except "this named action was recorded"."""
    found: list = []
    seen: set = set()
    for line in (org_text or "").splitlines():
        match = _REQUIRED_RE.match(line)
        if not match:
            continue
        action_id = match.group(1).lower()
        if action_id in seen:
            continue
        seen.add(action_id)
        found.append((action_id, match.group(2).strip()))
    return found


def org_required_close_actions(org_path: Path | None = None) -> list:
    """The required actions this machine's org contract declares, or []."""
    path = org_path if org_path is not None else org_file()
    try:
        if not path or not path.is_file():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return required_close_actions(split_sections(text).get("Close actions", ""))


def org_file() -> Path:
    """The ORG-level contract: ~/.config/virt-surv-it/team-extensions.md.

    Same machine-config home as installer.json, honouring XDG_CONFIG_HOME, so this adds a
    file to a directory that already exists rather than inventing a location."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "virt-surv-it" / "team-extensions.md"


# Sections whose bodies ACCUMULATE across tiers rather than one replacing the other.
_CONCAT_SECTIONS = ("Standing instructions", "Close actions")


def _tag_origin(entries: list, origin: str) -> list:
    for entry in entries:
        if isinstance(entry, dict):
            entry.setdefault("origin", origin)
    return entries


def merge_contracts(org: dict | None, project: dict | None) -> dict:
    """Resolve org + project into one contract. Project wins where they collide.

    Never raises on a malformed tier: a broken org file must not take a project's own
    extensions down with it, so each side is used for whatever it could parse. Problems
    from both tiers are carried through, prefixed with their origin, because a registry
    entry that was refused should say WHERE it was refused from."""
    org = org or {"sections": {}, "registry": [], "problems": []}
    project = project or {"sections": {}, "registry": [], "problems": []}

    sections: dict = {}
    for name in _SECTIONS:
        org_body = (org["sections"].get(name) or "").strip()
        proj_body = (project["sections"].get(name) or "").strip()
        if name in _CONCAT_SECTIONS and org_body and proj_body:
            # Org first: the standing rule leads, the project's addition follows. Exact
            # duplicates are dropped so a project that copied the org file does not
            # produce every instruction twice.
            org_lines = org_body.splitlines()
            seen = {line.strip() for line in org_lines if line.strip()}
            extra = [ln for ln in proj_body.splitlines() if ln.strip() not in seen]
            sections[name] = "\n".join(
                org_lines + ([""] + extra if any(x.strip() for x in extra) else [])
            )
        elif proj_body:
            sections[name] = proj_body
        elif org_body:
            sections[name] = org_body

    by_name: dict = {}
    for entry in _tag_origin(list(org["registry"]), "org"):
        by_name[entry.get("name")] = entry
    for entry in _tag_origin(list(project["registry"]), "project"):
        by_name[entry.get("name")] = entry  # project wins on collision, by design

    problems = [f"[org] {p}" for p in org["problems"]]
    problems += [f"[project] {p}" for p in project["problems"]]
    return {"sections": sections, "registry": list(by_name.values()), "problems": problems}


def load_resolved(project_path: Path | None = None, org_path: Path | None = None) -> dict:
    """The merged contract, or None-shaped emptiness when neither tier exists.

    Reading either tier is best-effort: an unreadable file contributes nothing rather than
    failing the open. Absence stays free - no file, no cost, silent exit."""
    project_path = project_path or default_file()
    org_path = org_path if org_path is not None else org_file()
    org_data = project_data = None
    for path, target in ((org_path, "org"), (project_path, "project")):
        try:
            if path and path.is_file():
                parsed = load(path)
                if target == "org":
                    org_data = parsed
                else:
                    project_data = parsed
        except OSError:
            continue
    if org_data is None and project_data is None:
        return {}
    merged = merge_contracts(org_data, project_data)
    merged["files"] = {
        "org": str(org_path) if org_data is not None else "",
        "project": str(project_path) if project_data is not None else "",
    }
    return merged


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
        return [], [] if not (section or "").strip() else [
            "Analyser registry: no ```json block found"
        ]
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
        if not isinstance(e, dict) or not e.get("name") or not (e.get("command") or e.get("mcp")):
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


def _load_raw_registry_entries(file: Path) -> list:
    """The registry's raw `analysers` array exactly as JSON parsed it - valid or not,
    UNFILTERED by parse_registry()'s validation. `load()["registry"]` is valid-entries-
    only (by design, for `show`/`check`); add-tool's upsert must not build the file it
    writes back from that filtered view.

    M7 (2026-08 Fable audit): `_cmd_add_tool` used to do exactly that - rebuild the
    registry from `load(file)["registry"]`, so a pre-existing entry parse_registry()
    already flagged as a problem (bad name/command, a refused shell metacharacter, an
    unrecognised shape) vanished, silently and unreported, the instant add-tool touched
    the file for anything else. An invalid entry staying on disk is not a safety issue -
    this script never executes registry commands (module docstring) - so there is no
    reason to destroy it instead of leaving it for a human to fix or remove on purpose."""
    if not file.is_file():
        return []
    text = file.read_text(encoding="utf-8", errors="replace")
    section = split_sections(text).get("Analyser registry", "")
    m = _JSON_FENCE_RE.search(section)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    entries = data.get("analysers")
    return entries if isinstance(entries, list) else []


def _cmd_show(args: argparse.Namespace) -> int:
    # --file still targets ONE file when given explicitly (add-tool and the tests rely on
    # it); with no --file, both tiers resolve and merge.
    if args.file:
        if not args.file.is_file():
            return 0
        data = load(args.file)
        data["files"] = {"org": "", "project": str(args.file)}
    else:
        data = load_resolved()
        if not data:
            return 0  # neither tier present - zero-cost silence
    files = data.get("files") or {}
    if files.get("org") and files.get("project"):
        print(f"TEAM-EXTENSIONS: org {files['org']} + project {files['project']}")
    else:
        print(f"TEAM-EXTENSIONS: {files.get('project') or files.get('org')}")
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
            # The origin travels with the entry: a reader must be able to tell an org
            # standard from a project's own registration without opening two files.
            src = f" <{e['origin']}>" if e.get("origin") else ""
            print(
                f"- {e['name']}{src} [{mark}] lenses={','.join(e['lenses']) or '-'}{rep} :: {what}"
            )
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
            args.command = _ask(
                'Command (plain argv, e.g. "cxcli scan --format sarif -o {workspace}/data/cx.sarif {target}")'
            )
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
        print(
            "need --name and one of --command / --mcp (or run with --interactive)", file=sys.stderr
        )
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
    raw_entries = _load_raw_registry_entries(file)
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
    entries = [
        e for e in raw_entries if not (isinstance(e, dict) and e.get("name") == args.name)
    ] + [entry]
    _write_registry(file, entries)
    print(f"registered {args.name} in {file}")
    if args.mcp:
        print(
            f"mcp tool {args.mcp}: ensure the server is wired in your project's .mcp.json "
            "and named under ## Integrations"
        )
    else:
        found = shutil.which(entry["probe"]) is not None
        print(
            f"probe {entry['probe']}: {'found on PATH' if found else 'MISSING on PATH - install it or fix --probe'}"
        )
        if entry.get("output") == "sarif":
            print(
                "SARIF output converts via: python -m scripts.convert_sarif <report> --slug <slug> --scope <scope>"
            )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    # With no --file this checks the MERGED registry, so it reports on the tools the session
    # will actually reach for rather than one tier's view of them.
    if args.file:
        if not args.file.is_file():
            print("no team-extensions file - nothing to check")
            return 0
        data = load(args.file)
    else:
        data = load_resolved()
        if not data:
            print("no team-extensions file - nothing to check")
            return 0
    missing = 0
    for e in data["registry"]:
        if e.get("mcp"):
            print(
                f"{e['name']:24} mcp      ({e['mcp']}) - presence not probed; verify the server in .mcp.json"
            )
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
    p = sub.add_parser(
        "add-tool",
        help="register an analyser (creates the contract if absent); no flags = interactive wizard",
    )
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
