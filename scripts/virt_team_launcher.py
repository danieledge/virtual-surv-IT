#!/usr/bin/env python3
"""Decision engine for `virt-surv go` - NOT a Claude Code hook, not run by the model,
never invoked from inside a session. This runs BEFORE Claude Code even starts, from the
user's own shell (the "go" branch of virt-surv's own shell function, written by
install_helper.py's run_setup_alias - a separate `virt-team` alias existed for one turn
of this same feature and was explicitly rejected as confusing: one alias, not two).

Two things get moved entirely outside the LLM pipeline here, for two different reasons:

1. **Tool-inventory pre-warming.** `check-review-tools.sh`'s own 7-day-TTL cache means a
   warm read never spawns a shell (`engage_probe.py`'s `_read_cached_tool_probe`) - the
   remaining cost only shows up on a cold/stale cache, and even then it's a one-time,
   machine-level fact, not a per-engagement one. Refreshing it here (best-effort, via the
   exact same `run_tool_probe` the live probe already calls - no logic duplicated) means
   that rare cost never touches a model turn at all.
2. **The resume-vs-new decision.** Live-observed unreliability, not just latency: the
   model-driven menu (`AskUserQuestion` over `engagement_state.resume_menu()`'s output)
   has occasionally picked the wrong option before self-correcting. This computes the
   SAME menu with the SAME function, but the human picks directly in the terminal - no
   model reasoning involved in the choice itself.

**Output contract (load-bearing - the caller is a shell function capturing stdout via
command substitution):** ALL interactive text (the menu, the prompt) goes to **stderr**.
**stdout carries ONLY the final pre-seeded prompt**, one line, one of:
  - `<engage-cmd> --resume <slug>` - resume that open engagement
  - `<engage-cmd> --new` - start new work
  - `` (empty) - nothing to decide, or the human chose to decide inside the session
where `<engage-cmd>` is the spelling of the engage command THIS project answers to:
bare `/engage` in repo-as-project mode, the namespaced
`/compliance-surveillance-team:engage` for a plugin install (see _engage_command - live
report 2026-08-16: a hardcoded bare `/engage` is an unknown command in a plugin-mode
session). The caller passes the string through as ONE argument, verbatim - it must not
prepend, split or reformat it. Never both an interactive transcript and the decision on
the same stream - a caller doing `decision="$(virt_team_launcher.py)"` must get exactly
the prompt string, nothing else.

Never asks about execution consent or any other safety gate - deliberately out of scope.
That gate requires the human to see what's actually being asked BEFORE granting it
(ADR-002: "intent, not grant"); asking it here, before the human has even described the
task, would be a blanket sight-unseen yes, not the specific informed consent the design
requires. Moving THAT decision out would weaken the protection, not just relocate it.

Fails open on any error: prints nothing to stdout (empty decision), so the caller always
falls back to a plain `claude` launch with no pre-seeded prompt - this script existing or
working correctly is never load-bearing for actually starting a session.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _scripts_dir() -> Path:
    """This script always lives directly in scripts/ (never staged/dual-copy like the
    UserPromptSubmit hook) - its siblings are simply its own directory."""
    return Path(__file__).resolve().parent


def _plugin_enabled(target: Path) -> bool:
    """Cheap marker check so an unrelated `claude` launch (any other project on this
    machine) does no work and prints nothing - never worth refreshing a cache or
    computing a menu for a project that doesn't even have the team wired in.

    Live bug (2026-08-15): this used to check only `.claude/hooks/run-guard.sh`, which
    exists in REPO-AS-PROJECT mode (developing the plugin itself) but NOT in the far more
    common case - a normal user project with the plugin installed via marketplace, where
    hooks resolve through `CLAUDE_PLUGIN_ROOT` pointing at the plugin's own install
    directory and nothing gets copied locally. That made this return False, silently, for
    every real user project - the exact live report that motivated this fix. Now checks,
    in order: the repo-as-project marker (unchanged), OR `.claude/team-preferences.json`
    (written by `run_configure` - the reliable signal a project has actually been set up
    for this team, present regardless of run mode)."""
    if (target / "docs" / "team-operating-guide.md").is_file():
        return True
    return (target / ".claude" / "team-preferences.json").is_file()


def _refresh_tool_cache(project_dir: Path) -> None:
    """Best-effort; a failure here must never block the resume-menu step or the launch
    itself. Calls the exact function engage_probe.py's own probe already calls - no
    reimplementation, so this can never drift from the live trust-boundary logic
    (root_is_trusted, plugin-vs-project provenance) that function's own docstring
    documents in detail."""
    try:
        from find_plugin_root import find_plugin_root
        import engage_probe

        plugin_root_arg = find_plugin_root(Path.home(), project_dir)
        root, _display, root_is_trusted = engage_probe.resolve_root(plugin_root_arg, project_dir)
        engage_probe.run_tool_probe(root, project_dir, root_is_trusted)
    except Exception:
        pass


def _engage_command(target: Path) -> str:
    """Which spelling of the engage command THIS project answers to. A plugin install
    namespaces every skill (`/compliance-surveillance-team:engage`); only repo-as-project
    mode - the plugin's own repo opened as the project, marked by the operating guide
    being present locally - loads them bare as `/engage`. Live report (2026-08-16): the
    pre-seeded prompt hardcoded the bare form, which a plugin-mode session rejects as an
    unknown command, so the pre-made decision arrived broken on every real plugin
    install. Same repo-as-project marker _plugin_enabled already keys on, reused here so
    the two can never disagree."""
    if (target / "docs" / "team-operating-guide.md").is_file():
        return "/engage"
    return "/compliance-surveillance-team:engage"


def _row_resume_token(row: dict) -> str:
    """The identifier a `--resume` decision should carry for this menu row. The
    workspace dir is preferred (it is what the engage skill's own resume flow keys on),
    with one exception: resume_menu() reports a flat-layout pack (a state file sitting
    directly in artifacts/, no per-slug subfolder) as dir "(flat)" - a display label,
    not a resumable identifier. Live finding (2026-08-16): the decision used to prefer
    dir unconditionally and emitted literally `--resume (flat)`; the engage skill's
    validation can only reject that and fall back to asking in-session - safe, but the
    pre-made decision this script exists for was silently lost. Use the real slug for
    that row instead."""
    workspace_dir = row.get("dir")
    if workspace_dir and workspace_dir != "(flat)":
        return workspace_dir
    return row.get("slug") or workspace_dir or ""


def _resume_decision(project_dir: Path) -> str:
    """Returns the full pre-seeded prompt string (possibly empty) - the engage command
    in the spelling THIS project answers to (see _engage_command), plus the
    resume-or-new flag. All interactive I/O here targets stderr/stdin explicitly -
    never print() bare, which would land on stdout and corrupt the caller's
    command-substitution capture."""
    try:
        import engagement_state

        menu = engagement_state.resume_menu(project_dir / "artifacts")
    except Exception:
        return ""
    shown = menu.get("shown") or []
    if not shown:
        return ""  # nothing open - nothing to decide, plain launch
    err = sys.stderr
    print("Existing engagement(s) found:", file=err)
    for i, row in enumerate(shown, 1):
        slug = _row_resume_token(row) or "?"
        status = row.get("status") or "?"
        title = row.get("title") or ""
        print(f"  {i}) resume {slug} ({status}) - {title}", file=err)
    more = menu.get("more") or 0
    if more:
        print(f"     (+{more} more not shown)", file=err)
    print("  n) start new", file=err)
    print("  [Enter] decide inside the session instead", file=err)
    try:
        # Live bug (2026-08-15): input(prompt) writes `prompt` to STDOUT, not stderr -
        # CPython does this unconditionally, regardless of which stream the caller
        # otherwise uses. Passing "Choice: " as input()'s own argument leaked it onto
        # the exact stream this function's own output contract reserves for the
        # decision alone, so a shell capturing stdout via $(...) got "Choice: --new"
        # instead of a clean "--new" - garbled into a single mangled argument by the
        # time it reached the launch command. Print the prompt text ourselves, to
        # stderr, then call input() with NO argument so it never touches stdout.
        print("Choice: ", end="", file=err)
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        return ""  # no tty / interrupted - fall through to deciding in-session
    if not choice:
        return ""
    engage_cmd = _engage_command(project_dir)
    if choice.lower() == "n":
        return f"{engage_cmd} --new"
    try:
        idx = int(choice)
    except ValueError:
        print(f"'{choice}' not recognised - deciding inside the session instead.", file=err)
        return ""
    if 1 <= idx <= len(shown):
        slug = _row_resume_token(shown[idx - 1])
        if slug:
            return f"{engage_cmd} --resume {slug}"
    print(f"'{choice}' out of range - deciding inside the session instead.", file=err)
    return ""


def _print_project_defaults(project_dir: Path) -> None:
    """One compact table of this project's effective team settings, to STDERR, every
    `virt-surv go` (2026-08-17 user request) - the human sees at a glance what the
    session is about to run with, before Claude Code even starts. ASCII-aligned, no
    box-drawing glyphs: corp Windows consoles decode stderr as cp1252 and box chars
    arrive as mojibake (the same lesson the probe's _ascii_safe already carries).
    Cosmetic: any failure here must never cost the launch or the decision."""
    err = sys.stderr
    try:
        import engage_probe

        prefs = engage_probe.resolve_preferences(project_dir)
        integrations = engage_probe.resolve_integrations(project_dir)
        raw = engage_probe.read_team_preferences(project_dir)
    except Exception:
        return
    rows = [
        ("docx export", "on" if "docx" in (prefs.get("extra_formats") or []) else "off"),
        ("regulatory citations", "on" if prefs.get("regulatory_citations") else "off"),
        ("large-context review split", "on" if prefs.get("large_context_review_split") else "off"),
        (
            "parallel dispatch (Workflow)",
            "on" if prefs.get("parallel_dispatch_via_workflow") else "off",
        ),
        ("standards critique", "on" if prefs.get("standards_critique") else "off"),
        ("codebase-map skeleton", "on" if prefs.get("map_skeleton") else "off"),
    ]
    tools = raw.get("review_tools") or {}
    overrides = ", ".join(f"{k}:{v}" for k, v in sorted(tools.items()) if v != "auto")
    rows.append(("review tools", overrides or "all auto"))
    jira = integrations.get("jira") or {}
    if jira.get("enabled"):
        rows.append(
            ("jira integration", f"on ({jira['mirror']}, {jira['project_key'] or 'UNSET'})")
        )
    else:
        rows.append(("jira integration", "off"))
    pr = integrations.get("pr_comments") or {}
    if pr.get("enabled") or pr.get("locked"):
        rows.append(("pr comments", "on (EXPERIMENTAL)" if pr.get("enabled") else "locked"))
    width = max(len(name) for name, _ in rows)
    print("Project defaults ('virt-surv configure' to change):", file=err)
    for name, value in rows:
        print(f"  {name.ljust(width)}  {value}", file=err)


def _offer_first_time_setup(project_dir: Path) -> bool:
    """No team configuration here yet: offer the real first-time setup instead of a
    plain launch with a hint (2026-08-17 user request). The configure flow's own
    stdout is redirected onto OUR stderr - the caller captures this process's stdout
    via $(...) as the decision string, and a setup transcript leaking into it would
    become the session's opening prompt. Returns True only when the project actually
    ends up configured; every decline/failure path falls back to the explained plain
    launch. Non-interactive callers (no tty, EOF) decline automatically."""
    err = sys.stderr
    helper = _scripts_dir().parent / "install_helper.py"
    if not helper.is_file():
        return False
    print(f"(virt-team: {project_dir} has no team configuration yet.)", file=err)
    print("Run first-time project setup now? [Y/n] ", end="", file=err)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if answer in ("n", "no"):
        return False
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, str(helper), "configure", str(project_dir)],
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
    except OSError:
        return False
    return proc.returncode == 0 and _plugin_enabled(project_dir)


def main() -> int:
    project_dir = Path.cwd()
    if not _plugin_enabled(project_dir):
        try:
            configured = _offer_first_time_setup(project_dir)
        except Exception:
            configured = False  # cosmetic path - never let it kill the launch
        if configured:
            print("Setup complete - continuing the launch.", file=sys.stderr)
    if not _plugin_enabled(project_dir):
        # Live report (2026-08-15): a session that ran this from the wrong directory (or
        # hit a shell cwd-reset - a documented issue on some corp Windows hosts, see
        # probe-contract.md) got a silent plain launch with no explanation, indistinguishable
        # from a genuine cold-cache decline. This message goes to stderr - never stdout,
        # which stays reserved for the decision string alone - so it's visible in the
        # terminal without corrupting a caller's command-substitution capture.
        print(
            f"(virt-team: {project_dir} doesn't look like a configured project - no "
            "docs/team-operating-guide.md or .claude/team-preferences.json here - "
            "launching plainly, no resume-menu. Wrong directory? cd into your project "
            "root first, or run 'virt-surv configure' if this project hasn't been set "
            "up yet.)",
            file=sys.stderr,
        )
        return 0  # not a plugin-enabled project - plain launch, but now explained
    scripts_dir = _scripts_dir()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        _print_project_defaults(project_dir)
    except Exception:
        pass  # cosmetic - the table must never cost the launch
    try:
        _refresh_tool_cache(project_dir)
    except Exception:
        pass  # belt-and-braces, same as _refresh_tool_cache's own internal try/except -
        # a failure here must cost only the cache refresh, never the resume decision below.
    try:
        decision = _resume_decision(project_dir)
    except Exception:
        decision = ""  # same reasoning - never let one piece's failure kill the other
    if decision:
        print(decision)  # the ONLY thing that goes to stdout
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open - never block a claude launch over this optimisation
