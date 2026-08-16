#!/usr/bin/env python3
"""UserPromptSubmit hook - pre-run the /engage step-0 probe before the model's turn.

The step-0 open (`engage-open.md` + `engage/SKILL.md` step 0b) used to cost 2 separate
Bash-tool round-trips on every `/engage`/`/engage-light`/`/map-codebase` open - the probe
heredoc, then `engagement_state list --menu` - each a real model turn, not free, even
though both are already cheap in substance (tool inventory 7-day TTL cached, map-drift
mtime-shortcut cached, the menu computation itself sub-second). This hook removes both
round-trips for the steady-state case: it calls the SAME functions
(`find_plugin_root.find_plugin_root`, `engage_probe.build_report`,
`engagement_state.resume_menu` - no logic duplicated, no new drift surface) from a
`UserPromptSubmit` hook, which Claude Code fires BEFORE the model's turn and whose plain
stdout (exit 0) is added straight to context - the identical mechanism
`persona_anchor.py`/`session_resume_brief.py` already rely on. When the result lands in
context already wrapped as `<engage-probe-result>`, `engage-open.md`'s step 0 and
`engage/SKILL.md`'s step 0b both use it directly instead of running their own command.

Dormancy-exact, two gates, in order:
1. `user_input` must actually look like one of the three commands that read
   `engage-open.md` (`/engage`, `/engage-light`, `/map-codebase` - checked by grepping
   every skill file for the reference, not guessed) - a single regex check, so every
   other prompt in every other session costs nothing, same contract as
   `persona_anchor.py`'s own dormancy gate.
2. The project's `.guard-interpreter` cache must already be warm. A cold cache means
   this is a genuinely first-ever run in this project - the exact case the live Bash
   heredoc's own three-way interpreter trial (`python3`/`python`/`py`, Windows-aware)
   exists to handle, and reimplementing that here would be new, untested surface for a
   case that only happens once per project. This hook declines instead: no injected
   block, the model's own live probe runs exactly as it does today. The steady-state
   majority (every session after the first, in a project that has run the plugin
   before) is what this hook actually targets.

Fails open on any error past those two gates too (missing plugin-root, a build_report
exception, an unreadable cache file) - an optimisation must never cost a broken open;
worst case is simply no injected block, same as a cold cache.

Wire via scripts/apply-engage-probe-prefetch.sh (HUMAN-run - hook/config edits are
human-only, ADR-002 rec 5).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

# \b alone is too loose here: a hyphen counts as a word boundary, so "/engage-lighter"
# would match via the bare "engage" branch (live test caught this). Command arguments
# always follow a space, never a bare hyphen, so require whitespace-or-end explicitly.
#
# The optional `<plugin-name>:` prefix (2026-08-16 live finding): a plugin install
# namespaces every command, so real plugin-mode users type (and virt-surv go now
# pre-seeds) `/compliance-surveillance-team:engage ...` - the bare-only pattern meant
# the prefetch NEVER fired for them and every open silently fell back to the in-session
# probe block. It went unnoticed because the repo-as-project dev loop, and Friday's
# pre-namespacing launcher, both used the bare spelling that did match. Any plugin name
# is accepted rather than hardcoding this one (a fork can rename the plugin; the cost of
# matching a foreign `/other-plugin:engage` is one probe that injects context the model
# then ignores - fail-open, same as every other branch here).
_ENGAGE_RE = re.compile(r"^/(?:[\w.-]+:)?(?:engage(?:-light)?|map-codebase)(?:\s|$)")


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _read_cache(project_dir: Path) -> str:
    """A garbage-but-non-empty cache file used to be injected verbatim as authoritative
    (Fable review, 2026-08-14): probe-contract.md tells the model never to re-probe the
    printed INTERPRETER= word, so a corrupted cache would have been trusted for the whole
    open. Validate it actually resolves to something executable before returning it - the
    same bar the live heredoc's own cache check already applies (`command -v`) - so a bad
    cache degrades to the cold-cache path (no injected block, live probe runs normally)
    instead of poisoning the open."""
    try:
        raw = (project_dir / ".claude" / ".guard-interpreter").read_text(encoding="utf-8")
    except OSError:
        return ""
    interp = raw.strip()
    if not interp or "\n" in raw.strip("\n"):
        return ""  # empty, or a multi-line file - not a single interpreter token/path
    return interp if shutil.which(interp) else ""


def _scripts_dir() -> Path:
    """Sibling find_plugin_root.py/engage_probe.py live in scripts/ - resolve that
    directory whether THIS file is running from its staged copy
    (scripts/staged_hooks/engage_probe_prefetch.py, what this file's own tests load
    directly) or its live, applied copy (scripts/engage_probe_prefetch.py, what actually
    runs once a human applies it) - __file__.parent differs between the two."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent):
        if (candidate / "find_plugin_root.py").is_file():
            return candidate
    return here  # neither has it - let the import below fail naturally (fail-open)


def _resume_menu_json(project_dir: Path) -> str | None:
    """Same computation as `<python> -m scripts.engagement_state list --menu`
    (SKILL.md step 0b), called directly rather than reimplemented. Separate try/except
    from `_build_block`'s: a failure here must not cost the probe report too - the two
    are independent pieces of the same injected block, fail open independently."""
    try:
        scripts_dir = _scripts_dir()
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import engagement_state

        menu = engagement_state.resume_menu(project_dir / "artifacts")
        return json.dumps(menu, ensure_ascii=False, indent=2)
    except Exception:
        return None


def _build_block(interp: str, project_dir: Path) -> str | None:
    """Returns the full injected block, or None on any failure (fail-open)."""
    try:
        scripts_dir = _scripts_dir()
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from find_plugin_root import find_plugin_root  # local import: see sys.path above
        import engage_probe

        plugin_root = find_plugin_root(Path.home(), project_dir)
        report = engage_probe.build_report(plugin_root, project_dir)
    except Exception:
        return None
    if not report:
        return None
    lines = [
        "<engage-probe-result>",
        "Pre-computed by the engage_probe_prefetch hook, same probe engage-open.md's step 0",
        "documents - use these values directly, do NOT run the Bash bootstrap heredoc for",
        "this open. Still read docs/team-operating-guide.md yourself using PLUGIN_ROOT below;",
        "the probe never prints it.",
        f"INTERPRETER={interp}",
        report,
    ]
    try:
        menu_json = _resume_menu_json(project_dir)
    except Exception:
        # Belt-and-braces, same reasoning as main()'s outer guard around _build_block
        # itself: _resume_menu_json already fails open internally, but the call site
        # must not trust that alone - a failure here must cost only RESUME_MENU, never
        # the report this function already successfully built above.
        menu_json = None
    if menu_json is not None:
        lines += [
            "RESUME_MENU (same shape as `<python> -m scripts.engagement_state list --menu` -",
            "use this directly, do NOT also run that command for this open):",
            menu_json,
        ]
    lines.append("</engage-probe-result>")
    return "\n".join(lines)


def main() -> int:
    _force_utf8_output()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = (data.get("user_input") or "").lstrip()
    if not _ENGAGE_RE.match(prompt):
        return 0  # not an engage-open.md consumer - zero cost, dormancy preserved

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    interp = _read_cache(project_dir)
    if not interp:
        return 0  # cold cache: first-ever run in this project, let the live probe handle it

    try:
        block = _build_block(interp, project_dir)
        if block:
            print(block)
    except Exception:
        pass  # belt-and-braces: _build_block already fails open internally, but a hook's
        # own main() must never propagate ANY exception past itself (matches
        # persona_anchor.py/session_resume_brief.py's own outer try/except) - an
        # optimisation must never cost a broken open.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
