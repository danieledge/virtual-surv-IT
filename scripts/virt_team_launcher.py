#!/usr/bin/env python3
"""Decision engine for the `virt-team` shell alias/function - NOT a Claude Code hook, not
run by the model, never invoked from inside a session. This runs BEFORE Claude Code even
starts, from the user's own shell.

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
**stdout carries ONLY the final decision**, one line, one of:
  - `--resume <slug>` - resume that open engagement
  - `--new` - start new work
  - `` (empty) - nothing to decide, or the human chose to decide inside the session
Never both an interactive transcript and the decision on the same stream - a caller doing
`decision="$(virt_team_launcher.py)"` must get exactly the flag string, nothing else.

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
    computing a menu for a project that doesn't even have the guard system wired in."""
    return (target / ".claude" / "hooks" / "run-guard.sh").is_file()


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


def _resume_decision(project_dir: Path) -> str:
    """Returns the decision string (possibly empty). All interactive I/O here targets
    stderr/stdin explicitly - never print() bare, which would land on stdout and corrupt
    the caller's command-substitution capture."""
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
        slug = row.get("dir") or row.get("slug") or "?"
        status = row.get("status") or "?"
        title = row.get("title") or ""
        print(f"  {i}) resume {slug} ({status}) - {title}", file=err)
    more = menu.get("more") or 0
    if more:
        print(f"     (+{more} more not shown)", file=err)
    print("  n) start new", file=err)
    print("  [Enter] decide inside the session instead", file=err)
    try:
        choice = input("Choice: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""  # no tty / interrupted - fall through to deciding in-session
    if not choice:
        return ""
    if choice.lower() == "n":
        return "--new"
    try:
        idx = int(choice)
    except ValueError:
        print(f"'{choice}' not recognised - deciding inside the session instead.", file=err)
        return ""
    if 1 <= idx <= len(shown):
        slug = shown[idx - 1].get("dir") or shown[idx - 1].get("slug")
        if slug:
            return f"--resume {slug}"
    print(f"'{choice}' out of range - deciding inside the session instead.", file=err)
    return ""


def main() -> int:
    project_dir = Path.cwd()
    if not _plugin_enabled(project_dir):
        return 0  # not a plugin-enabled project - stay silent, plain launch
    scripts_dir = _scripts_dir()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
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
