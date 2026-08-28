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
1. The submitted `prompt` must actually look like one of the three commands that read
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
import sys
from pathlib import Path


def _vsit_paths():
    """The layout resolver (VSIT migration), imported lazily.

    Lazy because this file may run standalone from a bare clone where `scripts/` is not yet
    on sys.path. Searches its own directory AND a sibling `scripts/`, because several of
    these files also exist as staged copies under `scripts/staged_hooks/`."""
    import sys as _sys

    _here = Path(__file__).resolve().parent
    for _candidate in (_here, _here.parent, _here.parent / "scripts"):
        if (_candidate / "vsit_paths.py").is_file():
            if str(_candidate) not in _sys.path:
                _sys.path.insert(0, str(_candidate))
            break
    import vsit_paths

    return vsit_paths


# shutil, subprocess and time are imported INSIDE the branches that use them, not here.
# This hook fires on EVERY UserPromptSubmit - it must, because its job is to put the probe
# in context before the turn starts, so it cannot be lazy or deferred - and on the great
# majority of prompts it reads one regex and exits. Paying `import subprocess` (a measured
# ~11ms, pulling selectors and signal with it) to decide it has nothing to do is exactly
# the cost its dormancy gate exists to avoid (2026-08-25 performance review).

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
    import shutil

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

        # resume_menu_json, not resume_menu: the injected block is model context, so
        # `open` travels as slugs only (rows stay for in-process consumers - see
        # engagement_state.resume_menu_json's docstring). getattr fallback covers a
        # mixed-version install where this hook outruns an older engagement_state.
        menu_fn = getattr(engagement_state, "resume_menu_json", engagement_state.resume_menu)
        menu = menu_fn(_vsit_paths().engagements_dir(project_dir))
        return json.dumps(menu, ensure_ascii=False, indent=2)
    except Exception:
        return None


def _engage_flag(prompt: str) -> str:
    """The wrapper-provided resume-or-new answer, verbatim from the prompt: '--new',
    '--resume <slug>', or '' when neither is present."""
    m = re.search(r"(?:^|\s)--resume\s+(\S+)", prompt)
    if m:
        return f"--resume {m.group(1)}"
    if re.search(r"(?:^|\s)--new(?:\s|$)", prompt):
        return "--new"
    return ""


def _build_block(interp: str, project_dir: Path, prompt: str = "") -> str | None:
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
        "this open, and never compose a substitute probe of your own (no grepping the",
        "skill tree for fields, no ad-hoc engagement_state calls - live drift 2026-08-17).",
        "Still read docs/team-operating-guide.md yourself using PLUGIN_ROOT below;",
        "the probe never prints it.",
        f"INTERPRETER={interp}",
        report,
    ]
    lines += _tail_lines(project_dir, prompt)
    return "\n".join(lines)


def _tail_lines(project_dir: Path, prompt: str) -> list:
    """Everything after the report - the flag, the (conditional) resume menu, and the
    closing tag. Shared by the live build and the go-written cache fast path so the two
    can never drift."""
    lines: list = []
    flag = _engage_flag(prompt)
    if flag:
        lines.append(f"ENGAGE_FLAG={flag}")
    if flag == "--new":
        # ZERO engagement discovery under --new (SKILL.md 0b): the resume menu is
        # deliberately NOT injected - there is nothing to validate and nothing to
        # enumerate; the human already answered in the go menu.
        lines.append("(--new: resume menu omitted on purpose - skip 0b entirely, no list --menu,")
        lines.append("no open-pack commentary; go straight to classifying the work)")
        lines.append("</engage-probe-result>")
        return lines
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
    return lines


_PROBE_CACHE_TTL_S = 3600


def _git_identity(project_dir: Path) -> tuple[str, str]:
    """(branch, head) of the working project; ('', '') when git or a repo is absent.
    Matched strictly against the cache's stamped values - both sides are empty in a
    non-repo, so they still match there. Part of the cache identity fingerprint
    (2026-08-18, external token-review finding 2): TTL + prefs mtime alone could serve a
    report whose embedded BRANCH= was written before a branch switch inside the hour.
    `rev-parse HEAD --abbrev-ref HEAD`, in that order: --abbrev-ref applies to every rev
    AFTER it, so the old `--abbrev-ref HEAD HEAD` abbreviated BOTH and stamped the branch
    name twice - the HEAD half of the fingerprint was a no-op and a new commit on the same
    branch never invalidated the cache (found 2026-08-20)."""
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "HEAD", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = (proc.stdout or "").strip().splitlines()
        if proc.returncode == 0 and len(lines) >= 2:
            return lines[1].strip(), lines[0].strip()  # (branch, head) - see note above
    except Exception:
        pass
    return "", ""


def _live_plugin_version() -> str:
    """The manifest version of the install this hook belongs to - walked upward from the
    hook file itself so the same text works from scripts/ (live) and scripts/staged_hooks/
    (staged). '' when unreadable: the check is then skipped rather than guessing."""
    try:
        for anc in Path(__file__).resolve().parents:
            manifest = anc / ".claude-plugin" / "plugin.json"
            if manifest.is_file():
                return str(
                    json.loads(manifest.read_text(encoding="utf-8-sig")).get("version") or ""
                )
    except Exception:
        pass
    return ""


def _cached_block(project_dir: Path, data: dict, prompt: str) -> str | None:
    """The corp fast path (2026-08-18 user request: the in-session probe can take
    minutes on corporate boxes): serve the go-written .claude/engage-probe.json with
    zero probe computation - only the session stamp and the resume menu are done live
    (the stamp MUST be live: the cache is written pre-session, deliberately unstamped,
    and no pre-session process may forge session scoping; the menu changed the moment
    the previous engagement opened). Pure accelerator: any staleness (TTL, prefs mtime
    change, toggled off, missing) returns None and the live path runs exactly as
    before - a plain `claude` + manual /engage is never broken by this."""
    try:
        raw = json.loads(
            (project_dir / ".claude" / "engage-probe.json").read_text(encoding="utf-8")
        )
        import time

        age = time.time() - float(raw.get("computed_at_epoch") or 0)
        if age < 0 or age > _PROBE_CACHE_TTL_S:
            return None
        prefs_file = project_dir / ".claude" / "team-preferences.json"
        prefs_mtime = int(prefs_file.stat().st_mtime) if prefs_file.is_file() else 0
        cached_prefs_mtime = raw.get("prefs_mtime")
        # NOT `or -1`: a prefs-less project stamps 0, and 0-is-falsy turned that into -1,
        # so the fast path silently never fired for the common no-preferences case
        # (found 2026-08-18 by the cache-lifecycle test matrix).
        if cached_prefs_mtime is None or int(cached_prefs_mtime) != prefs_mtime:
            return None  # settings changed since go - recompute live
        try:
            prefs = json.loads(prefs_file.read_text(encoding="utf-8-sig"))
            if isinstance(prefs, dict) and prefs.get("probe_cache") is False:
                return None  # toggled off
        except Exception:
            pass
        # Identity fingerprint (2026-08-18, external token-review finding 2): the cached
        # report embeds BRANCH= and PLUGIN_VERSION= from compute time, so TTL + prefs
        # alone can inject stale facts after a branch switch or /plugin update inside the
        # hour. Strict empty-normalised equality; a cache written before these fields
        # existed mismatches once, costs one live probe, and go's next run stamps them.
        if _git_identity(project_dir) != (
            str(raw.get("git_branch") or ""),
            str(raw.get("git_head") or ""),
        ):
            return None  # branch/HEAD moved since go - recompute live
        live_version = _live_plugin_version()
        if live_version and str(raw.get("plugin_version") or "") != live_version:
            return None  # plugin updated since go - recompute live
        report = raw.get("report") or ""
        interp = raw.get("interpreter") or ""
        if not report or not interp:
            return None
    except Exception:
        return None
    sid = data.get("session_id")
    if sid:
        try:
            art = _vsit_paths().engagements_dir(project_dir)
            art.mkdir(parents=True, exist_ok=True)
            (art / ".team-session.json").write_text(json.dumps({"session": sid}), encoding="utf-8")
        except Exception:
            pass  # the first engagement_state mutation stamps as a fallback
    lines = [
        "<engage-probe-result>",
        "Pre-computed by `virt-surv go` (probe cache) and served by the prefetch hook -",
        "use these values directly, do NOT run the Bash bootstrap heredoc for this open,",
        "and never compose a substitute probe of your own. Still read",
        "docs/team-operating-guide.md yourself using PLUGIN_ROOT below.",
        f"INTERPRETER={interp}",
        report,
    ]
    lines += _tail_lines(project_dir, prompt)
    return "\n".join(lines)


def main() -> int:
    _force_utf8_output()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    # Claude Code names this field `prompt` - verified 2026-08-20 against the shipped
    # CLI's own hook schema (`hook_event_name: "UserPromptSubmit", prompt: ...`), not
    # against docs. It was read as `user_input` from the start, a name Claude Code
    # never sends, so the gate below never matched and this prefetch had NEVER fired
    # in a real session: every /engage paid the full live probe, which is minutes on a
    # corp box. The whole test suite fed `user_input` too, so it was self-consistently
    # wrong. `user_input` stays as a fallback rather than being swapped out, so any
    # caller or future rename that does send it keeps working.
    prompt = (data.get("prompt") or data.get("user_input") or "").lstrip()
    if not _ENGAGE_RE.match(prompt):
        return 0  # not an engage-open.md consumer - zero cost, dormancy preserved

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    try:
        # Corp fast path FIRST (2026-08-18): a fresh go-written probe cache serves the
        # whole block with zero probe computation - no interpreter-cache requirement
        # either, since nothing needs spawning.
        cached = _cached_block(project_dir, data, prompt)
        if cached:
            print(cached)
            return 0
    except Exception:
        pass
    interp = _read_cache(project_dir)
    if not interp:
        return 0  # cold cache: first-ever run in this project, let the live probe handle it

    try:
        block = _build_block(interp, project_dir, prompt)
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
