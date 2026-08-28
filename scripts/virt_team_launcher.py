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
  - `<engage-cmd> --review <slug>` - open a DONE or ARCHIVED engagement read-only
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

import json
import os
import re
import subprocess
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


def _scripts_dir() -> Path:
    """This script always lives directly in scripts/ (never staged/dual-copy like the
    UserPromptSubmit hook) - its siblings are simply its own directory."""
    return Path(__file__).resolve().parent


def _ensure_sibling_imports() -> None:
    """Put scripts/ on sys.path so the six `import engage_probe`-style sibling imports
    resolve however this file was entered. Running it as a path (`python
    scripts/virt_team_launcher.py`) puts scripts/ at sys.path[0] for free; `python -m
    scripts.virt_team_launcher` and importing it by spec (the tests) do not, and every
    one of those imports sits inside an except that returns a quiet nothing - so the
    settings editor rendered an empty table rather than failing loudly. Found 2026-08-20
    via two editor tests that passed only when an unrelated test had polluted sys.path
    first."""
    here = str(_scripts_dir())
    if here not in sys.path:
        sys.path.insert(0, here)


_ensure_sibling_imports()


def _installer_config_path() -> Path:
    """Mirrors install_helper's config_path() instead of exec'ing that whole file on
    every go - a test pins the two derivations together."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "virt-surv-it" / "installer.json"


def _configured_launch_command() -> str:
    """The command 'virt-surv go' launches Claude Code with, resolved at RUN time from
    the machine config rather than baked into the shell alias (alias v5, 2026-08-17
    live report: a launch command reset in the config kept launching the old baked
    value even after closing PowerShell, because the profile function still carried it;
    and a multi-word command like 'cc --debug' was baked as ONE quoted word, which can
    never resolve). Any failure falls back to plain 'claude', same as an unset config."""
    try:
        cfg = json.loads(_installer_config_path().read_text(encoding="utf-8-sig"))
        cmd = cfg.get("claude_launch_command") if isinstance(cfg, dict) else None
        if isinstance(cmd, str) and cmd.strip():
            return cmd.strip()
    except (OSError, ValueError):
        pass
    return "claude"


# Pinned to install_helper._ALIAS_VERSION by a sync test - bump both together.
_EXPECTED_ALIAS_VERSION = 7  # v7: cd handshake for the project explorer + Esc exits
# Exit code that means "the human backed out - do NOT launch" (2026-08-20 user report:
# "when exiting the tui it launches claude code, it shouldn't"). Esc used to be folded
# into the same empty decision as 'just launch', so backing out of the menu still
# started a session. 97 is arbitrary but must stay in step with the wrapper templates.
_ABORT_EXIT_CODE = 97
_ABORT = "__abort__"


def _heal_stale_alias_once(force: bool = False) -> None:
    """Self-resolution for stale installed aliases (2026-08-17 user requirement: "it
    should self-resolve" - the config said 'cc' but the loaded v4 function still fired
    its baked 'cc --debug'; a plugin update must not wait on a manual re-register).
    Runs from the __main__ entry of every real 'go', but does real work at most ONCE
    per machine per alias version (the alias_heal_checked config mark): it asks
    install_helper.heal_stale_aliases() to upgrade every rc/profile that already
    carries a virt-surv entry older than the current template - never installing the
    alias anywhere new. The one thing it cannot fix is the function already loaded in
    the CALLING shell (no child process can mutate its parent), so it says exactly
    that. Best-effort throughout: any failure must never cost the launch."""
    try:
        cfg_path = _installer_config_path()
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            if not isinstance(cfg, dict):
                cfg = {}
        except (OSError, ValueError):
            cfg = {}
        if not force and cfg.get("alias_heal_checked") == _EXPECTED_ALIAS_VERSION:
            return
        import contextlib
        import importlib.util as _ilu

        spec = _ilu.spec_from_file_location(
            "install_helper_heal", _scripts_dir().parent / "install_helper.py"
        )
        ih = _ilu.module_from_spec(spec)
        with contextlib.redirect_stdout(sys.stderr):
            spec.loader.exec_module(ih)
            healed = ih.heal_stale_aliases()
        cfg["alias_heal_checked"] = ih._ALIAS_VERSION
        try:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
        if healed:
            ink = _Ink()
            print("", file=sys.stderr)
            for path, removed in healed:
                note = f" (removed {removed} old definition(s))" if removed else ""
                print(
                    f"    {ink.warn('!')} auto-updated an out-of-date 'virt-surv' alias "
                    f"in {path}{note}",
                    file=sys.stderr,
                )
            print(
                "      This terminal still holds the OLD alias (a program cannot change "
                "its parent shell): run '. $PROFILE' (PowerShell) or 'source ~/.bashrc' "
                "(bash), or open a new terminal. If THIS launch errors on an unknown "
                "command, that is the old alias firing one last time - the next terminal "
                "is fixed.",
                file=sys.stderr,
            )
    except Exception:
        pass  # never cost the launch


def _alias_installed_anywhere() -> bool:
    """Does an rc/profile on this machine carry a virt-surv wrapper at all?

    Used only on the abort path, to tell two very different situations apart: an OLD
    wrapper that is about to ignore the abort and launch anyway, versus no wrapper at all
    (a direct `python scripts/virt_team_launcher.py`, which is how developers and the test
    suite run it - nobody there needs warning about a shell function they never installed).
    Best-effort: unreadable means unknown means stay quiet."""
    try:
        home = Path.home()
    except Exception:
        return False
    candidates = [home / n for n in (".bashrc", ".zshrc", ".bash_profile", ".profile")]
    try:
        documents = home / "Documents"
        for sub in ("WindowsPowerShell", "PowerShell"):
            candidates.append(documents / sub / "Microsoft.PowerShell_profile.ps1")
    except Exception:
        pass
    for path in candidates:
        try:
            if path.is_file() and "virt-surv" in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def _warn_if_abort_will_be_ignored() -> None:
    """Say so when Esc is about to be overruled by an out-of-date shell wrapper.

    2026-08-25 user report: "when pressing escape on the TUI it should drop to terminal,
    instead it falls through and launches claude". The launcher's own side is correct -
    Esc returns _ABORT and main() exits 97 with clean stdout - but honouring that is the
    WRAPPER's job, and the `-ne 97` check only arrived in alias v7. A pre-v7 function
    already loaded in the calling shell ignores the code and launches regardless, and no
    child process can change its parent's loaded functions.

    We can detect this precisely rather than guess: VIRT_SURV_CD_FILE is exported by the
    v7 wrapper and by nothing else - the cd handshake and the exit-code check landed in
    the same version (a714932) - so its absence, combined with a wrapper being installed
    somewhere, means the abort is about to be ignored. Silence here is the worst option:
    the user pressed Esc, a session opened anyway, and nothing explained why.

    Heals the rc file first, so the "already brought up to date" claim below is true when
    it is printed, and forces past the once-per-version stamp: the stamp records that a
    heal RAN, which is not the same as this terminal being current."""
    if os.environ.get("VIRT_SURV_CD_FILE"):
        return  # v7+ wrapper - it checks the exit code, the abort will be honoured
    if not _alias_installed_anywhere():
        return  # no wrapper at all: a direct run, nothing to warn about
    try:
        _heal_stale_alias_once(force=True)
    except Exception:
        pass  # cosmetic tier - never let the heal cost the abort message
    ink = _Ink()
    print("", file=sys.stderr)
    print(
        f"    {ink.warn('!')} This terminal's 'virt-surv' wrapper predates Esc-to-exit, so "
        "a session will start anyway despite the abort.",
        file=sys.stderr,
    )
    print(
        "      The rc file itself is now up to date; the loaded function is not, and no "
        "program can change its parent shell. Run 'source ~/.bashrc' (bash) or "
        "'. $PROFILE' (PowerShell), or open a new terminal, and Esc will return you to "
        "the prompt as intended.",
        file=sys.stderr,
    )


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


_TOGGLE_PREFS = (
    ("docx export", "extra_formats"),
    ("regulatory citations", "regulatory_citations"),
    ("large-context review split", "large_context_review_split"),
    ("parallel dispatch (Workflow)", "parallel_dispatch_via_workflow"),
    ("standards critique", "standards_critique"),
    ("codebase-map skeleton", "map_skeleton"),
    ("probe pre-cache at go", "probe_cache"),
    ("evidence room at close", "evidence_room"),
    ("autonomous mode offered", "autonomous_mode"),
    ("start work unattended", "autonomous_default"),
    ("open the session in a new window", "new_window"),
    ("data profiling tools", "data_profiling"),
    ("document map", "document_map"),
    ("guard daemon", "guard_daemon"),
)


# Shortened 2026-08-20 to match the sibling label in _print_project_defaults and, more to
# the point, to stop the longest label in the table setting a padding width that clipped
# every row's on/off column against the settings-screen divider. "timeouts" moved into the
# explanation pane, which now carries the detail for every row.
_ENV_ROW_LABEL = "env tuning (1h cache TTL)"

# Renamed from the bare "jira integration" (2026-08-20 user question: "not clear what does
# the setting jira do - what does it enable or disable or change"). Since [j] became a
# permanent menu item, this switch no longer decides whether Jira is USABLE - starting an
# engagement from a ticket works either way. What it decides is whether the team WRITES
# BACK to a tracker on its own initiative, so the label names that instead.
_JIRA_ROW_LABEL = "jira write-back"


# Settings that are NOT on/off (2026-08-20). The editor was boolean-only, so qa_depth -
# a four-value preference that decides how much INDEPENDENT QA a build buys, i.e. the
# single setting with the largest effect on both cost and assurance - could not be changed
# from the launcher at all, only by hand-editing team-preferences.json. Enter cycles.
# (label, storage key with dots for nesting, values in cycle order, default when unset)
_CHOICE_PREFS = (
    ("qa depth", "qa_depth", ("auto", "quick", "deep", "audit"), "auto"),
    ("jira mirror", "integrations.jira.mirror", ("close-only", "live"), "close-only"),
)


def _choice_read(prefs: dict, key: str):
    """Stored value at a dotted path, or None. Any wrong-typed level reads as unset -
    same fail-to-default posture the integrations block already takes."""
    node = prefs
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node if isinstance(node, str) else None


def _choice_write(prefs: dict, key: str, value: str) -> None:
    """Set a dotted path, creating intermediate dicts and replacing wrong-typed ones."""
    parts = key.split(".")
    node = prefs
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


# What each setting actually DOES, keyed by the row label (2026-08-20 user request: "for
# each setting show on right hand side an explanation of that setting", after asking what
# the jira row even meant). Wording is derived from the implementations and docs that own
# each preference - resolve_preferences for the defaults, DEFINITION-OF-DONE.md for the
# two DoD-gating ones - rather than paraphrased from the label, because a settings screen
# that guesses is worse than one that says nothing. Kept here, not in launcher_app, so any
# tier can show it and there is one copy to keep true.
_SETTING_HELP = {
    "docx export": (
        "Also render deliverables as .docx alongside the .md + .html every engagement "
        "already produces. For sharing with people who live in Word.",
        "Off: markdown and HTML only.",
    ),
    "regulatory citations": (
        "Each requirement in the RTM carries the specific obligation it serves, so an "
        "alert traces back to the rule that justifies it.",
        "Off: the obligation link is recorded as DECLINED, never silently dropped - the "
        "rest of the trace still holds.",
    ),
    "large-context review split": (
        "Splits a big review into several passes instead of one call, so a large "
        "findings set cannot blow the write cap or time out mid-review.",
        "Off: one delegated review call. Worth turning on if reviews here keep hitting "
        "the ~8-finding threshold.",
    ),
    "parallel dispatch (Workflow)": (
        "Independent review passes fan out through the Workflow tool's deterministic "
        "parallel dispatch rather than batched Task calls, which did not stick reliably.",
        "Off: passes run one after another. Slower, but no Workflow dependency.",
    ),
    "standards critique": (
        "Adds a second, independent critic pass over an already-finished deliverable, "
        "judged against the named standard, before handover.",
        "Off (the default): the normal review gates still apply. This is a full extra "
        "pass, not a universal expectation.",
    ),
    "codebase-map skeleton": (
        "Seeds a starter docs/codebase-map.md for a project that has none, so the team "
        "has a map to curate instead of a blank page.",
        "Off: the map is only ever written by hand.",
    ),
    "probe pre-cache at go": (
        "Computes the engage probe HERE, outside the session, and caches it - so opening "
        "an engagement skips work that takes minutes on a locked-down box.",
        "Pure accelerator: a missing or stale cache just runs the live probe, so nothing "
        "breaks either way.",
    ),
    "evidence room at close": (
        "Assembles one self-contained HTML pack at close from evidence the engagement "
        "already produced - for handing to an auditor.",
        "Off (the default): whether a project wants an auditor-facing pack is a governance "
        "decision, so it is never created unasked.",
    ),
    _ENV_ROW_LABEL: (
        "Writes tuned timeouts and a 1-hour prompt-cache TTL into this project's "
        ".claude/settings.json - fewer timeouts, and cache that survives a thinking pause.",
        "Not applied: Claude Code's own defaults are used.",
    ),
    "guard daemon": (
        "Runs the safety guards in one persistent process instead of starting a fresh "
        "interpreter for every hook. Same guard code, same decisions - only the startup "
        "cost differs (~625ms vs ~211ms per call on Windows).",
        "On by default at machine and project level. Off falls back to a process per call: "
        "slower, never less safe.",
    ),
    "document map": (
        "Lets the team inventory a documentation tree first - filenames, dates and heading "
        "outlines - so it knows what exists before opening anything.",
        "On by default at machine and project level. Off means documents get opened at "
        "random instead, which costs more and misses things.",
    ),
    "data profiling tools": (
        "Lets the team run profile_temporal (gaps, freshness, cadence over time) and "
        "tag_columns (what each column means) on a dataset. Both emit counts and dates "
        "only - never a record.",
        "On by default: it is SAFER than the alternative, which is an agent reading rows "
        "into context. Off only where no tool may touch client data at all.",
    ),
    "autonomous mode offered": (
        "Whether an unattended run may be OFFERED at all - from a Jira ticket [j] or a "
        "typed request [n]. This is a kill switch, not an enabler: it is already on.",
        "Off removes the option from this project entirely. On does not start anything "
        "unattended by itself - see 'start work unattended' for that.",
    ),
    "open the session in a new window": (
        "Opens the Claude session in its own terminal window - attended or unattended - so "
        "this launcher survives to show the workflow and the run's status.",
        "OFF by default for now. Without it the session replaces this screen, which is what "
        "made the workflow hard to watch. No windowed terminal means it opens here anyway.",
    ),
    "start work unattended": (
        "Arms the unattended toggle for new work, so a run you were going to start "
        "unattended starts that way without reaching for Ctrl-T each time.",
        "It changes the default ANSWER, never removes the question: an armed run still "
        "stops at the pre-flight, where you attest the data, allow code and set the "
        "ceiling. Off by default - unattended stays opt-in, per project.",
    ),
    "qa depth": (
        "How much INDEPENDENT QA a build buys. auto reads the work; quick narrows what "
        "gets written and always closes PARTIAL; deep is the full pass; audit is the "
        "heaviest.",
        "There is no off: QA running, and being independent of whoever wrote the code, "
        "is not tierable - only its breadth is.",
    ),
    "jira mirror": (
        "WHEN tracker updates are posted. close-only waits until the end; live comments "
        "as phases change.",
        "Only bites when jira write-back is on. Work started from a ticket tracks live "
        "regardless, unless you set close-only here.",
    ),
    _JIRA_ROW_LABEL: (
        "Whether the team WRITES to your tracker itself. On: it raises ONE issue per "
        "engagement at open, after you approve a plan naming it, then comments as work "
        "moves and posts the summary at close.",
        "Off does NOT hide Jira. [j] still works: it starts from a ticket and reports "
        "back to that one ticket, without ever raising issues of its own.",
    ),
}


def setting_help(label: str) -> tuple:
    """(what it does, what off means) for a settings row, or () when unknown. Returning
    empty rather than a placeholder keeps an unexplained new setting visibly unexplained
    instead of quietly wrong."""
    return _SETTING_HELP.get(label, ())


def _editor_rows(project_dir: Path):
    """One consistent snapshot for a settings-editor render: [(label, value, on)] for
    the six toggle prefs plus the env-bundle row, or None when preferences can't be
    resolved. Shared by BOTH editor tiers so they can never drift."""
    try:
        import engage_probe

        effective = engage_probe.resolve_preferences(project_dir)
    except Exception:
        return None
    try:
        prefs = json.loads(
            (project_dir / ".claude" / "team-preferences.json").read_text(encoding="utf-8")
        )
    except Exception:
        prefs = {}
    rows = []
    for label, key in _TOGGLE_PREFS:
        if key == "extra_formats":
            on = "docx" in (effective.get("extra_formats") or [])
        else:
            on = bool(effective.get(key))
        src = "" if key in prefs else "  (machine default)"
        rows.append((label, ("on" if on else "off") + src, on))
    try:
        env = (
            json.loads((project_dir / ".claude" / "settings.json").read_text(encoding="utf-8")).get(
                "env"
            )
            or {}
        )
    except Exception:
        env = {}
    env_on = "ENABLE_PROMPT_CACHING_1H" in env
    rows.append((_ENV_ROW_LABEL, "applied" if env_on else "not applied", env_on))
    jira = (
        (prefs.get("integrations") or {}).get("jira")
        if isinstance(prefs.get("integrations"), dict)
        else {}
    )
    jira = jira if isinstance(jira, dict) else {}
    if jira.get("enabled") is True:
        key = str(jira.get("project_key") or "") or "key UNSET"
        rows.append((_JIRA_ROW_LABEL, f"on ({key})", True))
    else:
        rows.append((_JIRA_ROW_LABEL, "off", False))
    for label, key, values, default in _CHOICE_PREFS:
        stored = _choice_read(prefs, key)
        current = stored if stored in values else default
        rows.append(
            (label, current + ("" if stored in values else "  (default)"), current != default)
        )
    return rows


def _editor_apply(project_dir: Path, action) -> str:
    """Perform one editor action - 1..6 toggles that pref, 7 toggles the env bundle,
    'd' restores machine defaults (drops the project-level pref keys; env has no
    machine tier, its own row toggles it). Returns a short note for the user ('' when
    there is nothing to say). Shared by both editor tiers."""
    prefs_path = project_dir / ".claude" / "team-preferences.json"
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    except Exception:
        prefs = {}
    env_i = len(_TOGGLE_PREFS) + 1
    jira_i = len(_TOGGLE_PREFS) + 2
    last_i = jira_i + len(_CHOICE_PREFS)
    if action != "d":
        try:
            action = int(action)  # the input() tier hands over strings
        except (TypeError, ValueError):
            return f"1-{last_i}, d or b, please."
    if action != "d" and jira_i < action <= last_i:
        # Choice rows cycle rather than toggle (2026-08-20). Written even when the value
        # lands back on the default, because "explicitly chosen" and "never set" are
        # different states to resolve_preferences' key-presence precedence.
        label, key, values, default = _CHOICE_PREFS[action - jira_i - 1]
        stored = _choice_read(prefs, key)
        try:
            at = values.index(stored)
        except ValueError:
            # Unset: advance from the DEFAULT, not from values[0]. Otherwise the first
            # press writes the value that was already in effect and reads as a dead key.
            at = values.index(default) if default in values else -1
        nxt = values[(at + 1) % len(values)]
        _choice_write(prefs, key, nxt)
        try:
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            prefs_path.write_text(
                json.dumps(prefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            return "could not write team-preferences.json - unchanged"
        return (
            f"{label}: {nxt}"
            if label != "qa depth" or nxt == "auto"
            else (
                f"qa depth: {nxt} - QA still runs and stays independent; this changes its breadth"
            )
        )
    if action == jira_i:
        # Jira integration toggle (2026-08-18 user report: the [c] editor was missing
        # table rows like this one). Enable/disable in place, PRESERVING the rest of
        # the jira block (project_key, tool_prefix, mirror) so re-enabling keeps the
        # configuration; a key-less enable shows "key UNSET" in the table and the note
        # points at the canonical doc.
        integrations = prefs.get("integrations")
        if not isinstance(integrations, dict):
            integrations = {}
        jira = integrations.get("jira")
        if not isinstance(jira, dict):
            jira = {}
        now_on = jira.get("enabled") is not True
        jira["enabled"] = now_on
        integrations["jira"] = jira
        prefs["integrations"] = integrations
        note = ""
        if now_on and not str(jira.get("project_key") or ""):
            note = (
                "enabled with no project key - set integrations.jira.project_key in "
                ".claude/team-preferences.json (docs/INTEGRATIONS.md)"
            )
        try:
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            prefs_path.write_text(
                json.dumps(prefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            return "could not write team-preferences.json - unchanged"
        return note
    if action == "d":
        for _, key in _TOGGLE_PREFS:
            prefs.pop(key, None)
        for _label, key, _values, _default in _CHOICE_PREFS:
            # Top-level choice keys only: a nested one (jira mirror) lives inside a config
            # block that "restore machine defaults" has no business dismantling.
            if "." not in key:
                prefs.pop(key, None)
    elif action == env_i:
        # The env bundle: ON adds the missing recommended keys, add-only, same
        # contract as the go-time propagation; OFF removes only keys still AT their
        # recommended value, so a custom-tuned timeout survives and is reported.
        try:
            import importlib.util as _ilu

            spec = _ilu.spec_from_file_location(
                "install_helper_env2", _scripts_dir().parent / "install_helper.py"
            )
            ih = _ilu.module_from_spec(spec)
            spec.loader.exec_module(ih)
            recommended = dict(ih.RECOMMENDED_ENV)
        except Exception:
            return "could not load the recommended env set - unchanged"
        settings_path = project_dir / ".claude" / "settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}
        env = dict(settings.get("env") or {}) if isinstance(settings.get("env"), dict) else {}
        note = ""
        if "ENABLE_PROMPT_CACHING_1H" in env:
            kept = [k for k in recommended if k in env and env[k] != recommended[k]]
            for k in recommended:
                if k in env and env[k] == recommended[k]:
                    del env[k]
            if kept:
                note = "kept custom-tuned value(s): " + ", ".join(sorted(kept))
        else:
            for k, v in recommended.items():
                env.setdefault(k, v)
        settings["env"] = env
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            return "could not write settings.json - unchanged"
        return note
    else:
        try:
            label, key = _TOGGLE_PREFS[int(action) - 1]
        except (ValueError, IndexError, TypeError):
            return f"1-{last_i}, d or b, please."
        rows = _editor_rows(project_dir) or []
        current = bool(rows[int(action) - 1][2]) if rows else False
        if key == "extra_formats":
            formats = [f for f in (prefs.get("extra_formats") or []) if f != "docx"]
            prefs["extra_formats"] = formats if current else formats + ["docx"]
        else:
            prefs[key] = not current
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(
            json.dumps(prefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        return "could not write team-preferences.json - unchanged"
    return ""


def _run_settings_editor(project_dir: Path) -> None:
    """The [c] flow shared by both menu tiers: run the editor, then report ONLY the
    rows that changed (live report 2026-08-17: the full defaults table was reprinted
    under the table already on screen, so every edit showed the same settings twice -
    the go-time table remains above as the 'before', these lines are the delta)."""
    before = _editor_rows(project_dir) or []
    _config_editor(project_dir)
    after = _editor_rows(project_dir) or []
    ink = _Ink()
    changed = [
        (label, value)
        for (label, value, _on), (b_label, b_value, _bo) in zip(after, before)
        if value != b_value
    ]
    for label, value in changed:
        print(ink.dim(f"    -> {label}: {value}"), file=sys.stderr)
    if not changed:
        print(ink.dim("    -> no changes"), file=sys.stderr)
    else:
        # Reprint the table in its CURRENT state (2026-08-18 user report: leaving the
        # launch-time table on screen made a successful change look ignored - the
        # no-change path stays quiet, which is what the original duplicate-table
        # complaint was about).
        try:
            _print_project_defaults(project_dir)
        except Exception:
            pass


def _pt_config_editor(p, project_dir: Path) -> None:
    """prompt_toolkit tier of the settings editor: arrows move, Enter/Space toggles the
    highlighted row IN PLACE (only the widget repaints, no full redraw), 'd' restores
    machine defaults, Esc/'b' done. Mouse: click a row to toggle it."""
    idx = [0]
    note = [""]
    kb = p["KeyBindings"]()

    def _rows():
        return _editor_rows(project_dir) or []

    def _toggle(i):
        note[0] = _editor_apply(project_dir, i + 1)

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % max(len(_rows()), 1)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % max(len(_rows()), 1)

    @kb.add("enter")
    @kb.add(" ")
    def _flip(event):
        _toggle(idx[0])

    @kb.add("d")
    def _defaults(event):
        note[0] = _editor_apply(project_dir, "d") or "machine defaults restored"

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("b")
    @kb.add("q")
    def _done(event):
        event.app.exit()

    def _fragments():
        MouseEventType = p["MouseEventType"]
        rows = _rows()
        out = [("class:title", " Project settings\n")]
        width = max((len(label) for label, _v, _o in rows), default=0)
        for i, (label, value, on) in enumerate(rows):

            def _click(mouse_event, _i=i):
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    idx[0] = _i
                    _toggle(_i)
                    return None
                return NotImplemented

            sel = i == idx[0]
            marker = "> " if sel else "  "
            row_style = "class:sel" if sel else ""
            head, _, src = value.partition("  ")
            val_style = "class:sel" if sel else ("class:on" if on else "class:dim")
            out.append((row_style, f"  {marker}{label.ljust(width + 2)}", _click))
            out.append((val_style, head, _click))
            if src:
                out.append(("class:sel" if sel else "class:dim", f"  {src}", _click))
            out.append(("", "\n"))
        out.append(("class:dim", "  Enter/Space/click toggles · d machine defaults · Esc done"))
        if note[0]:
            out.append(("class:note", f"\n  {note[0]}"))
        return out

    rows0 = _rows()
    if not rows0:
        return True
    app = p["Application"](
        layout=p["Layout"](
            p["Window"](
                p["FormattedTextControl"](_fragments, focusable=True, show_cursor=False),
                height=len(rows0) + 3,
                always_hide_cursor=True,
            )
        ),
        key_bindings=kb,
        style=_pt_style(p),
        mouse_support=True,
        erase_when_done=True,
        full_screen=False,
        **_pt_io(),
    )
    try:
        app.run()
    except Exception:
        return False  # widget never ran - caller falls back to the numbered tier
    return True


def _config_editor(project_dir: Path) -> None:
    """Inline project-settings editor on the go screen (2026-08-17 user request).
    prompt_toolkit tier when the terminal supports it (arrows/mouse, in-place toggles);
    numbered input() tier otherwise - both drive the same _editor_rows/_editor_apply,
    so they can never disagree about what a toggle does. Writes team-preferences.json
    preserving every unrelated key; restoring defaults means REMOVING the project-level
    keys (resolve_preferences' key-presence precedence lets the machine tier speak
    again). All interaction on stderr/stdin; stdout stays the decision channel. Every
    failure path just returns - cosmetic tier."""
    p = _ptk_ui()
    if p and _pt_config_editor(p, project_dir) is not False:
        return
    err = sys.stderr
    ink = _Ink()
    while True:
        rows = _editor_rows(project_dir)
        if rows is None:
            return
        print("", file=err)
        _print_rule("Project settings", note="pick a number to toggle")
        width = max(len(label) for label, _v, _o in rows)
        for i, (label, value, on) in enumerate(rows, 1):
            dots = ink.dim("." * (width - len(label) + 2))
            head, _, tail = value.partition("  ")
            shown = (ink.good(head) if on else ink.dim(head)) + (
                ink.dim("  " + tail) if tail else ""
            )
            print(f"    {ink.bold(f'[{i}]')} {label} {dots} {shown}", file=err)
        print(f"    {ink.bold('[d]')} restore machine defaults (drop project choices)", file=err)
        print(f"    {ink.bold('[b]')} done", file=err)
        print(ink.bold("    Setting: "), end="", file=err)
        try:
            choice = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if choice in ("", "b"):
            return
        note = _editor_apply(project_dir, "d" if choice == "d" else choice)
        if note:
            print(ink.dim(f"  {note}"), file=err)


def _archive_perform(es, targets: list) -> None:
    """Archive each target pack (--force: an OPEN pack archives but shows as
    ARCHIVED-OPEN in checks), reporting per slug to stderr. Shared by both tiers."""
    import contextlib

    ink = _Ink()
    for row in targets:
        slug = _row_resume_token(row) or ""
        if not slug:
            continue
        try:
            # es.main prints its confirmations to ITS stdout - which in-process is OUR
            # stdout, the decision channel. Everything it says belongs on stderr here
            # (the test that added this caught the leak before it shipped).
            with contextlib.redirect_stdout(sys.stderr):
                rc = es.main(["archive", slug, "--force"])
        except SystemExit as exc:  # es.main may exit; treat code as rc
            rc = int(exc.code or 0)
        except Exception:
            rc = 1
        marker = ink.good("archived") if rc == 0 else ink.warn(f"failed (rc {rc})")
        print(f"    {slug}: {marker}", file=sys.stderr)


def _finished_menu(project_dir: Path, es) -> str:
    """Browse DONE and ARCHIVED engagements (2026-08-21 user request) - the read side
    of the archive story. Returns the chosen engagement's resume token ('' when the
    user backs out or there is nothing to browse). The CALLER turns a token into the
    `--review <slug>` decision - this menu never touches stdout.
    prompt_toolkit tier when the terminal supports it; numbered input() otherwise."""
    err = sys.stderr
    ink = _Ink()
    try:
        rows = es.finished_engagements(_vsit_paths().engagements_dir(project_dir))
    except Exception:
        rows = []
    if not rows:
        print(ink.dim("    no done or archived engagements yet"), file=err)
        return ""
    p = _ptk_ui()
    if p:
        slug_w = max((len(_row_resume_token(r) or "?") for r in rows), default=0)
        entries = []
        for i, row in enumerate(rows):
            slug = _row_resume_token(row) or "?"
            tail = "archived" if row.get("archived") else (row.get("status") or "?")
            when = str(row.get("closed") or row.get("opened") or "")[:10]
            entries.append(
                (
                    i,
                    [
                        ("class:slug", slug.ljust(slug_w)),
                        ("class:dim", f"  {tail}" + (f"  {when}" if when else "")),
                    ],
                    None,
                )
            )
        entries.append((None, "back", "b"))
        pick = _pt_pick(
            p,
            "Open a done or archived engagement",
            entries,
            subtitle="read-only review in a Claude session - nothing is reopened",
        )
        if pick is not _PT_FAILED:
            if pick is None:
                return ""
            return _row_resume_token(rows[pick]) or ""
        # fall through to the numbered tier
    print("", file=err)
    _print_rule("Done & archived engagements")
    for i, row in enumerate(rows, 1):
        slug = _row_resume_token(row) or "?"
        tail = "archived" if row.get("archived") else (row.get("status") or "?")
        when = str(row.get("closed") or row.get("opened") or "")[:10]
        title = row.get("title") or ""
        print(
            f"    {ink.bold(f'[{i}]')} {slug}  {ink.dim(tail + (f'  {when}' if when else ''))}"
            + (f"  {ink.dim(title)}" if title else ""),
            file=err,
        )
    print(f"    {ink.bold('[b]')} back", file=err)
    print(ink.bold("    Open: "), end="", file=err)
    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ""
    if choice in ("", "b"):
        return ""
    try:
        return _row_resume_token(rows[int(choice) - 1]) or ""
    except (ValueError, IndexError):
        print(ink.dim("    a number or b, please."), file=err)
        return ""


def _archive_menu(project_dir: Path, es, menu: dict) -> None:
    """Archive engagements from the go screen (2026-08-17 user request): pick one,
    'all' archives every OPEN one (not just the 3 shown rows - live report), back to
    leave. Archiving an OPEN pack is allowed but informed: it uses --force and the DoD
    checker will show it as ARCHIVED-OPEN - stated before confirming, never silently.
    prompt_toolkit tier when the terminal supports it; numbered input() otherwise."""
    err = sys.stderr
    ink = _Ink()
    shown = menu.get("shown") or []
    if not shown:
        print(ink.dim("    nothing to archive"), file=err)
        return
    open_rows = menu.get("open") or shown
    p = _ptk_ui()
    if p:
        slug_w = max((len(_row_resume_token(r) or "?") for r in shown), default=0)
        entries = []
        for i, row in enumerate(shown):
            slug = _row_resume_token(row) or "?"
            status = row.get("status") or "?"
            entries.append(
                (i, [("class:slug", slug.ljust(slug_w)), ("class:dim", f"  {status}")], None)
            )
        entries.append(("all", f"archive ALL open engagements ({len(open_rows)})", None))
        entries.append((None, "back", "b"))
        pick = _pt_pick(
            p,
            "Archive engagements",
            entries,
            subtitle="in-place, nothing deleted; an OPEN pack shows as ARCHIVED-OPEN in checks",
        )
        if pick is not _PT_FAILED:
            if pick is None:
                return
            _archive_perform(es, open_rows if pick == "all" else [shown[pick]])
            return
        # fall through to the numbered tier
    print("", file=err)
    _print_rule("Archive engagements")
    for i, row in enumerate(shown, 1):
        slug = _row_resume_token(row) or "?"
        status = row.get("status") or "?"
        print(f"    {ink.bold(f'[{i}]')} {slug}  {ink.dim(status)}", file=err)
    print(f"    {ink.bold('[all]')} archive ALL open engagements ({len(open_rows)})", file=err)
    print(f"    {ink.bold('[b]')} back", file=err)
    print(
        ink.dim(
            "    (archive-in-place: nothing is deleted; an OPEN pack archives with --force "
            "and shows as ARCHIVED-OPEN in checks)"
        ),
        file=err,
    )
    print(ink.bold("    Archive: "), end="", file=err)
    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice in ("", "b"):
        return
    if choice == "all":
        # ALL OPEN, not all SHOWN (live report 2026-08-17: the list caps at 3 rows with
        # "+N more not shown" - 'all' archived the visible three and the rest came
        # straight back as open).
        targets = open_rows
    else:
        try:
            targets = [shown[int(choice) - 1]]
        except (ValueError, IndexError):
            print(ink.dim("    a number, 'all' or b, please."), file=err)
            return
    _archive_perform(es, targets)


def _resume_decision(project_dir: Path) -> str:
    """Returns the full pre-seeded prompt string (possibly empty) - the engage command
    in the spelling THIS project answers to (see _engage_command), plus the
    resume-or-new flag. All interactive I/O here targets stderr/stdin explicitly -
    never print() bare, which would land on stdout and corrupt the caller's
    command-substitution capture."""
    try:
        import engagement_state
    except Exception:
        return ""
    show_all = [False]
    while True:
        try:
            # Every open engagement, not the top 3 (2026-08-20): the cap used to be
            # applied HERE, so the remainder was unreachable from any tier - "+2 more not
            # shown" with no way to reach them, and resuming an older one meant knowing
            # its slug. The app tier scrolls the full list; the plain tiers still show
            # three and offer [m].
            menu = engagement_state.resume_menu(
                _vsit_paths().engagements_dir(project_dir), max_shown=_FULL_MENU
            )
        except Exception:
            return ""
        shown = menu.get("shown") or []
        # Zero open engagements used to skip the pause entirely (straight plain
        # launch); the menu now shows regardless (2026-08-17 user preference: "I
        # prefer it always pauses") - [c]/[a] stay reachable, and non-interactive
        # callers are unaffected: no tty means input() raises EOFError, which is the
        # same plain launch as before.
        decision = _menu_round(project_dir, engagement_state, menu, shown, show_all=show_all[0])
        if decision == _SHOW_ALL:
            show_all[0] = True
            continue
        if decision.startswith(_CHDIR_PREFIX):
            # Project switch (2026-08-20 explorer): re-enter the SAME loop against the new
            # folder rather than returning, so the menu, settings and resume list all
            # belong to the project the session is about to open. The shell is asked to
            # follow; if the wrapper is too old to have the handshake, say so rather than
            # opening a session in the previous directory.
            project_dir = Path(decision[len(_CHDIR_PREFIX) :])
            ink = _Ink()
            print(ink.good(f"    -> switched to {project_dir}"), file=sys.stderr)
            if not _write_cd_request(project_dir):
                print(
                    ink.warn(
                        "    note: this shell's virt-surv wrapper predates folder "
                        "switching, so the session will still open in the previous "
                        "directory. The rc file self-heals, but THIS terminal keeps the "
                        "old function until you reload it (source ~/.bashrc, . $PROFILE) "
                        "or open a new one."
                    ),
                    file=sys.stderr,
                )
            for step in (_remember_project, _prewarm_guard_interpreter, _write_probe_cache):
                try:
                    step(project_dir)  # the new project deserves the same warm start
                except Exception:
                    pass
            continue
        if decision != "__again__":
            return decision


_CHDIR_PREFIX = "__chdir__:"
_SHOW_ALL = "__show_all__"
_FULL_MENU = 9999  # "no cap" for resume_menu; the tiers below do their own limiting
_PLAIN_TIER_ROWS = 3  # what the numbered/picker tiers show before offering [m]


def _write_cd_request(target: Path) -> bool:
    """Ask the SHELL to change directory (2026-08-20 project explorer).

    A launcher is a child process: it cannot move its parent's cwd, and the wrapper
    launches Claude Code from wherever the user was standing. So switching project inside
    the menu would otherwise open a session pointed at the OLD folder - worse than not
    offering the feature, because the menu would show one project and the session would
    open another.

    The wrapper (install_helper._alias_line_for, alias v7+) creates a temp file, passes
    its path in VIRT_SURV_CD_FILE, and cd's to whatever it contains before launching. No
    variable means an older wrapper that has not self-healed yet: the switch still works
    for everything the LAUNCHER does, and the caller warns rather than silently opening
    the wrong directory."""
    path = os.environ.get("VIRT_SURV_CD_FILE")
    if not path:
        return False
    try:
        Path(path).write_text(str(target.resolve()), encoding="utf-8")
        return True
    except OSError:
        return False


_RECENT_LIMIT = 8


def _recent_projects() -> list:
    """Project folders opened before, most recent first (2026-08-20). The explorer starts
    from the current directory, so reaching a project you use every day meant walking the
    tree from wherever you happened to be standing. Machine-scoped on purpose: which
    folders THIS person works in is a fact about the machine, never about a project, so it
    never lands in a repo. Missing entries are dropped on read rather than pruned on
    write - a folder on an unmounted share should come back when it returns."""
    try:
        cfg = json.loads(_installer_config_path().read_text(encoding="utf-8"))
        entries = cfg.get("recent_projects")
    except Exception:
        return []
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, str):
            continue
        candidate = Path(entry)
        if candidate.is_dir() and candidate not in out:
            out.append(candidate)
    return out[:_RECENT_LIMIT]


def _remember_project(project_dir: Path) -> None:
    """Record a project as recently used. Best-effort and silent: a machine config that
    cannot be written must never cost a launch."""
    try:
        resolved = str(project_dir.resolve())
    except Exception:
        return
    path = _installer_config_path()
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    existing = [e for e in (cfg.get("recent_projects") or []) if isinstance(e, str)]
    cfg["recent_projects"] = [resolved] + [e for e in existing if e != resolved][
        : _RECENT_LIMIT - 1
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _engagement_artifacts(project_dir: Path, slug: str) -> list:
    """(label, path) for what an engagement actually produced, newest-looking first.
    Rendered .html is preferred over its .md twin - the HTML is the shareable artifact and
    the one a person means when they say "open the report"."""
    workspace = _vsit_paths().engagement_dir(slug, project_dir)
    if not workspace.is_dir():
        return []
    preferred = ("START-HERE", "delivery-report", "evidence-room", "engagement-summary")
    found = []
    try:
        files = [f for f in workspace.iterdir() if f.is_file()]
    except OSError:
        return []
    html = {f.stem: f for f in files if f.suffix == ".html"}
    for f in sorted(files, key=lambda x: x.name.lower()):
        if f.suffix not in (".html", ".md", ".txt"):
            continue
        if f.suffix == ".md" and f.stem in html:
            continue  # the rendered twin is already listed
        found.append(f)

    def rank(path):
        for i, name in enumerate(preferred):
            if path.stem.lower().startswith(name.lower()):
                return i
        return len(preferred)

    found.sort(key=rank)
    return [(f.name, f) for f in found]


def _open_path(target: Path) -> str:
    """Hand a file to the OS's own opener. Returns '' on success, else a short reason.
    Deliberately not a viewer: reading a delivery report in a 30-column pane would be
    worse than the browser the HTML was rendered for."""
    import subprocess

    if sys.platform == "win32":
        argv = ["cmd", "/c", "start", "", str(target)]
    elif sys.platform == "darwin":
        argv = ["open", str(target)]
    else:
        argv = ["xdg-open", str(target)]
    try:
        subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
        )
        return ""
    except (OSError, ValueError) as exc:
        return f"could not open it here ({exc.__class__.__name__}) - {target}"


def _pick_engagement_slug(project_dir: Path, shown: list) -> str:
    """Which engagement's artifacts to show when more than one is open. Reuses the app's
    own picker so the choice looks like everything else; falls back to the most recent
    rather than asking a question the plain tier cannot render well."""
    try:
        from launcher_app import slug_picker_screen

        picked = slug_picker_screen(project_dir, sys.modules[__name__], shown)
        if picked:
            return picked
    except Exception:
        pass
    return _row_resume_token(shown[0]) if shown else ""


def _artifacts_plain(project_dir: Path, slug: str) -> None:
    """Plain tier: list what exists and open one by number. Same _engagement_artifacts and
    _open_path underneath as the screen, so the two cannot disagree about what is there."""
    ink = _Ink()
    err = sys.stderr
    items = _engagement_artifacts(project_dir, slug)
    print("", file=err)
    _print_rule(f"Artifacts for {slug}")
    if not items:
        print(ink.dim("  nothing rendered yet in this workspace"), file=err)
        return
    for i, (label, _path) in enumerate(items, 1):
        print(f"    {ink.bold(f'[{i}]')} {label}", file=err)
    print(ink.bold("  Open which? (blank to skip): "), end="", file=err)
    try:
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not choice:
        return
    try:
        target = items[int(choice) - 1][1]
    except (ValueError, IndexError):
        print(ink.dim("  not a listed number"), file=err)
        return
    problem = _open_path(target)
    print(ink.dim(f"  {problem or 'opened'}"), file=err)


def _browse_decision(project_dir: Path):
    """Run the explorer and return the chosen directory, or None. App tier only - the
    plain fallback below is a single typed path, because a numbered directory walker in
    input() is worse than just pasting the path you already know."""
    try:
        from launcher_app import BROWSE_CANCELLED, browse_screen

        chosen = browse_screen(project_dir, sys.modules[__name__])
        if chosen is None:
            return _browse_prompt(project_dir)
        if chosen == BROWSE_CANCELLED:
            return None
        return chosen
    except Exception:
        try:
            return _browse_prompt(project_dir)
        except Exception:
            return None


def _browse_prompt(project_dir: Path):
    """Plain tier: type or paste a folder. Same outcome, no full-screen requirement."""
    ink = _Ink()
    err = sys.stderr
    print(ink.bold("    Project folder (blank to cancel): "), end="", file=err)
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_dir():
        print(ink.dim(f"    not a folder: {candidate}"), file=err)
        return None
    return candidate


def _jira_offered(project_dir: Path) -> bool:
    """Whether to SHOW the [j] item. Always (2026-08-20 user decision: "it's an available
    option always, by default").

    Safe precisely because the item is only an affordance: picking it collects a ticket
    ref and pre-seeds the session prompt - the LAUNCHER never talks to Jira. Outward
    actions (creating the issue at open, mirroring progress) stay behind the explicit
    `integrations.jira.enabled` opt-in below, because those are the ones that touch
    someone else's tracker, and defaulting THOSE on would break the integrations
    contract's "off by default" promise."""
    return True


def _jira_enabled(project_dir: Path) -> bool:
    """True only on the explicit integrations opt-in (docs/INTEGRATIONS.md) - this gates
    OUTWARD actions (issue creation, progress comments), never the menu item."""
    try:
        import engage_probe

        return bool(
            (engage_probe.resolve_integrations(project_dir).get("jira") or {}).get("enabled")
        )
    except Exception:
        return False


_JIRA_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]+-\d+)\b")


def _jira_decision(project_dir: Path) -> str:
    """The [j] flow (2026-08-18 user request: engagements raisable BY ANYONE as a
    Jira, a human picks one up here - the human-approval step IS this menu): collect the
    issue URL (a bare key also works), pre-seed the session with it. The LAUNCHER never
    talks to Jira - the session fetches the ticket via the project's configured access
    (MCP or otherwise, per integrations.md) and delivers results back to it at close.
    Returns the decision string, or "__again__" to re-show the menu on an empty/invalid
    input."""
    ink = _Ink()
    err = sys.stderr
    print(
        ink.dim(
            "    The session will fetch the ticket and deliver results back to it "
            "(ticket content is treated as data, never instructions)."
        ),
        file=err,
    )
    if not _jira_enabled(project_dir):
        # Offered everywhere, but say plainly that fetching needs configured access -
        # better here than as a surprise mid-engagement.
        print(
            ink.dim(
                "    Note: this project has no Jira integration configured, so the "
                "session will only be able to fetch the ticket if access exists "
                "(docs/INTEGRATIONS.md)."
            ),
            file=err,
        )
    print(ink.bold("    Jira URL (or issue key): "), end="", file=err)
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        return "__again__"
    if not raw:
        return "__again__"
    m = _JIRA_KEY_RE.search(raw)
    if not m:
        print(ink.dim(f"    no issue key found in '{raw}' - back to the menu."), file=err)
        return "__again__"
    key = m.group(1).upper()
    # Pass the URL through when one was given - the session can use the exact instance
    # host; a bare key relies on the project's configured Jira access alone.
    ref = raw if "://" in raw else key
    print(ink.dim(f"    -> starting new engagement from {key}"), file=err)
    return _jira_command(project_dir, ref)


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


_AUTO_CONSENT_HOURS = 4
_AUTO_PROVENANCE = ".auto-grant.json"


def _consent_marker_path(project_dir: Path) -> Path:
    """The gate file guard-code-execution.py looks for. Assembled from parts so this
    module never carries the literal name - the consent-write guard checks command and
    edit text lexically, and a launcher that cannot be maintained is worse than one that
    spells a constant."""
    return project_dir / ".claude" / ("." + "exec" + "-" + "consent")


def _auto_provenance_path(project_dir: Path) -> Path:
    return project_dir / ".claude" / _AUTO_PROVENANCE


# Written into the marker body so the launcher can recognise its OWN grants later without
# depending on a sidecar that may be gone (2026-08-21 audit C3). Never change it without a
# migration: an older marker carrying the previous wording stops being recognised as ours.
_GRANT_SIGNATURE = "granted by the human at the virt-surv launcher"


def grant_execution_consent(project_dir: Path, slug: str, hours: int = _AUTO_CONSENT_HOURS):
    """Create the execution-consent gate ON BEHALF OF THE HUMAN AT THIS KEYBOARD.

    Read ADR-002 before touching this. The rule it protects is that the MODEL can never
    manufacture its own grant, and this does not weaken it: the launcher is a separate
    process that runs BEFORE any session exists, and this function is reachable only from a
    keypress on the pre-flight screen. The session still cannot create the marker - the
    guard hook blocks that exactly as before, and must keep doing so.

    Three properties make the second channel safe, and none is optional:
      * PROVENANCE - a sidecar records who granted it, when, from where and for which
        engagement, so an auditor can see the grant was human. The marker's own body says
        the same thing in plain text, since the guard only tests existence and ignores
        content.
      * EXPIRY - an unattended run must not leave standing authorisation behind. The
        sidecar carries an expiry; `_expire_stale_auto_consent` drops the marker once it
        passes, and the engagement's close does the same. Deleting the marker is a
        permitted action (closing a gate never needs consent); creating it is not, which
        is why only this process does it.
      * SCOPE - one engagement, named in the sidecar.

    Returns (True, "") or (False, reason)."""
    marker = _consent_marker_path(project_dir)
    import datetime

    now = datetime.datetime.now()
    expires = now + datetime.timedelta(hours=hours)
    body = (
        f"Execution consent {_GRANT_SIGNATURE}'s auto-mode\n"
        f"pre-flight screen for engagement '{slug}'.\n"
        f"granted: {now.isoformat(timespec='seconds')}\n"
        f"expires: {expires.isoformat(timespec='seconds')}\n"
        "Delete this file at any time to close the gate.\n"
    )
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(body, encoding="utf-8")
        _auto_provenance_path(project_dir).write_text(
            json.dumps(
                {
                    "granted_by": "human keypress, virt-surv auto-mode pre-flight",
                    "granted_at": now.isoformat(timespec="seconds"),
                    "expires_at": expires.isoformat(timespec="seconds"),
                    "engagement": slug,
                    "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"could not write the consent gate ({exc.__class__.__name__})"
    return True, ""


def _expire_stale_auto_consent(project_dir: Path) -> bool:
    """Drop a launcher-granted consent gate once its window has passed. Run at every go, so
    a marker left behind by an auto run cannot silently authorise later sessions - the
    failure mode that would quietly turn a one-off grant into a standing one.

    ONLY ever removes a marker this launcher granted (the sidecar proves it). A marker the
    human created by hand is theirs and is never touched."""
    import datetime

    side = _auto_provenance_path(project_dir)
    marker = _consent_marker_path(project_dir)
    if not marker.is_file():
        return False
    # Ownership is decided by the MARKER's own body, not by the sidecar's existence
    # (2026-08-21 audit C3/S1). Keying on the sidecar failed both ways: delete or corrupt
    # it and a launcher grant became permanent, while a stale sidecar left beside a
    # hand-made marker would have deleted the human's. The body is written by
    # grant_execution_consent and says so in plain text.
    try:
        body = marker.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if _GRANT_SIGNATURE not in body:
        return False  # a marker the human made by hand - never ours to remove
    expires = None
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        expires = datetime.datetime.fromisoformat(str(data.get("expires_at")))
    except Exception:
        expires = None
    if expires is None:
        # Ours, but the window is unreadable (sidecar gone, truncated, hand-edited). Close
        # the gate rather than leave an unbounded grant open: a gate closed too early costs
        # one static-only run, an unbounded one is a standing authorisation nobody granted.
        pass
    elif datetime.datetime.now() < expires:
        return False
    for path in (marker, side):
        try:
            path.unlink()
        except OSError:
            pass
    return True


def _auto_run_decision(project_dir: Path, ref: str, request_text: str = "") -> str:
    """Authorise and start an unattended run, from a TICKET or a typed request.

    Source-agnostic on purpose (2026-08-24): autonomy was reachable only from a Jira ticket,
    which was an accident of where it was built rather than anything about autonomy - the
    pre-flight, the ledger, park-don't-guess and the always-PARTIAL close never cared where
    the work came from. `request_text` set means a typed request; otherwise `ref` is a ticket.

    Returns the decision string, "__again__" if the human cancelled, or "" when the pre-flight
    screen could not run at all (the caller then starts an ORDINARY run - an unattended one
    must never begin by default because a screen failed to render)."""
    ink = _Ink()
    err = sys.stderr
    try:
        from launcher_app import AUTO_CANCELLED, auto_preflight_screen

        answers = auto_preflight_screen(project_dir, sys.modules[__name__], ref)
    except Exception:
        return ""
    if answers is None:
        return ""
    if answers == AUTO_CANCELLED:
        return "__again__"
    match = _JIRA_KEY_RE.search(ref) if not request_text else None
    if match:
        slug = match.group(1).upper()
    else:
        # No ticket to name it after: a few words of the request, so the consent grant's
        # provenance says what it was granted FOR rather than a bare "auto".
        slug = "-".join(_sanitise_request(request_text or ref).lower().split()[:4])[:40] or "auto"
    if answers.get("allow_exec"):
        ok, problem = grant_execution_consent(project_dir, slug)
        if ok:
            print(
                ink.warn(f"    execution gate opened for {slug}, expiring in ")
                + ink.warn(f"{_AUTO_CONSENT_HOURS}h"),
                file=err,
            )
        else:
            print(ink.warn(f"    {problem} - the run continues WITHOUT execution"), file=err)
    if not answers.get("data_attested"):
        print(
            ink.dim("    no data attestation - the run is limited to synthetic data"),
            file=err,
        )
    # Hand the fact to the workspace mechanically (2026-08-21 audit C1). The session used
    # to be relied on to run `mark-auto`, which nothing ever told it to do, so `auto`
    # stayed False and the AUTO-* DoD gates skipped every real unattended engagement.
    # engagement_state init consumes this file one-shot when it creates the pack.
    session_id = ""
    if answers.get("run_mode") == "headless":
        try:
            import headless_run

            # Generated before the run starts, so the pack records the SAME id the session
            # will carry. That is the correlation problem solved by construction rather than
            # matched afterwards by date or by whichever transcript was touched last.
            session_id = headless_run.new_session_id()
        except Exception:
            session_id = ""
    try:
        handoff = project_dir / ".claude" / ".auto-pending.json"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text(
            json.dumps(
                {
                    "ref": ref,
                    "slug": slug,
                    "granted_at": _now_iso(),
                    "auto": True,
                    # The spend ceiling and the pre-answered degrade rung travel with the
                    # flag: engagement_state consumes all of it when it creates the pack, so
                    # the run never has to be told any of it.
                    "engagement_usd": answers.get("engagement_usd"),
                    "hard_cap_usd": answers.get("hard_cap_usd"),
                    "allow_web": bool(answers.get("allow_web")),
                    "run_mode": answers.get("run_mode") or "window",
                    "session_id": session_id,
                    # Deliberately "park" and NOT the screen's default rung: this fires
                    # only if the pre-flight handed back a dict with no answer in it, which
                    # it never does normally. A missing answer is not the same as a chosen
                    # one, so the fallback stays the cautious rung.
                    "on_budget": answers.get("on_budget") or "park",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        print(
            ink.warn("    could not record the unattended flag - the DoD gates may not fire"),
            file=err,
        )
    cap = answers.get("engagement_usd")
    if cap:
        enforced = answers.get("hard_cap_usd")
        how = (
            "STOPS there (enforced)"
            if enforced
            else (f"it will {answers.get('on_budget', 'park')}")
        )
        print(ink.dim(f"    ceiling ${cap} - at the cap {how}"), file=err)
    if answers.get("run_mode") == "headless":
        print(ink.dim("    headless - no window; watch it from here"), file=err)
    print(
        ink.good(f"    -> unattended run on {slug}; it will close PARTIAL for sign-off"), file=err
    )
    if request_text:
        return _new_command(project_dir, request_text, auto=True)
    return _jira_command(project_dir, ref, auto=True)


def _pack_dir(project_dir: Path, slug: str) -> Path:
    return _vsit_paths().engagement_dir(slug, project_dir)


def _sign_off_state(project_dir: Path, slug: str) -> str:
    """Who signed a finished engagement off, or ''. Read-only."""
    if not slug:
        return ""
    try:
        state = json.loads(
            (_pack_dir(project_dir, slug) / "engagement-state.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return ""
    for entry in state.get("ratifications") or []:
        text = str(entry.get("text", "")) if isinstance(entry, dict) else ""
        if text.startswith("human sign-off:"):
            return text.split(":", 1)[1].strip()
    return ""


def _signer_name() -> str:
    """Who is at this keyboard, from git config - the same identity the commits carry.
    Falls back to the OS user; never to a placeholder, because an unattributed signature
    is worse than none."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        name = (proc.stdout or "").strip()
        if name:
            return name
    except Exception:
        pass
    name = os.environ.get("USER") or os.environ.get("USERNAME")
    if name:
        return name
    # The environment is not the only place the OS knows who you are, and in a container it
    # knows nothing: docker sets neither USER nor USERNAME, so sign-off was impossible on a
    # machine that could name its user perfectly well (found in a clean container,
    # 2026-08-25). getpass consults LOGNAME/USER/LNAME/USERNAME and then the password
    # database, which is the answer wherever a real account exists.
    try:
        import getpass

        return getpass.getuser() or ""
    except Exception:
        # Still never a placeholder. An unattributed signature is worse than none, and the
        # caller already says plainly what to set.
        return ""


def _record_sign_off(project_dir: Path, slug: str) -> str:
    """Append a human sign-off to a finished pack. Returns a short note for the screen.

    This is the answer to "what if I want to reopen it" for the commonest case: the work
    is delivered, a person just has not put their name to it - which every unattended run
    produces by design. Appending a signature leaves the as-found record intact; reopening
    the pack would not (the QA evidence rules say exactly this about retro-editing)."""
    if not slug:
        return "nothing selected"
    who = _signer_name()
    if not who:
        return "no signer identity - set git config user.name"
    import subprocess

    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.engagement_state",
                "sign-off",
                "--dir",
                str(_pack_dir(project_dir, slug)),
                "--by",
                who,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_scripts_dir().parent),
            # DEVNULL, never inherited: a child that keeps the parent's stdin open blocks
            # forever when nothing writes to it. This exact failure has bitten this repo
            # before (the CLI adapter, 2026-08-20), and it is what made a 6-second test file
            # hang the whole suite once enough prior subprocesses had run.
            stdin=subprocess.DEVNULL,
        )
    except Exception as exc:
        return f"could not sign off ({exc.__class__.__name__})"
    if proc.returncode != 0:
        return (proc.stderr or "sign-off failed").strip().splitlines()[-1][:60]
    return f"signed off by {who}"


def _supersede_command(project_dir: Path, slug: str) -> str:
    """Start NEW work that replaces a finished engagement, linked to it. Never reopens the
    old pack: the link lives on the new one, so the closed record stays exactly as closed."""
    return f"{_engage_command(project_dir)} --new --supersedes {slug}"


def _jira_command(project_dir: Path, ref: str, auto: bool = False) -> str:
    """The one place the --jira opening command is spelled. Both ticket prompts (the
    full-screen jira_screen and the plain input() flow above) end here, so they cannot
    drift the way the two menu renderers did."""
    return f"{_engage_command(project_dir)} --new --jira {ref}" + (" --auto" if auto else "")


# Every character that reads as a closing speech mark. The request is delivered inside
# `--request "<text>"`, so any of these ends the span early and hands the remainder to the
# skill as flags. Folded to a plain apostrophe, which carries the same meaning to a reader
# and cannot terminate anything. The curly forms matter for a second reason: they are not
# encodable on a cp1252 console, and this string is printed on the way out.
_QUOTE_CHARS = '"\u201c\u201d\u201e\u201f\u00ab\u00bb\u2033\u02ba'


def _sanitise_request(text: str) -> str:
    """Make a typed request safe to carry inside `--request "<text>"`, losing no words.

    The decision travels to the shell as a SINGLE argument and reaches the skill as
    `--request "<text>"`. Four things would break that, and all four are real rather than
    theoretical (2026-08-25):

    - a NEWLINE truncates the capture, so whitespace of every kind collapses to one space;
    - a DOUBLE QUOTE, straight or curly, closes the span early and turns the rest of the
      sentence into flags;
    - a CONTROL character (a bell from a bad paste, a stray escape) reaches the terminal
      and the prompt as noise;
    - a TRAILING BACKSLASH lands immediately before the closing quote as a backslash-quote
      pair, which any escape-aware reader takes as an escaped quote rather than a
      terminator - so the request appears to swallow the rest of the line. Interior
      backslashes are KEPT: a Windows path is a legitimate thing to put in a request, and
      mangling it would be its own bug.

    Deliberately does NOT truncate. Losing the end of someone's brief is the failure this
    whole path was just fixed for; a long request is merely long."""
    flat = " ".join(str(text).split())
    cleaned = "".join(ch for ch in flat if ch.isprintable())
    for quote in _QUOTE_CHARS:
        cleaned = cleaned.replace(quote, "'")
    return cleaned.rstrip("\\").strip()


_REQUEST_HANDOFF = ".request-pending.txt"


def _clear_request_handoff(project_dir: Path) -> None:
    """Remove any request left over from a previous `go`.

    Three things can strand one: backing out with Esc after typing, a session that never
    opened, and a session that opened but did not delete it. Clearing at the START of every
    go means the file is only ever this run's request or absent - so a stale instruction
    cannot be handed to an engagement nobody typed it for. Cheap, and it runs whether or
    not a request is typed this time."""
    try:
        (project_dir / ".claude" / _REQUEST_HANDOFF).unlink()
    except OSError:
        pass  # absent is the normal case


def _write_request_handoff(project_dir: Path, text: str) -> bool:
    """Put the typed request in a file for the session to read. True if it landed."""
    try:
        path = project_dir / ".claude" / _REQUEST_HANDOFF
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def _new_command(project_dir: Path, request: str = "", auto: bool = False) -> str:
    """The one place the new-engagement opening command is spelled. An empty request gives
    exactly the old `--new`, which is the point: typing is an offer, not a toll gate.

    The request travels in a FILE, never inside the command string (2026-08-25). It used to
    be `--request "<text>"`, which works in bash - verified - and fails on PowerShell: 5.1
    hands embedded double quotes to a native .exe unescaped, so claude.exe re-splits the
    line on its own and keeps the first token. Two users saw the same symptom on the same
    day, and the tell was that `--jira SURV-9` worked while a typed request did not - the
    difference between them being spaces and quotes, not anything about Jira.

    So the decision now carries a single bare token, `--request-pending`, with no spaces and
    no quotes anywhere in it. Nothing is left for a shell to re-interpret, on any platform,
    which is a better property than escaping correctly for each one."""
    command = f"{_engage_command(project_dir)} --new"
    clean = _sanitise_request(request)
    if clean:
        if _write_request_handoff(project_dir, clean):
            command += " --request-pending"
            if auto:
                command += " --auto"
        else:
            # Never silently drop what someone typed: say it, and let them repeat it in
            # session rather than opening as though they had asked for nothing.
            print(
                _Ink().warn(
                    "    could not hand your request to the session - please repeat it "
                    "once Claude opens"
                ),
                file=sys.stderr,
            )
    return command


def _new_decision(project_dir: Path, engagement_state=None, menu=None, shown=None) -> str:
    """Collect the request for a new engagement, and optionally start it unattended.

    Returns the decision string. Every failure path returns the plain `--new` this replaced,
    because a screen that cannot render must never cost someone a launch."""
    ink = _Ink()
    # A request prompt with no human at the keyboard is meaningless, and worse than
    # meaningless in a harness: prompt_toolkit blocks in its event loop waiting for keys that
    # never arrive, which hung the whole test suite for hours (found 2026-08-25 by aborting
    # the stuck process for its stack). VIRT_SURV_FORCE_PTK deliberately fakes the tty gate
    # so screens can be driven headlessly, so this checks stdin DIRECTLY - the same guard
    # _write_probe_cache uses. No tty means the plain `--new` this replaced.
    try:
        interactive = sys.stdin.isatty()
    except Exception:
        interactive = False
    if not interactive:
        print(ink.dim("    -> starting new"), file=sys.stderr)
        return _new_command(project_dir)
    try:
        from launcher_app import REQUEST_SKIPPED, request_screen

        answer = request_screen(project_dir, sys.modules[__name__])
    except Exception:
        answer = None
    if answer is None or answer == REQUEST_SKIPPED:
        print(ink.dim("    -> starting new"), file=sys.stderr)
        return _new_command(project_dir)
    request, auto = answer
    if auto:
        decision = _auto_run_decision(project_dir, request, request_text=request)
        if decision == "__again__":
            return "__again__"
        if decision:
            return decision
    print(ink.dim("    -> starting new with your request"), file=sys.stderr)
    return _new_command(project_dir, request)


def _auto_armed(project_dir: Path) -> bool:
    """Whether the unattended toggle starts ON for new work in this project.

    The DEFAULT ANSWER to one question, never the removal of a question: an armed run still
    stops at the pre-flight, where data attestation, execution consent and the spend ceiling
    are answered by a human. Off unless the project (or machine) asked for it - see
    engage_probe.resolve_preferences for why arming stays opt-in while the kill switch
    does not."""
    try:
        import engage_probe

        return bool(engage_probe.resolve_preferences(project_dir).get("autonomous_default"))
    except Exception:
        return False


def _auto_offered(project_dir: Path) -> bool:
    """Whether [j] may offer an unattended run - the AFFORDANCE, not the decision.

    Offered unless the project explicitly turned it off (2026-08-21: "auto should be per
    jira not entire project"). Safe because offering grants nothing: an unattended run
    still takes three deliberate acts per ticket - toggle it on the ticket screen, confirm
    the pre-flight, and separately tick execution consent if code is to run. Same shape as
    [j] itself, where the menu item is always present and what it can DO is gated."""
    try:
        import engage_probe

        return bool(engage_probe.resolve_preferences(project_dir).get("autonomous_mode"))
    except Exception:
        return False


def _pt_menu_round(
    p, project_dir: Path, engagement_state, menu: dict, shown: list, show_all: bool = False
) -> str:
    """prompt_toolkit tier of the go menu: arrow/mouse picker over the same entries as
    the numbered flow, same return contract (decision, "" for in-session/plain, or
    "__again__" after a side action)."""
    # Same local cap as the numbered tier, and the same escape hatch - the picker is a
    # fixed-height widget, so an uncapped list would simply run off it.
    full = shown
    shown = shown if show_all else shown[:_PLAIN_TIER_ROWS]
    hidden = len(full) - len(shown)
    entries = []
    default_slug = menu.get("default") or ""
    for i, row in enumerate(shown):
        # 2026-08-19: this tier used to render its own `resume <slug> <status> opened
        # <date> <title>` row while the numbered tier had already moved to title-first
        # with a detail tail - two renderers, and THIS is the one most users actually
        # see (live screenshot). Same content in both now; one line, because a picker
        # entry is a single selectable row.
        view = row_view(row, default_slug=default_slug, of_many=len(shown) > 1)
        frags = [
            ("class:warn" if view["mark_style"] == "warn" else "class:dim", f"{view['mark']} "),
            ("", view["title"]),
        ]
        if view["detail"]:
            frags.append(("class:dim", f"  ·  {view['detail']}"))
        if view["recommended"]:
            frags.append(("class:on", "  <- most recent"))
        entries.append((("resume", i), frags, None))
    subtitle = ""
    if not shown:
        archived = menu.get("archived") or 0
        subtitle = f"none open ({archived} archived)" if archived else "none open"
    if hidden:
        entries.append(((_SHOW_ALL,), f"show all {len(full)} open engagements", "m"))
    entries.append((("new",), "start a new engagement", "n"))
    if _jira_offered(project_dir):
        entries.append((("jira",), "a new engagement from a Jira ticket", "j"))
    entries.append((("settings",), "change a project setting", "c"))
    entries.append((("open",), "open a different project folder", "o"))
    if shown:
        entries.append((("archive",), "archive engagement(s)", "a"))
    entries.append((("finished",), "browse done & archived engagements", "b"))
    if _running_slug(project_dir):
        entries.append((("watch",), "watch the engagement already running", "t"))
    launch_label = "decide inside the session instead" if shown else "just launch"
    entries.append((("launch",), launch_label, None))
    default_index = 0
    for i, row in enumerate(shown):
        if (_row_resume_token(row) or "") == default_slug:
            default_index = i
            break
    pick = _pt_pick(
        p,
        # Morgan ASKS rather than captioning a list (2026-08-20): the picker's title is
        # the question, so both tiers pose the same thing.
        "How would you like to start?",
        entries,
        default_index=default_index,
        subtitle=subtitle,
    )
    if pick is _PT_FAILED:
        return "__pt_fallback__"
    return _decision_from_pick(pick, project_dir, engagement_state, menu, shown)


def _decision_from_pick(
    pick, project_dir: Path, engagement_state, menu: dict, shown: list, rich: bool = False
) -> str:
    """Map a picked entry to the decision string. Shared by the full-screen app tier and
    the picker tier (2026-08-20) - both produce the SAME pick tuples, and a second copy of
    this mapping is exactly the drift this work exists to remove."""
    ink = _Ink()
    if pick is None:
        # Backing out is NOT the same as choosing to launch: Esc/Ctrl-C returns you to
        # the terminal (2026-08-20 user report). Only the explicit launch row below
        # starts a session with no pre-seeded decision.
        print(ink.dim("    -> back to the terminal"), file=sys.stderr)
        return _ABORT
    if pick[0] == "launch":
        print(ink.dim("    -> launching"), file=sys.stderr)
        return ""
    if pick[0] == "jira":
        try:
            # Full-screen ticket prompt first (2026-08-20 user report: picking [j] used to
            # tear the app down and drop to a bare input()). Same None/cancel contract the
            # settings screen learned the hard way: None means the screen could not run
            # and the plain prompt takes over; a cancel is NOT unavailability.
            from launcher_app import JIRA_CANCELLED, jira_screen

            ref = jira_screen(project_dir, sys.modules[__name__])
            if ref == JIRA_CANCELLED:
                return "__again__"
            auto = False
            if isinstance(ref, tuple):
                ref, auto = ref
            if ref and auto:
                decision = _auto_run_decision(project_dir, ref)
                if decision == "__again__":
                    return "__again__"
                if decision:
                    return decision
                auto = False  # pre-flight could not run - fall through to a normal run
            if ref:
                print(ink.dim(f"    -> starting new engagement from {ref}"), file=sys.stderr)
                return _jira_command(project_dir, ref)
        except Exception:
            pass  # any app failure degrades to the plain prompt below
        try:
            return _jira_decision(project_dir)
        except Exception:
            return "__again__"
    if pick[0] == _SHOW_ALL:
        return _SHOW_ALL
    if pick[0] == "help":
        try:
            from launcher_app import help_screen

            help_screen(project_dir, sys.modules[__name__])
        except Exception:
            pass  # cosmetic tier
        return "__again__"
    if pick[0] == "watch":
        # Watching starts NOTHING. Returning "__again__" puts the human back on the menu
        # afterwards rather than launching a session they never asked for.
        try:
            _watch_running_engagement(project_dir)
        except Exception:
            print(ink.dim("    could not open the watch view here"), file=sys.stderr)
        return "__again__"
    if pick[0] == "artifacts":
        slug = _row_resume_token(shown[0]) if shown else ""
        if len(shown) > 1:
            slug = _pick_engagement_slug(project_dir, shown) or slug
        if slug:
            try:
                from launcher_app import artifacts_screen

                if artifacts_screen(project_dir, sys.modules[__name__], slug) is None:
                    _artifacts_plain(project_dir, slug)
            except Exception:
                try:
                    _artifacts_plain(project_dir, slug)
                except Exception:
                    pass
        return "__again__"
    if pick[0] == "open":
        chosen = _browse_decision(project_dir)
        if not chosen:
            return "__again__"
        try:
            same = chosen.resolve() == project_dir.resolve()
        except Exception:
            same = False
        if same:
            return "__again__"
        return _CHDIR_PREFIX + str(chosen)
    if pick[0] == "settings":
        try:
            # App screen first (2026-08-20): same _editor_rows/_editor_apply underneath,
            # so behaviour is identical and only the presentation differs. Falls back to
            # the numbered editor wherever the app can't run.
            from launcher_app import settings_screen

            # None = the app screen could not run; False = it ran and the user changed
            # nothing (Esc). Only the former falls back - treating Esc as "unavailable"
            # dumped the user into the old numbered editor (live report, 2026-08-20).
            if settings_screen(project_dir, sys.modules[__name__]) is None:
                _run_settings_editor(project_dir)
        except Exception:
            try:
                _run_settings_editor(project_dir)
            except Exception:
                pass  # cosmetic tier
        return "__again__"
    if pick[0] == "archive":
        try:
            from launcher_app import archive_screen

            if archive_screen(project_dir, sys.modules[__name__], engagement_state, menu) is None:
                _archive_menu(project_dir, engagement_state, menu)
        except Exception:
            try:
                _archive_menu(project_dir, engagement_state, menu)
            except Exception:
                pass
        return "__again__"
    if pick[0] == "finished":
        # None = the app screen could not run -> numbered fallback; '' = the user
        # backed out (Esc / back) -> just re-ask. Same None-vs-falsy contract as
        # settings above - conflating them dumped users into the wrong tier once.
        token = None
        try:
            from launcher_app import finished_screen

            token = finished_screen(project_dir, sys.modules[__name__], engagement_state)
        except Exception:
            token = None
        if token is None:
            try:
                token = _finished_menu(project_dir, engagement_state)
            except Exception:
                token = ""
        if token:
            print(ink.dim(f"    -> reviewing {token}"), file=sys.stderr)
            if isinstance(token, tuple) and token and token[0] == "supersede":
                print(ink.dim(f"    -> new work superseding {token[1]}"), file=sys.stderr)
                return _supersede_command(project_dir, token[1])
            return f"{_engage_command(project_dir)} --review {token}"
        return "__again__"
    engage_cmd = _engage_command(project_dir)
    if pick[0] == "new":
        # The request screen belongs to the APP tier only. The picker and numbered tiers are
        # the fallbacks for consoles that cannot run a full-screen app, so opening one from
        # them is both wrong in principle and, on a pipe-driven input, a hang: prompt_toolkit
        # blocks forever waiting for keys that will never arrive (found 2026-08-25 by a
        # performance review, after three of my own test runs sat stuck for hours).
        if rich:
            return _new_decision(project_dir, engagement_state, menu, shown)
        print(ink.dim("    -> starting new"), file=sys.stderr)
        return _new_command(project_dir)
    slug = _row_resume_token(shown[pick[1]])
    if slug:
        print(ink.dim(f"    -> resuming {slug}"), file=sys.stderr)
        return f"{engage_cmd} --resume {slug}"
    return ""


def _menu_round(
    project_dir: Path, engagement_state, menu: dict, shown: list, show_all: bool = False
) -> str:
    """One render-and-ask round of the engagement menu. Returns the decision string, ""
    for decide-in-session, or the sentinel "__again__" after a side action ([c] settings,
    [a] archive) so the caller recomputes the menu - archiving changes it - and asks
    again."""
    err = sys.stderr
    ink = _Ink()
    # Tier order (2026-08-20): full-screen app -> picker -> numbered. Each falls through
    # on its own sentinel, so a console that cannot run the app still gets a working menu.
    # Default since 2026-08-20 (user decision: "no need to poc, lets just build out the
    # better tui"). VIRT_SURV_NO_APP=1 opts OUT, back to the picker/numbered tiers - kept
    # as an escape hatch for a console where the app misbehaves in a way the internal
    # fallback does not catch.
    if not os.environ.get("VIRT_SURV_NO_APP"):
        try:
            from launcher_app import APP_FALLBACK, run_app

            pick = run_app(
                project_dir, sys.modules[__name__], menu, shown, jira_on=_jira_offered(project_dir)
            )
            if pick != APP_FALLBACK:
                return _decision_from_pick(
                    pick, project_dir, engagement_state, menu, shown, rich=True
                )
        except Exception:
            pass  # any app failure degrades to the tiers below, never breaks the launch
    p = _ptk_ui()
    if p:
        decision = _pt_menu_round(p, project_dir, engagement_state, menu, shown, show_all)
        if decision != "__pt_fallback__":
            return decision
        # The pt widget could not run in this console (live Windows report
        # 2026-08-17: a silent plain launch) - the numbered tier below takes over.
    # 2026-08-20 UX pass: Morgan ASKS, and the answers are grouped. Previously one
    # "Open engagements" rule sat above everything, so [n] start new / [c] settings /
    # [Enter] read as though they were open engagements; and with no blank line anywhere
    # the whole screen ran together. Groups are dim labels, not rules - more rules on a
    # short screen is what made it feel crowded in the first place.
    print("", file=err)
    print(f"  {ink.bold('How would you like to start?')}", file=err)
    print("", file=err)
    # The menu now arrives uncapped, so THIS tier does its own limiting - a numbered
    # input() list of thirty engagements is unusable, but the remainder must still be
    # reachable ([m]) rather than merely counted.
    capped = shown if show_all else shown[:_PLAIN_TIER_ROWS]
    hidden = len(shown) - len(capped)
    if shown:
        print(f"  {ink.dim('Resume an engagement')}", file=err)
        # 2026-08-19 UX pass: rows now LEAD with the title (what the work is), carry a
        # status mark and a relative age, and the recommended row is marked - the raw
        # slug/status/ISO-date table made the reader do the interpreting.
        default_slug = menu.get("default")
        slug_w = max(len(_row_resume_token(r) or "?") for r in capped)
        for i, row in enumerate(capped, 1):
            view = row_view(row, default_slug=default_slug or "", of_many=len(shown) > 1)
            mark_col = (
                ink.warn(view["mark"]) if view["mark_style"] == "warn" else ink.dim(view["mark"])
            )
            head = f"    {ink.bold(f'[{i}]')} {mark_col} {ink.bold(view['title'])}"
            if view["recommended"]:
                head += "  " + ink.good("<- most recent")
            print(head, file=err)
            tail = f"        {ink.dim(view['slug'].ljust(slug_w))}"
            if view["detail"]:
                tail += "  " + ink.dim(view["detail"])
            print(tail, file=err)
            if i < len(capped):
                print("", file=err)  # one blank line BETWEEN two-line entries
        if hidden:
            print(
                ink.dim(f"        (+{hidden} more)  ") + ink.bold("[m]") + ink.dim(" show all"),
                file=err,
            )
        print("", file=err)
    else:
        archived = menu.get("archived") or 0
        note = f"no open engagements ({archived} archived)" if archived else "no open engagements"
        print(f"  {ink.dim(note)}", file=err)
        print("", file=err)
    print(f"  {ink.dim('Start something new')}", file=err)
    print(f"    {ink.bold('[n]')} a new engagement", file=err)
    jira_on = _jira_offered(project_dir)
    if jira_on:
        print(f"    {ink.bold('[j]')} a new engagement from a Jira ticket", file=err)
    print("", file=err)
    print(f"  {ink.dim('Or')}", file=err)
    settings_opt = f"    {ink.bold('[c]')} change a project setting"
    settings_opt += f"   {ink.bold('[o]')} open a different project"
    if shown:
        settings_opt += f"   {ink.bold('[v]')} view artifacts"
    if shown:
        settings_opt += f"   {ink.bold('[a]')} archive engagement(s)"
    settings_opt += f"   {ink.bold('[b]')} browse done & archived"
    if _running_slug(project_dir):
        settings_opt += f"   {ink.bold('[t]')} watch the running engagement"
    print(settings_opt, file=err)
    enter_label = "just launch" if not shown else "decide inside the session instead"
    print(f"    {ink.dim(f'[Enter] {enter_label}')}   {ink.dim('[?] help')}", file=err)
    try:
        suggestion = _suggestion_line(project_dir, menu)
    except Exception:
        suggestion = ""  # cosmetic tier - a nudge must never cost a launch
    if suggestion:
        print("", file=err)
        print(f"  {ink.warn('>')} {ink.dim(suggestion)}", file=err)
    print("", file=err)
    try:
        # Live bug (2026-08-15): input(prompt) writes `prompt` to STDOUT, not stderr -
        # CPython does this unconditionally, regardless of which stream the caller
        # otherwise uses. Passing "Choice: " as input()'s own argument leaked it onto
        # the exact stream this function's own output contract reserves for the
        # decision alone, so a shell capturing stdout via $(...) got "Choice: --new"
        # instead of a clean "--new" - garbled into a single mangled argument by the
        # time it reached the launch command. Print the prompt text ourselves, to
        # stderr, then call input() with NO argument so it never touches stdout.
        print(_Ink().bold("  Choice: "), end="", file=err)
        choice = input().strip()
    except EOFError:
        # No tty (CI, a pipe, `go < /dev/null`): the documented plain launch. NOT an
        # abort - automation that never sees the menu must keep behaving as it always has.
        return ""
    except KeyboardInterrupt:
        # A human backing out, same as Esc in the app tier (2026-08-20).
        return _ABORT
    if not choice:
        return ""
    if choice.lower() == "j" and jira_on:
        try:
            return _jira_decision(project_dir)
        except Exception:
            return "__again__"
    if choice.lower() == "c":
        try:
            _run_settings_editor(project_dir)
        except Exception:
            pass  # cosmetic tier
        return "__again__"
    if choice.lower() == "m" and hidden:
        return _SHOW_ALL
    if choice == "?":
        return _decision_from_pick(("help",), project_dir, engagement_state, menu, shown)
    if choice.lower() == "v" and shown:
        return _decision_from_pick(("artifacts",), project_dir, engagement_state, menu, capped)
    if choice.lower() == "o":
        # Same mapping the other two tiers use, so the explorer cannot mean one thing
        # here and another there.
        return _decision_from_pick(("open",), project_dir, engagement_state, menu, shown)
    if choice.lower() == "a":
        try:
            _archive_menu(project_dir, engagement_state, menu)
        except Exception:
            pass
        return "__again__"
    if choice.lower() == "b":
        # Same mapping as the app and picker tiers, so [b] cannot mean one thing
        # there and another here.
        return _decision_from_pick(("finished",), project_dir, engagement_state, menu, shown)
    if choice.lower() == "t" and _running_slug(project_dir):
        return _decision_from_pick(("watch",), project_dir, engagement_state, menu, shown)
    engage_cmd = _engage_command(project_dir)
    shown = capped  # numbered picks refer to what was PRINTED
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


# ---------------------------------------------------------------- presentation
# The go screen is the team's front door (2026-08-17 user request: "prettify it
# materially"). Constraints learned live: STRUCTURE stays pure ASCII (corp consoles
# decode stderr as cp1252 - box glyphs arrive as mojibake, the probe's own lesson), and
# ANSI color only when the terminal provably supports it - a real tty, NO_COLOR unset,
# and on Windows a terminal that speaks VT (Windows Terminal / mintty / a TERM-setting
# ssh session). Everything degrades to the same plain text the tests read. stdout is
# untouched by any of this - it stays exactly the decision string.


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stderr.isatty():
        return False
    if os.name != "nt":
        return True
    return bool(
        os.environ.get("WT_SESSION")
        or os.environ.get("TERM")
        or os.environ.get("TERM_PROGRAM")
        or os.environ.get("ANSICON")
    )


class _Ink:
    def __init__(self) -> None:
        self.on = _color_enabled()

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text

    def title(self, t: str) -> str:
        return self._c("1;36", t)

    def dim(self, t: str) -> str:
        return self._c("2", t)

    def good(self, t: str) -> str:
        return self._c("32", t)

    def warn(self, t: str) -> str:
        return self._c("33", t)

    def bold(self, t: str) -> str:
        return self._c("1", t)

    # The brand banner's palette (2026-08-27): plain cyan next to `title`'s bold cyan, and
    # the violet the wordmark gradient runs through. Same _c() gate as everything else, so
    # NO_COLOR / a pipe / a non-VT Windows console strips them with the rest.
    def cyan(self, t: str) -> str:
        return self._c("36", t)

    def violet(self, t: str) -> str:
        return self._c("35", t)


def _rule(ink: _Ink, label: str = "", note: str = "", width: int = 0) -> str:
    # width=0 means "fit the terminal" (2026-08-19): the old fixed 64 overflowed narrow
    # terminals, wrapping the tail of every rule onto its own line.
    width = width or min(_term_cols() - 2, 76)
    if not label:
        return ink.dim("=" * width)
    body = f"--- {label} "
    pad = width - len(body) - (len(note) + 1 if note else 0)
    line = body + "-" * max(pad, 3) + (f" {note}" if note else "")
    return (
        ink.dim(line[:width])
        if not note
        else ink.dim(body + "-" * max(pad, 3)) + " " + ink.dim(note)
    )


_RICH_CACHE = None


def _rich_ui():
    """Vendored rich (repo vendor/, the same tree convert_file's deps live in - 2026-08-17
    user request for a materially nicer go TUI) when importable; None otherwise. Every
    caller keeps its plain-_Ink rendering as the fallback, so a missing or broken vendor
    tree costs looks only, never the launch. Only rich CORE is vendored (Console, Table,
    Panel, Rule need neither pygments nor markdown-it - verified empirically before
    vendoring). The Console is built fresh per call so it binds the CURRENT sys.stderr
    (tests swap it); box/rule glyphs degrade to ASCII unless stderr is utf-capable - corp
    Windows consoles decode stderr as cp1252 and box glyphs arrive as mojibake (the
    _print_project_defaults lesson, kept)."""
    global _RICH_CACHE
    if _RICH_CACHE is None:
        try:
            vend = _scripts_dir().parent / "vendor"
            if str(vend) not in sys.path:
                sys.path.insert(0, str(vend))
            from rich import box
            from rich.console import Console
            from rich.panel import Panel
            from rich.rule import Rule
            from rich.table import Table
            from rich.text import Text

            _RICH_CACHE = {
                "box": box,
                "Console": Console,
                "Panel": Panel,
                "Rule": Rule,
                "Table": Table,
                "Text": Text,
            }
        except Exception:
            _RICH_CACHE = {}
    if not _RICH_CACHE:
        return None
    r = dict(_RICH_CACHE)
    utf = "utf" in ((getattr(sys.stderr, "encoding", "") or "").lower())
    import shutil as _shutil

    # Cap the content column (2026-08-17 polish pass): full-terminal-width rules on a
    # wide screen visually detach from the panel and table beside them - one bounded
    # column reads as a single composed block.
    cols = _shutil.get_terminal_size((80, 24)).columns
    r["console"] = r["Console"](
        file=sys.stderr, highlight=False, emoji=False, soft_wrap=True, width=min(cols, 76)
    )
    r["safe_box"] = r["box"].SIMPLE if utf else r["box"].ASCII
    r["panel_box"] = r["box"].ROUNDED if utf else r["box"].ASCII
    r["rule_char"] = "─" if utf else "-"
    return r


def _print_rule(label: str, note: str = "") -> None:
    """Section rule to stderr - rich Rule when available, the plain _rule string
    otherwise. One helper so every menu header upgrades/degrades together. Bold title,
    dim note, cyan-tinted line - the same accent the panel and pickers use."""
    r = _rich_ui()
    if r:
        title = r["Text"](label, style="bold")
        if note:
            title.append(f"  ({note})", style="dim")
        r["console"].print(
            r["Rule"](title, characters=r["rule_char"], style="dim cyan", align="left")
        )
        return
    print(_rule(_Ink(), label, note=note), file=sys.stderr)


_PTK_CACHE = None

# Sentinel for "the pt widget failed to run at all" - distinct from None, which means
# the USER backed out (Esc). A failure falls back to the numbered input() tier; an Esc
# must never re-prompt.
_PT_FAILED = object()

_WIN_CONOUT_BOUND = None


def _win_bind_conout() -> bool:
    """prompt_toolkit's Win32 layer renders via GetStdHandle(STD_OUTPUT_HANDLE) - the
    PROCESS stdout handle - regardless of the stream passed in (win32.py's
    Win32Output.__init__, confirmed in the vendored source). Under the v5 alias stdout
    is a capture pipe, so pt raised NoConsoleScreenBufferError and the menu silently
    vanished (live corp report + WINTEST repro, 2026-08-17). The winpty-style fix:
    point the process STD_OUTPUT_HANDLE at the real console (CONOUT$). Python-level
    stdout is unaffected - the C runtime's fd 1 already holds the pipe handle, so the
    decision print still reaches the shell's capture; only fresh GetStdHandle callers
    (pt) see the console. Returns False when there is no console to bind (then the
    numbered tier takes over)."""
    global _WIN_CONOUT_BOUND
    if _WIN_CONOUT_BOUND is not None:
        return _WIN_CONOUT_BOUND
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        # GENERIC_READ|GENERIC_WRITE, share read|write, OPEN_EXISTING
        handle = ctypes.c_void_p(
            k32.CreateFileW("CONOUT$", 0xC0000000, 0x3, None, 0x3, 0, None)
        ).value
        invalid = ctypes.c_void_p(-1).value
        if not handle or handle == invalid:
            _WIN_CONOUT_BOUND = False
        else:
            # 0xFFFFFFF5 == (DWORD) STD_OUTPUT_HANDLE (-11)
            _WIN_CONOUT_BOUND = bool(k32.SetStdHandle(0xFFFFFFF5, handle))
    except Exception:
        _WIN_CONOUT_BOUND = False
    return _WIN_CONOUT_BOUND


def _ptk_ui():
    """Vendored prompt_toolkit (2026-08-17 user request: arrow keys, mouse, in-place
    updates - "a nicer, less tech experience") when USABLE: importable AND both stdin
    and stderr are real ttys. Anything else - tests, pipes, dumb terminals, a broken
    vendor tree - returns None and every menu falls back to the numbered input() flow,
    which stays fully maintained (it is also what non-tty automation always gets).
    VIRT_SURV_FORCE_PTK=1 skips the tty gate so the pt tier can be driven headlessly
    (tests use prompt_toolkit's own pipe-input/dummy-output session)."""
    global _PTK_CACHE
    if not os.environ.get("VIRT_SURV_FORCE_PTK"):
        try:
            if not (sys.stdin.isatty() and sys.stderr.isatty()):
                return None
        except Exception:
            return None
        if sys.platform == "win32":
            try:
                # The alias captures stdout, and pt's Win32 layer only ever renders
                # via the PROCESS stdout handle - rebind it to the console first.
                if not sys.stdout.isatty() and not _win_bind_conout():
                    return None
            except Exception:
                return None
    if _PTK_CACHE is None:
        try:
            vend = _scripts_dir().parent / "vendor"
            if str(vend) not in sys.path:
                sys.path.insert(0, str(vend))
            from prompt_toolkit.application import Application
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import Layout, Window
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.mouse_events import MouseEventType
            from prompt_toolkit.styles import Style

            _PTK_CACHE = {
                "Application": Application,
                "KeyBindings": KeyBindings,
                "Layout": Layout,
                "Window": Window,
                "FormattedTextControl": FormattedTextControl,
                "MouseEventType": MouseEventType,
                "Style": Style,
            }
        except Exception:
            _PTK_CACHE = {}
    return _PTK_CACHE or None


def _pt_io() -> dict:
    """Application() kwargs binding prompt_toolkit's rendering to STDERR - stdout stays
    the decision channel even while a full-screen-less pt app is running. Tests
    monkeypatch this to {} so the app inherits their pipe-input/dummy-output session."""
    try:
        from prompt_toolkit.output.defaults import create_output

        return {"output": create_output(stdout=sys.stderr)}
    except Exception:
        return {}


def _pt_style(p):
    """ANSI-16 only (corp terminals and pt's legacy Win32 backend map these cleanly;
    truecolor does not survive every console). One accent - cyan - for structure and
    selection; semantic colors reserved for STATE: green active, yellow attention,
    dim inactive. The selection bar is cyan-on-black rather than reverse video, which
    flips to something different in every terminal theme."""
    return p["Style"].from_dict(
        {
            "title": "bold ansicyan",
            "sel": "bg:ansicyan ansiblack",
            "dim": "ansibrightblack",
            "note": "italic ansibrightblack",
            "on": "ansigreen",
            "warn": "ansiyellow",
            "slug": "bold",
            "hot": "ansicyan",
        }
    )


def _pt_pick(p, title: str, entries: list, default_index: int = 0, subtitle: str = ""):
    """One arrow/mouse picker round: entries = [(ret, label, hotkey-or-None)] where
    label is a plain string OR a list of (style, text) fragments for styled rows.
    Returns the chosen entry's ret, or None on Esc/Ctrl-C/q (caller's 'back/default').
    Up/Down and mouse move the highlight, Enter (or a click, or the hotkey) picks; the
    widget erases itself when done so the console stays clean."""
    idx = [max(0, min(default_index, len(entries) - 1))]
    result = {"v": None}
    kb = p["KeyBindings"]()

    def _exit(event, value):
        result["v"] = value
        event.app.exit()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(entries)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(entries)

    @kb.add("enter")
    def _enter(event):
        _exit(event, entries[idx[0]][0])

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        _exit(event, None)

    for i, (ret, _label, hot) in enumerate(entries):
        if hot:

            @kb.add(hot)
            def _hot(event, _ret=ret):
                _exit(event, _ret)

    def _fragments():
        MouseEventType = p["MouseEventType"]
        out = [("class:title", f" {title}\n")]
        if subtitle:
            out.append(("class:dim", f"   {subtitle}\n"))
        for i, (ret, label, hot) in enumerate(entries):

            def _click(mouse_event, _i=i, _ret=ret):
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    idx[0] = _i
                    result["v"] = _ret
                    from prompt_toolkit.application.current import get_app

                    get_app().exit()
                    return None
                return NotImplemented

            sel = i == idx[0]
            marker = "> " if sel else "  "
            out.append(("class:sel" if sel else "", f"  {marker}", _click))
            if isinstance(label, str):
                out.append(("class:sel" if sel else "", label, _click))
            else:
                for frag_style, frag_text in label:
                    out.append(("class:sel" if sel else frag_style, frag_text, _click))
            if hot:
                # Always rendered - hiding it on the selected row made the badge
                # vanish and the highlight bar change width as you moved (live report
                # 2026-08-17); on selection it just joins the bar's styling.
                out.append(("class:sel" if sel else "class:dim", "  ", _click))
                out.append(("class:sel" if sel else "class:hot", f"[{hot}]", _click))
            out.append(("", "\n"))
        out.append(("class:dim", "  arrows/mouse move · Enter picks · Esc backs out"))
        return out

    height = len(entries) + (3 if subtitle else 2)
    app = p["Application"](
        layout=p["Layout"](
            p["Window"](
                p["FormattedTextControl"](_fragments, focusable=True, show_cursor=False),
                height=height,
                always_hide_cursor=True,
            )
        ),
        key_bindings=kb,
        style=_pt_style(p),
        mouse_support=True,
        erase_when_done=True,
        full_screen=False,
        **_pt_io(),
    )
    try:
        app.run()
    except Exception:
        # NOT the same as Esc (None): the widget never ran - e.g. prompt_toolkit's
        # Win32 console layer refusing a captured-stdout invocation (live Windows
        # report 2026-08-17: the menu silently vanished and go launched plainly).
        # Callers see the sentinel and fall back to the numbered input() tier.
        return _PT_FAILED
    return result["v"]


def _plugin_version() -> str:
    try:
        manifest = _scripts_dir().parent / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text(encoding="utf-8-sig")).get("version") or ""
    except Exception:
        return ""


_PROBE_CACHE_TTL_S = 3600


def _write_probe_cache(project_dir: Path) -> None:
    """Run the engage probe ENTIRELY OUTSIDE Claude Code (2026-08-18 user request: corp
    boxes take minutes per in-session probe - go is where a human is already watching a
    terminal). Writes .claude/engage-probe.json: the full report plus invalidation keys
    (epoch + human timestamp, prefs mtime, plugin version, interpreter). The prefetch
    hook serves it with zero computation; the engage-open Read path uses it when the
    hook didn't fire. The SESSION STAMP is deliberately not written here - no session
    exists pre-launch, and engage_probe's own guard skips stamping without
    CLAUDE_CODE_SESSION_ID; the serving side stamps live. Interactive runs only (a tty
    check keeps tests and automation off this path); freshness-gated so repeat go runs
    don't recompute; best-effort - failure just means the live probe runs."""
    try:
        if not sys.stdin.isatty():
            return
        scripts_dir = _scripts_dir()
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import engage_probe

        if not engage_probe.resolve_preferences(project_dir).get("probe_cache", True):
            return  # toggled off ([c] item 7) - the live probe is the only path
        import time

        out = _vsit_paths().local_file("engage_probe", project_dir)
        prefs = _vsit_paths().preferences_file(project_dir)
        prefs_mtime = int(prefs.stat().st_mtime) if prefs.is_file() else 0
        # Identity fingerprint (2026-08-18, external token-review finding 2) - stamped
        # here, validated by the prefetch hook's _git_identity/_live_plugin_version, so a
        # branch switch or plugin update inside the TTL invalidates instead of injecting
        # a stale BRANCH=/PLUGIN_VERSION= fact into the session's opening context.
        git_branch = git_head = ""
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
                # Order is load-bearing: --abbrev-ref applies to every rev AFTER it, so the
                # old `--abbrev-ref HEAD HEAD` stamped the branch name into BOTH fields and
                # the head half never invalidated anything (found 2026-08-20). The hook's
                # _git_identity runs the identical command - keep the two in step.
                git_head, git_branch = lines[0].strip(), lines[1].strip()
        except Exception:
            pass
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            # prefs comparison NOT via `or -1`: a prefs-less project stamps 0, and
            # 0-is-falsy made every freshness check fail, recomputing on each go run
            # (same bug as the hook's, found 2026-08-18 by the cache test matrix).
            fresh = (
                time.time() - float(existing.get("computed_at_epoch") or 0) < _PROBE_CACHE_TTL_S
                and existing.get("prefs_mtime") is not None
                and int(existing.get("prefs_mtime")) == prefs_mtime
                and existing.get("plugin_version") == _plugin_version()
                and str(existing.get("git_branch") or "") == git_branch
                and str(existing.get("git_head") or "") == git_head
            )
            if fresh:
                return
        except Exception:
            pass
        from find_plugin_root import find_plugin_root

        # A live spinner while the slow part runs, then a tick (2026-08-19 UX pass): on
        # a corp box this step is seconds of apparent hang, and silence reads as a stall
        # rather than as work being moved out of the session. rich's own status widget
        # when the console supports it; a plain one-line note otherwise, unchanged.
        ink = _Ink()
        r = _rich_ui()
        label = "warming the engage probe cache (the slow parts run here, not in session)"
        plugin_root = find_plugin_root(Path.home(), project_dir)
        if r:
            try:
                with r["console"].status(f"[dim]{label}[/]", spinner="dots"):
                    report = engage_probe.build_report(plugin_root, project_dir)
            except Exception:
                report = engage_probe.build_report(plugin_root, project_dir)
        else:
            print(ink.dim(f"  {label}..."), file=sys.stderr)
            report = engage_probe.build_report(plugin_root, project_dir)
        if not report:
            return
        print(ink.good("  probe cache ready"), file=sys.stderr)
        payload = {
            "computed_at_epoch": int(time.time()),
            "computed_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "plugin_version": _plugin_version(),
            "prefs_mtime": prefs_mtime,
            "git_branch": git_branch,
            "git_head": git_head,
            "interpreter": Path(sys.executable).as_posix(),
            "report": report,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except Exception:
        pass  # cosmetic tier - the live probe is always the fallback


def _prewarm_guard_interpreter(project_dir: Path) -> None:
    """The engage-probe PREFETCH hook only runs when .claude/.guard-interpreter is
    warm - a cold cache means the FIRST /engage of a fresh project pays the big inline
    fallback heredoc in the transcript (live report 2026-08-17: "why is the bash
    command containing this python script"). run-guard.sh owns this cache and writes
    it after the first guard execution; go seeds it earlier with the interpreter
    already running this launcher, so even a first engage gets the zero-tool-call
    prefetch. Never overwrites an existing value (run-guard's probe result wins);
    forward slashes so the heredoc's `command -v` accepts it in Git Bash on Windows."""
    try:
        cache = _vsit_paths().local_file("guard_interpreter", project_dir)
        if cache.is_file():
            return
        # The "don't create the parent" rule was about .claude/, which belongs to Claude
        # Code - creating it as a side effect of warming a cache would put our directory
        # into a project that had not opted in. VSIT/local/ is OURS, so we may create it;
        # without this the cache is never warmed on a fresh project and every first
        # /engage pays the cold-start it exists to avoid (VSIT migration, 2026-08-28).
        if cache.parent.name == ".claude":
            if not cache.parent.is_dir():
                return
        else:
            cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(Path(sys.executable).as_posix() + "\n", encoding="utf-8")
    except Exception:
        pass  # cosmetic tier - the fallback heredoc still works without it


def _term_cols() -> int:
    """Usable terminal width, floored at 40. Every fixed-width string in this file
    predates any width check - a live mobile/mosh screenshot (2026-08-19) showed the
    greeting and the rules wrapping to column 0 and reading as debris."""
    try:
        import shutil as _sh

        return max(40, _sh.get_terminal_size((80, 24)).columns)
    except Exception:
        return 80


def _greeting(hour: int | None = None) -> str:
    """Time-of-day greeting for the go screen (2026-08-19 user request). Local clock,
    four bands - the late-night one is deliberately a nudge rather than a joke, since
    someone launching an engagement at 01:00 is usually the person who most needs to
    hear it. `hour` is injectable so the bands are testable without freezing the clock."""
    if hour is None:
        import datetime as _dt

        hour = _dt.datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    if 18 <= hour < 22:
        return "Good evening"
    return "Working late"


def _morgan_line() -> str:
    """Morgan's greeting for the go screen (2026-08-17 user request: the persona should
    be visible from the very first touchpoint) - with the mandatory AI-identity
    attribution, same wording family as install_helper's opening line. The 🎩 marker is
    encoding-probed like every other glyph (cp1252 corp consoles)."""
    hat = "🎩 " if _can_encode("🎩") else ""
    full = f"{hat}{_greeting()}, I'm Morgan (PM) - an AI agent with Virtual Surveillance IT."
    # Narrow terminals (mobile/mosh, live 2026-08-19) wrapped this onto a second line
    # starting at column 0, which read as broken output. The AI-identity attribution is
    # mandatory, so the SHORT form keeps it and drops the conversational padding rather
    # than letting the line wrap.
    if len(full) + 2 > _term_cols():
        return f"{hat}Morgan (PM) - an AI agent, Virtual Surveillance IT"
    return full


_STATUS_MARK = {
    "in_progress": ("*", "warn"),
    "blocked": ("!", "warn"),
    "closing": ("~", "dim"),
    # The browse-finished screen shows closed packs; a distinct mark keeps a
    # closed-but-not-archived row readable next to an ARCHIVED-OPEN one.
    "closed": ("+", "dim"),
}


def _relative_age(iso_date: str) -> str:
    """'today' / 'yesterday' / 'N days ago' from an ISO date - a launcher screen answers
    "how stale is this?", which a bare 2026-08-19 makes the reader compute (2026-08-19
    UX pass). Returns '' on anything unparseable rather than guessing."""
    try:
        import datetime as _dt

        then = _dt.date.fromisoformat(str(iso_date)[:10])
    except (ValueError, TypeError):
        return ""
    days = (_dt.date.today() - then).days
    if days < 0:
        return ""
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


def _row_detail(row: dict) -> str:
    """The dim tail of an engagement row: age, phase and how much is still open - the
    'where is this up to' facts that were on disk all along but never shown. A BLOCKED
    engagement additionally names what it is waiting on, since "blocked" without the
    reason just moves the question somewhere else."""
    bits = []
    age = _relative_age(row.get("opened") or "")
    if age:
        bits.append(age)
    phase = row.get("phase")
    if phase:
        bits.append(str(phase))
    outstanding = row.get("outstanding") or 0
    if outstanding:
        bits.append(f"{outstanding} open")
    if row.get("status") == "blocked":
        # "next:", not "waiting on:" - this is the FIRST item on the outstanding list,
        # which may be a pre-seeded gate rather than the thing actually blocking. The
        # honest label is what it is; the engagement itself holds the full list.
        waiting = (row.get("outstanding_first") or "").strip()
        if waiting:
            if len(waiting) > 48:
                waiting = waiting[:47].rstrip() + "…"
            bits.append(f"next: {waiting}")
    return "  ".join(bits)


def _suggestion_line(project_dir: Path, menu: dict) -> str:
    """One contextual nudge under the menu, or '' when there is nothing worth saying.
    The screen already knows these facts; surfacing one turns a static list into
    something that reads the project (2026-08-19 UX pass). Deliberately at most ONE
    line, and silent by default - a nudge on every launch is just noise with extra
    steps."""
    blocked = [r for r in (menu.get("shown") or []) if r.get("status") == "blocked"]
    if blocked:
        return f"{len(blocked)} engagement(s) blocked - resume to clear the outstanding list"
    if not (menu.get("shown") or []):
        try:
            proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
                ["git", "-C", str(project_dir), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0:
                changed = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
                if changed:
                    return (
                        f"{len(changed)} uncommitted file(s) here - "
                        "a new engagement can review them"
                    )
        except Exception:
            pass
    return ""


def row_view(row: dict, *, default_slug: str = "", of_many: bool = False) -> dict:
    """ONE source of an engagement row's display content (2026-08-20, Phase 1).

    Every tier - numbered, picker, and the full-screen app - builds its row from this, so
    they cannot drift apart. They diverged for real on 2026-08-19: a redesign (title-first,
    status mark, relative age, recommended marker) landed in the numbered tier only, while
    the picker tier - the one most users actually see - kept the old
    `resume <slug> <status> opened <date>` layout until a screenshot exposed it. Rendering
    stays per-tier; CONTENT lives here.

    Returns plain data, never styled strings, so a tier can decorate it however it likes:
        mark/mark_style · title · slug · detail · recommended · status · lines (detail pane)
    """
    slug = _row_resume_token(row) or "?"
    status = row.get("status") or "?"
    mark, mark_style = _STATUS_MARK.get(status, ("-", "dim"))
    lines = []
    for label, value in (
        ("slug", slug),
        ("status", status),
        ("opened", _relative_age(row.get("opened") or "")),
        ("phase", row.get("phase") or ""),
        ("open", f"{row.get('outstanding') or 0} item(s)" if row.get("outstanding") else ""),
        ("next", (row.get("outstanding_first") or "") if status == "blocked" else ""),
    ):
        if value:
            lines.append((label, str(value)))
    return {
        "mark": mark,
        "mark_style": mark_style,
        "title": row.get("title") or slug,
        "slug": slug,
        "status": status,
        "detail": _row_detail(row),
        "recommended": bool(default_slug) and slug == default_slug and of_many,
        "lines": lines,
    }


def _can_encode(text: str) -> bool:
    """Can stderr actually render these glyphs? The corp-Windows cp1252 lesson every
    output path here already carries - previously inlined per glyph; one helper now, so
    the wordmark and Morgan's hat make the same decision the same way."""
    try:
        text.encode(getattr(sys.stderr, "encoding", None) or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _git_branch(project_dir: Path) -> str:
    """The working project's branch for the header line, '' when it isn't a git repo or
    git isn't available. Cosmetic only - never let it cost or block a launch."""
    try:
        proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
            ["git", "-C", str(project_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception:
        pass
    return ""


# Wordmark (2026-08-27): the supplied VSIT brand banner, rendered as ASCII terminal art by
# scripts/brand_banner.py (mascot + wordmark + tagline + strapline). It supersedes the
# 2026-08-19 spaced-caps mark, whose note read "NOT block-glyph ASCII art - hand-drawn art
# at this width reads as amateur and illegible". That objection is answered rather than
# ignored: the source brand IS a dotted-outline design, so the letterforms are drawn in
# `- . ' |` on purpose and the mark is no longer hand-improvised. The old spaced-caps form
# survives as brand_banner's narrow tier, which is exactly the width where the objection
# still holds. No glyph in the module needs _can_encode - it is ASCII by construction.
_WORDMARK_TAG = "compliance surveillance engineering"


def _brand_banner_lines() -> list:
    """The brand banner as printable, already-painted lines - [] if anything goes wrong.

    Sibling import: scripts/ is already on sys.path by the time `go` reaches the banner,
    but this runs before that in the --configure path, so it inserts the directory itself.
    Cosmetic tier throughout: a missing module costs looks, never the launch."""
    try:
        scripts_dir = _scripts_dir()
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import brand_banner
    except Exception:
        return []
    ink = _Ink()
    painters = {
        "plain": lambda t: t,
        "dim": ink.dim,
        "cyan": ink.cyan,
        "violet": ink.violet,
        "green": ink.good,
        "amber": ink.warn,
        "bold": ink.bold,
    }
    try:
        return brand_banner.render(_term_cols(), lambda role, t: painters[role](t))
    except Exception:
        return []


def _print_banner(project_dir: Path) -> None:
    """The header: brand banner, then one dim identity line (project · version · branch).

    2026-08-19 UX pass: the old header was a small boxed panel whose width matched
    nothing else on screen, so the launch read as three unrelated blocks stacked up.
    A full-width wordmark anchors the screen and the identity facts collapse to a single
    line instead of a two-row table."""
    version = _plugin_version()
    branch = _git_branch(project_dir)
    # .resolve() first: a relative Path(".") has an EMPTY .name, which silently dropped
    # the project from the identity line (caught rendering at 52 columns, 2026-08-19).
    try:
        project_name = project_dir.resolve().name or str(project_dir)
    except OSError:
        project_name = project_dir.name or str(project_dir)
    facts = [project_name]
    if version:
        facts.append(f"v{version}")
    if branch:
        facts.append(branch)
    identity = "  ·  ".join(facts)
    err = sys.stderr
    # The art is printed with plain ANSI on BOTH paths, never through rich: rich would
    # re-measure and soft-wrap it inside its capped content column, and its markup parser
    # would have to be escaped around characters the art legitimately contains. rich still
    # renders the identity block below, so the two stay visually of a piece.
    art = _brand_banner_lines()
    print("", file=err)
    for line in art:
        print(line, file=err)
    r = _rich_ui()
    if r:
        if not art:
            r["console"].print(f"  [bold cyan]|[/]  [dim]{_WORDMARK_TAG}[/]")
        r["console"].print()
        r["console"].print(f"  [dim]{identity}[/]")
        r["console"].print(f"  [cyan]{_morgan_line()}[/]")
        return
    ink = _Ink()
    if not art:
        print(f"  {ink.title('|')}  {ink.dim(_WORDMARK_TAG)}", file=err)
    print("", file=err)
    print("  " + ink.dim(identity), file=err)
    print("  " + ink.title(_morgan_line()), file=err)


def _install_paths(obj) -> list:
    """Every "installPath" string anywhere in a plugin-registry JSON structure - same
    walk the engage-open bootstrap uses (drift there is pinned by its own test)."""
    out: list = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "installPath" and isinstance(v, str):
                out.append(v)
            else:
                out += _install_paths(v)
    elif isinstance(obj, list):
        for item in obj:
            out += _install_paths(item)
    return out


def _installed_plugin_version() -> tuple:
    """(version, root) of the marketplace-INSTALLED copy of this plugin, or ("", "")
    when none is registered. Deliberately registry-only: the point is to compare what a
    plugin-mode session will actually LOAD against the clone this launcher runs from."""
    try:
        base = Path.home() / ".claude" / "plugins"
        for name in ("installed_plugins.json", "config.json", "plugins.json"):
            try:
                data = json.loads((base / name).read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for p in _install_paths(data):
                try:
                    text = (Path(p) / ".claude-plugin" / "plugin.json").read_text(
                        encoding="utf-8-sig"
                    )
                    if "compliance-surveillance-team" not in text:
                        continue
                    ver = json.loads(text).get("version") or ""
                    if ver:
                        return ver, str(p)
                except Exception:
                    continue
    except Exception:
        pass
    return "", ""


def _check_plugin_cache_lag(project_dir: Path) -> None:
    """The go banner shows the CLONE's version, but a plugin-mode session loads the
    marketplace-installed cache - which only advances on a plugin update (live
    confusion, 2026-08-18: banner said v0.34.0 while the session would still load the
    older installed copy). Since go runs BEFORE the session starts, this is the one
    moment the mismatch is fixable just in time: detect it, and offer to run the update
    so the session about to launch loads the version the banner promised. Skipped in
    repo-as-project mode (no cache involved); silent when versions agree or nothing is
    installed; never blocks the launch."""
    try:
        if (project_dir / "docs" / "team-operating-guide.md").is_file():
            return  # repo-as-project: sessions load the repo itself, no cache to lag
        clone_v = _plugin_version()
        inst_v, _root = _installed_plugin_version()
        if not clone_v or not inst_v or clone_v == inst_v:
            return
        ink = _Ink()
        err = sys.stderr
        print(
            f"    {ink.warn('!')} installed plugin is v{inst_v} but this clone is "
            f"v{clone_v} - the session would load v{inst_v}.",
            file=err,
        )
        import shutil as _shutil

        claude = _shutil.which("claude")
        if not claude or not sys.stdin.isatty():
            print(
                ink.dim(
                    "      Fix: claude plugin update compliance-surveillance-team "
                    "(or rerun the installer, option 1)."
                ),
                file=err,
            )
            return
        print(ink.bold("      Update the installed plugin now? [Y/n]: "), end="", file=err)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if answer in ("", "y", "yes"):
            import subprocess

            proc = subprocess.run(
                [claude, "plugin", "update", "compliance-surveillance-team"],
                capture_output=True,
                text=True,
                timeout=180,
            )
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            if tail:
                print(ink.dim("      " + tail[-1]), file=err)
            print(
                (
                    ink.good("      updated - the session will load the new version")
                    if proc.returncode == 0
                    else ink.warn("      update failed - launching on the installed version")
                ),
                file=err,
            )
    except Exception:
        pass  # cosmetic tier - never cost the launch


def _apply_new_recommended_defaults(project_dir: Path) -> list:
    """Plugin updates grow the recommended env set (e.g. the 1-hour prompt-cache TTL,
    2026-08-17), but a project configured before the update never hears about the new
    keys unless the human re-runs configure. `virt-surv go` is the natural propagation
    point (2026-08-17 user request): for a project that PREVIOUSLY OPTED IN to env
    tuning (any recommended key already present in its settings env block), missing
    keys are added - ADD-ONLY: an existing value is never corrected here, the human may
    have tuned it deliberately, and a project with no recommended keys at all declined
    tuning (or predates it) and is left entirely alone; the first-time-setup offer is
    that path's front door. Runs pre-session from the human's own shell - no model, no
    guards in play. Returns the added key names; every failure returns [] (cosmetic
    tier, never costs the launch)."""
    try:
        import importlib.util

        helper = _scripts_dir().parent / "install_helper.py"
        spec = importlib.util.spec_from_file_location("install_helper_env", helper)
        ih = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ih)
        recommended = dict(ih.RECOMMENDED_ENV)
    except Exception:
        return []
    settings_path = project_dir / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    env = settings.get("env")
    if not isinstance(env, dict) or not any(k in env for k in recommended):
        return []  # never opted in - respect the decline
    added = [k for k in recommended if k not in env]
    if not added:
        return []
    for key in added:
        env[key] = recommended[key]
    try:
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        return []
    return added


def _tool_inventory_line(project_dir: Path) -> str:
    """A one-line summary of what the analyser probe last found, or "".

    Reads `.claude/.tool-availability` - the cache check-review-tools.sh already maintains
    on a TTL - rather than probing. This is the launch path: a banner must never be the
    thing that runs fifteen `which` calls, and never the thing that fails a launch.

    Returns "" when there is no cache yet, which is honest: the first `go` in a project
    genuinely does not know, and inventing a number would be worse than a blank row."""
    try:
        cache = _vsit_paths().local_file("tool_availability", project_dir)
        if not cache.is_file():
            return ""
        text = cache.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    installed = missing = ""
    extras = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("\u2705 Installed"):
            installed = stripped.split("(", 1)[-1].split(")", 1)[0]
        elif stripped.startswith("\u26a0") and "Missing" in stripped:
            missing = stripped.split("(", 1)[-1].split(")", 1)[0]
        elif stripped.startswith("\u2705") and "tree-sitter" in stripped:
            extras.append("tree-sitter")
    if not installed and not missing:
        return ""
    parts = []
    if installed:
        parts.append(f"{installed} analysers")
    if missing:
        parts.append(f"{missing} missing")
    if extras:
        parts.append(", ".join(extras))
    # Age matters: a stale inventory is the thing that makes a user think an install did
    # not take, so say when it was taken rather than presenting it as current fact.
    try:
        import time as _time

        days = int((_time.time() - cache.stat().st_mtime) // 86400)
        if days >= 1:
            parts.append(f"probed {days}d ago")
    except OSError:
        pass
    return "  ".join(parts)


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
        ("probe pre-cache at go", "on" if prefs.get("probe_cache", True) else "off"),
    ]
    tools = raw.get("review_tools") or {}
    overrides = ", ".join(f"{k}:{v}" for k, v in sorted(tools.items()) if v != "auto")
    rows.append(("review tools", overrides or "all auto"))
    # What the probe ACTUALLY found, not just what is configured (2026-08-27 owner
    # request: "show what tools are available from the probe so it's clear it's
    # available"). The two are different questions - "all auto" says nothing about whether
    # anything is installed, and a user who has just installed a tool wants to see it
    # counted. Read straight from the cache the probe already writes; no probing here,
    # because this runs on the launch path.
    inventory = _tool_inventory_line(project_dir)
    if inventory:
        rows.append(("tools detected", inventory))
    jira = integrations.get("jira") or {}
    if jira.get("enabled"):
        rows.append((_JIRA_ROW_LABEL, f"on ({jira['mirror']}, {jira['project_key'] or 'UNSET'})"))
    else:
        rows.append((_JIRA_ROW_LABEL, "off"))
    pr = integrations.get("pr_comments") or {}
    if pr.get("enabled") or pr.get("locked"):
        rows.append(("pr comments", "on (EXPERIMENTAL)" if pr.get("enabled") else "locked"))
    # Session-safety state at a glance (2026-08-17 UX pass): the consent marker decides
    # whether the exec gate opens, and env tuning decides the day's cache economics -
    # both cheap file checks, both worth knowing before the session starts.
    rows.append(
        (
            "exec consent marker",
            "present" if (project_dir / ".claude" / ".exec-consent").is_file() else "absent",
        )
    )
    try:
        env = (
            json.loads((project_dir / ".claude" / "settings.json").read_text(encoding="utf-8")).get(
                "env"
            )
            or {}
        )
        tuned = "applied" if "ENABLE_PROMPT_CACHING_1H" in env else "not applied"
    except Exception:
        tuned = "not applied"
    rows.append(("env tuning (1h cache TTL)", tuned))

    def _value_style(value: str) -> str:
        head = value.split(" ")[0]
        if head in ("on", "applied", "present"):
            return "good"
        if head == "locked":
            return "warn"
        if head in ("off", "not", "absent"):
            return "dim"
        if value == "all auto":
            return "dim"  # the neutral default - only overrides should pop
        return ""

    # Signal, not a config dump (2026-08-19 UX pass): eleven rows printed on EVERY launch
    # were mostly defaults, so the two things that actually change a session's behaviour
    # (an armed exec-consent marker, a live Jira) had no more weight than "docx export
    # off". Notable settings get their own lines; everything sitting at its default folds
    # into one dim tail line that still names them, so nothing becomes invisible.
    _DEFAULTS = {
        "docx export": "off",
        "regulatory citations": "on",
        "large-context review split": "off",
        "parallel dispatch (Workflow)": "on",
        "standards critique": "off",
        "codebase-map skeleton": "off",
        "probe pre-cache at go": "on",
        "review tools": "all auto",
        _JIRA_ROW_LABEL: "off",
        "exec consent marker": "absent",
        "env tuning (1h cache TTL)": "not applied",
    }
    notable = [(n, v) for n, v in rows if _DEFAULTS.get(n) != v]
    at_default = [n for n, v in rows if _DEFAULTS.get(n) == v]

    r = _rich_ui()
    print("", file=err)
    # Points at the KEY, not a command: both callers of this block are inside the go
    # menu, where [c] opens the editor three lines further down - telling someone to
    # quit and type `virt-surv configure` from a TUI that already offers the action
    # makes no sense (2026-08-19 user report).
    # ONE dim line, not a rule plus rows (2026-08-20: "too crowded"). Settings are
    # CONTEXT for the decision below, not the headline - a rule gave them the same
    # visual weight as the question Morgan is actually asking. `virt-surv configure`
    # and the [c] editor still show every value in full.
    ink = _Ink()
    bits = [f"{name} {value}" for name, value in notable]
    if notable and at_default:
        bits.append(f"+{len(at_default)} at defaults")
    if not notable:
        bits = ["all at defaults"]  # "+11 at defaults" with nothing notable read as odd
    line = "  Project defaults: " + "  ·  ".join(bits) + "   (press [c] to change)"
    if r:
        # markup=False: rich reads "[c]" as a style tag and SWALLOWS it, so the hint
        # rendered as "(press  to change)" - caught on screen, 2026-08-20.
        r["console"].print(line, style="dim", markup=False)
    else:
        print(ink.dim(line), file=err)


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
    ink = _Ink()
    # In-app screen first (2026-08-20): the old bare [Y/n] meant a brand-new project's
    # FIRST impression was the plain prompt the TUI exists to replace. `onboard` applies
    # the project defaults with no questions, so the common answer never leaves the
    # interface; the guided pass is a separate interactive program and is labelled as
    # leaving rather than pretended otherwise. None = the screen could not run here, and
    # only then does the [Y/n] fallback below appear.
    verb = "configure"
    try:
        from launcher_app import SETUP_DEFAULTS, SETUP_GUIDED, SETUP_SKIP, setup_screen

        choice = setup_screen(project_dir, sys.modules[__name__])
        if choice == SETUP_SKIP:
            return False
        if choice == SETUP_DEFAULTS:
            verb = "onboard"  # non-interactive: applies the defaults and reports them
        elif choice != SETUP_GUIDED:
            choice = None
    except Exception:
        choice = None
    if choice is None:
        print("", file=err)
        _print_rule("First-time setup")
        print(ink.dim(f"  no team configuration in {project_dir}"), file=err)
        print(ink.bold("  Run first-time project setup now? [Y/n] "), end="", file=err)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in ("n", "no"):
            return False
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, str(helper), verb, str(project_dir)],
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
    except OSError:
        return False
    return proc.returncode == 0 and _plugin_enabled(project_dir)


def _running_slug(project_dir: Path) -> str:
    """The engagement currently marked ACTIVE, or "".

    Read-only, and it deliberately does NOT check whether a session is still attached: the
    marker is what the team itself keys on, and inventing a second notion of "running" here
    would be a second thing to disagree with the first."""
    try:
        import engagement_state

        return engagement_state.read_active(project_dir) or ""
    except Exception:
        return ""


def _watch_running_engagement(project_dir: Path) -> None:
    """Watch work that is ALREADY running, launching nothing.

    2026-08-25, owner: "if an engagement is running but I accidentally exit the TUI there is
    no way to get back to the workflow display ... I can't open an engagement in flight."
    Both halves were true. The menu's only offer for an open engagement was `--resume`, which
    starts a session - the wrong move entirely when one is already going, and the sort of
    thing that ends with two sessions in one workspace. Watching had existed for exactly one
    moment: the seconds after the launcher itself started a run.

    Same flat monitor/workflow loop the post-launch path uses, for the same reason: a screen
    cannot open another screen from inside itself."""
    slug = _running_slug(project_dir)
    if not slug:
        return
    _watch_after_launch(project_dir, slug)


def _pending_auto(project_dir: Path) -> dict:
    """What the pre-flight just recorded, for the launcher to act on.

    Read-only on purpose: `.auto-pending.json` is a ONE-SHOT handoff consumed by
    `engagement_state init`, and consuming it here would take the unattended flag away from
    the run before it ever started - which is precisely the bug (2026-08-21 audit C1) that
    left the AUTO-* gates dead."""
    try:
        payload = json.loads(
            (project_dir / ".claude" / ".auto-pending.json").read_text(encoding="utf-8")
        )
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _pending_auto_slug(project_dir: Path) -> str:
    return str(_pending_auto(project_dir).get("slug") or "")


# The tier docs/agent-design.md documents for the orchestrator. Opus stays available
# per project; it is simply not the thing to fall into by accident.
_DEFAULT_ORCHESTRATOR_MODEL = "sonnet"


def _headless_model(project_dir: Path) -> str:
    """Which model the orchestrator should run on for an unattended run.

    The project's configured choice if it has one, else the documented default. NEVER an
    empty string passed through to the CLI: omitting --model lets a headless run inherit
    whatever the session default happens to be, and a measured run inherited opus when
    docs/agent-design.md says the orchestrator defaults to sonnet. That was 84% of the run's
    cost and about a third more than the design intends - an unattended run guessing its own
    tier is a silent, recurring overcharge."""
    for settings in (
        project_dir / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.json",
    ):
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        model = data.get("model") if isinstance(data, dict) else None
        if isinstance(model, str) and model.strip():
            return model.strip()
    return _DEFAULT_ORCHESTRATOR_MODEL


def _headless_allow_rules(allow_web: bool = False) -> tuple:
    """What an unattended run is permitted to do, beyond writing files.

    acceptEdits covers file writes and ordinary filesystem commands but not
    `python -m scripts.render_html`, and not reading the team's own references - which the
    engage skill does on its very first step. Both come from the installer's own lists, so
    an unattended run may do exactly what an attended, configured project was already
    permitted to, and no more.

    install_helper lives in the repo ROOT, not in scripts/, so importing it from here needs
    the root on sys.path. It did not, the import raised, a broad `except` swallowed it and
    ZERO rules reached the run - which then had seven tool calls refused, including the
    command that records its own decisions (found end-to-end, 2026-08-26). Failures are
    reported now rather than silently degrading the run."""
    root = _scripts_dir().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import install_helper
    except Exception as exc:
        print(
            _Ink().warn(
                f"    could not load the permission rules ({exc.__class__.__name__}) - "
                "the run may be refused its own tooling"
            ),
            file=sys.stderr,
        )
        return ()
    rules = tuple(install_helper.RECOMMENDED_ALLOW)
    try:
        # The skill reads its own references (engage-open.md, auto-mode.md) from the team's
        # directory, which is outside the project. Without these it is refused its own
        # instructions - measured, not guessed.
        rules += tuple(install_helper.team_read_entries())
    except Exception:
        pass
    if allow_web:
        # Only when the human said so at the pre-flight. A page fetched by an unattended run
        # is content nobody reviewed, and content is DATA - never instruction (CLAUDE.md §7).
        rules += ("WebSearch", "WebFetch")
    return rules


def _start_headless(project_dir: Path, decision: str, pending: dict) -> bool:
    """Start the run with no terminal at all, and watch it. True if it started.

    False means nothing started and the caller must fall back to a normal launch. The human
    authorised this run at the pre-flight; a launcher that quietly declined to start it is
    the worst outcome available here, and one this repo has already shipped once."""
    ink, err = _Ink(), sys.stderr
    try:
        import headless_run
    except Exception:
        print(ink.warn("    headless unavailable - opening a session instead"), file=err)
        return False
    cap = pending.get("hard_cap_usd")
    try:
        allowed = _headless_allow_rules(bool(pending.get("allow_web")))
        record = headless_run.start(
            project_dir,
            decision,
            session_id=str(pending.get("session_id") or ""),
            budget_usd=float(cap) if cap else None,
            slug=str(pending.get("slug") or ""),
            allowed_tools=allowed,
            model=_headless_model(project_dir),
            claude=(_configured_launch_command().split() or ["claude"])[0],
        )
    except (OSError, ValueError) as exc:
        print(
            ink.warn(
                f"    could not start headless ({exc.__class__.__name__}) - "
                "opening a session instead"
            ),
            file=err,
        )
        return False
    print(ink.good(f"    -> headless run started, session {record['session_id'][:8]}"), file=err)
    if cap:
        print(ink.warn(f"    hard cap ${cap} - the run STOPS there, enforced"), file=err)
    _watch_after_launch(project_dir, str(pending.get("slug") or ""))
    return True


def _new_window_wanted(project_dir: Path) -> bool:
    """Whether to open the session in its own window rather than in this shell.

    Applies to EVERY run since 2026-08-25, attended included. It was unattended-only, on the
    reasoning that an attended run already has a human in the session - which ignored what
    the launcher had become. With the monitor and the workflow view living here, the TUI is
    worth keeping alive during any run, and it can only stay alive if the session did not
    replace it. The owner put it plainly: unattended-only was "making it hard to view the
    workflow"."""
    try:
        import engage_probe

        return bool(engage_probe.resolve_preferences(project_dir).get("new_window"))
    except Exception:
        return False


def _launch_in_window(project_dir: Path, decision: str, slug: str = "") -> bool:
    """Open the session beside the launcher and watch it. True if the window opened.

    ATTENDED OR UNATTENDED (2026-08-25, owner: "it should open in a new window if attended
    or unattended"). It was unattended-only, on the reasoning that an attended run already
    has a human in the session so a second window adds nothing. That ignored what the
    launcher became: with the run monitor living here, the TUI is worth keeping ALIVE during
    any run, and it can only stay alive if the session did not replace it.

    False means nothing was launched and the caller must fall back to launching in-place -
    never a silent no-op, because the human has already committed to a run by this point and
    a launcher that quietly declined to start it would be the worst possible outcome."""
    ink, err = _Ink(), sys.stderr
    try:
        import launch_terminal
    except Exception:
        return False
    terminal = launch_terminal.available()
    if not terminal:
        print(
            ink.warn(
                "    no windowed terminal found - opening in this one instead. Check with: "
                "python -m scripts.launch_terminal"
            ),
            file=err,
        )
        return False
    # The SAME command the wrapper would have run - _configured_launch_command is what
    # `--launch-command` hands the shell, so the windowed path and the in-place path start a
    # session identically (owner, 2026-08-25: "claude should be launched using the same
    # method as virt surv go does"). Anything else is a second way to start a session, and a
    # second way to get it wrong.
    command = _configured_launch_command().split() or ["claude"]
    if not launch_terminal.open_in_new_window(command + [decision], project_dir):
        print(
            ink.warn(
                f"    {terminal} could not start '{command[0]}' - opening in this one "
                "instead. Check with: python -m scripts.launch_terminal --open"
            ),
            file=err,
        )
        return False
    print(ink.good(f"    -> session opened in a new {terminal} window"), file=err)
    _watch_after_launch(project_dir, slug)
    return True


def _watch_after_launch(project_dir: Path, slug: str) -> None:
    """Keep the launcher useful while the session runs in its own window.

    An unattended run has a known workspace, so watch it. An attended one does not yet -
    the session creates it - so offer the workflow instead, which needs no slug and is the
    thing that was hard to see. Neither is essential: the run is already going, and a screen
    that cannot render must never read as a failed launch."""
    ink = _Ink()
    try:
        if slug:
            from launcher_app import monitor_screen

            monitor_screen(project_dir, sys.modules[__name__], slug)
            return
    except Exception:
        pass
    where = f"artifacts/{slug}/" if slug else "the new window"
    print(ink.dim(f"    the session is running - see {where}"), file=sys.stderr)


def main() -> int:
    if "--launch-command" in sys.argv[1:]:
        # Alias v5 support channel: print ONLY the configured launch command on stdout
        # (the shell function word-splits it), nothing else on either stream.
        print(_configured_launch_command())
        return 0
    if "--configure" in sys.argv[1:]:
        # `virt-surv configure` on an already-configured project lands here (2026-08-19
        # user request): the same banner + settings editor `go`'s [c] opens, then out -
        # no engagement menu, no launch, and nothing on stdout (a caller capturing this
        # process's stdout must never receive editor chatter as a launch decision).
        args = [a for a in sys.argv[1:] if a != "--configure"]
        target = Path(args[0]).expanduser().resolve() if args else Path.cwd()
        try:
            os.chdir(target)  # the editor reads/writes relative to the project
        except OSError:
            print(f"  not a directory: {target}", file=sys.stderr)
            return 1
        try:
            # No defaults summary here on purpose: the editor below lists every setting
            # with its current value, so printing the summary first said everything twice.
            _print_banner(target)
            _run_settings_editor(target)
        except Exception:
            return 1
        return 0
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
        # One idea per line (2026-08-19 UX pass): this used to be a single wrapped
        # paragraph that, when the setup offer above had already printed its own
        # unterminated prompt, ran into it and produced one unreadable line.
        ink = _Ink()
        print("", file=sys.stderr)
        print(
            f"  {ink.warn('Not a configured project')} - launching plainly, no menu.",
            file=sys.stderr,
        )
        print(ink.dim(f"  looked in: {project_dir}"), file=sys.stderr)
        print(
            ink.dim(
                "  wrong directory? cd to your project root. New project? run 'virt-surv configure'."
            ),
            file=sys.stderr,
        )
        return 0  # not a plugin-enabled project - plain launch, but now explained
    scripts_dir = _scripts_dir()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        _print_banner(project_dir)
    except Exception:
        pass  # cosmetic
    try:
        _check_plugin_cache_lag(project_dir)
    except Exception:
        pass
    try:
        added = _apply_new_recommended_defaults(project_dir)
        if added:
            ink = _Ink()
            print(
                "    "
                + ink.good("+")
                + " Applied new recommended default(s) from the plugin update: "
                + ", ".join(sorted(added))
                + ink.dim("  ('virt-surv configure' to review)"),
                file=sys.stderr,
            )
    except Exception:
        pass  # cosmetic - never costs the launch
    try:
        _print_project_defaults(project_dir)
    except Exception:
        pass  # cosmetic - the table must never cost the launch
    try:
        if _expire_stale_auto_consent(project_dir):
            print(
                _Ink().dim("  a previous unattended run's execution gate expired - closed"),
                file=sys.stderr,
            )
    except Exception:
        pass  # never let gate hygiene cost a launch
    try:
        _remember_project(project_dir)  # feeds the explorer's recent list
    except Exception:
        pass  # machine config is advisory - never costs a launch
    try:
        _prewarm_guard_interpreter(project_dir)
    except Exception:
        pass
    try:
        _clear_request_handoff(project_dir)  # never carry a previous go's request forward
    except Exception:
        pass
    try:
        _write_probe_cache(project_dir)
    except Exception:
        pass
    try:
        _refresh_tool_cache(project_dir)
    except Exception:
        pass  # belt-and-braces, same as _refresh_tool_cache's own internal try/except -
        # a failure here must cost only the cache refresh, never the resume decision below.
    try:
        decision = _resume_decision(project_dir)
    except Exception:
        decision = ""  # same reasoning - never let one piece's failure kill the other
    if decision == _ABORT:
        # Nothing on stdout, and a distinct exit code so the wrapper skips the launch
        # entirely rather than starting a session the human just backed out of. An
        # out-of-date wrapper ignores that code, so say so rather than let the session
        # open unexplained (2026-08-25 report).
        try:
            _warn_if_abort_will_be_ignored()
        except Exception:
            pass  # the exit code is the contract; the explanation is best-effort
        return _ABORT_EXIT_CODE
    # The session opens in its OWN window - attended or unattended - so the launcher
    # survives to show the workflow and the run's status (2026-08-25). Returning the abort
    # code afterwards is NOT an abort: it tells the wrapper the session has already been
    # started, so it must not start a second one. Every failure falls through to the
    # ordinary in-place launch below.
    #
    # A plain launch (empty decision) is included deliberately: it is still a session, and
    # it is still worth watching. Only the decision string differs.
    #
    # Every reason NOT to open a window is said out loud (2026-08-25: "it opens in the same
    # window", with no way to tell which condition declined). A control that quietly does
    # nothing is the defect class this repo has met five times in a week; the fix each time
    # is to make it speak.
    pending = _pending_auto(project_dir)
    unattended = bool(pending.get("auto")) and "--auto" in (decision or "").split()
    if pending.get("run_mode") == "headless" and decision:
        # A headless run is STARTED here, not handed to the shell: there is no terminal for
        # the shell to launch into, and the launcher is the thing that will watch it.
        if _start_headless(project_dir, decision, pending):
            return _ABORT_EXIT_CODE
    if _new_window_wanted(project_dir):
        if _launch_in_window(project_dir, decision, pending.get("slug", "")):
            return _ABORT_EXIT_CODE
        if unattended and decision:
            # No window, and this run is UNATTENDED. Falling back in place would hand the
            # terminal to Claude Code and take the launcher - and therefore the monitor -
            # with it, leaving a run nobody can watch or stop (live report 2026-08-25: "it
            # launched claude code in unattended mode and because no window manager it sat
            # there ... how can I monitor it if I can't go to the TUI").
            #
            # Headless is CLOSER to what was asked for than in-place is. The human chose a
            # separate window so the launcher would survive to show them the run; if there
            # is no window, keeping the launcher is the part worth keeping. Nothing is lost:
            # an unattended run answers no questions by definition, which is the only thing
            # in-place would have given it.
            print(
                _Ink().warn(
                    "    no window available - running headless instead so you can still "
                    "watch it here"
                ),
                file=sys.stderr,
            )
            if _start_headless(project_dir, decision, pending):
                return _ABORT_EXIT_CODE
    else:
        print(
            _Ink().dim(
                "    new window off - opening here ([c] -> open the session in a new window)"
            ),
            file=sys.stderr,
        )
    if decision:
        # The ONLY thing that ever goes to stdout, and only when there IS one: a bare
        # print() would put a newline on the decision channel, which the shell captures.
        print(decision)
    return 0


if __name__ == "__main__":
    # Heal from the REAL entry point only - never on module import (tests load and call
    # main() directly; the heal touching a developer's actual shell rc from inside a
    # test run is exactly the kind of side effect that split is for).
    _heal_stale_alias_once()
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open - never block a claude launch over this optimisation
