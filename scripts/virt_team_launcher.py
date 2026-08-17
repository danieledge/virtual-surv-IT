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

import json
import os
import sys
from pathlib import Path


def _scripts_dir() -> Path:
    """This script always lives directly in scripts/ (never staged/dual-copy like the
    UserPromptSubmit hook) - its siblings are simply its own directory."""
    return Path(__file__).resolve().parent


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
_EXPECTED_ALIAS_VERSION = 5


def _heal_stale_alias_once() -> None:
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
        if cfg.get("alias_heal_checked") == _EXPECTED_ALIAS_VERSION:
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
)


def _config_editor(project_dir: Path) -> None:
    """Inline project-settings editor on the go screen (2026-08-17 user request): pick a
    setting by number to toggle it, [d] restores machine defaults, [b] done. Writes the
    project's team-preferences.json directly, preserving every unrelated key; restoring
    defaults means REMOVING the project-level keys - resolve_preferences' key-presence
    precedence then lets the machine tier speak again. All interaction on stderr/stdin;
    stdout stays the decision channel. Every failure path just returns - cosmetic tier."""
    err = sys.stderr
    ink = _Ink()
    prefs_path = project_dir / ".claude" / "team-preferences.json"
    try:
        import engage_probe
    except Exception:
        return
    while True:
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except Exception:
            prefs = {}
        try:
            effective = engage_probe.resolve_preferences(project_dir)
        except Exception:
            return
        settings_path = project_dir / ".claude" / "settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}
        env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
        env_label = "env tuning (timeouts + 1h cache TTL)"
        env_on = "ENABLE_PROMPT_CACHING_1H" in env
        print("", file=err)
        print(_rule(ink, "Project settings", note="pick a number to toggle"), file=err)
        width = max(
            max(len(label) for label, _ in _TOGGLE_PREFS), len(env_label)
        )
        for i, (label, key) in enumerate(_TOGGLE_PREFS, 1):
            if key == "extra_formats":
                on = "docx" in (effective.get("extra_formats") or [])
            else:
                on = bool(effective.get(key))
            dots = ink.dim("." * (width - len(label) + 2))
            val = ink.good("on") if on else ink.dim("off")
            src = "" if key in prefs or (key == "extra_formats" and key in prefs) else ink.dim(
                "  (machine default)"
            )
            print(f"    {ink.bold(f'[{i}]')} {label} {dots} {val}{src}", file=err)
        env_i = len(_TOGGLE_PREFS) + 1
        env_dots = ink.dim("." * (width - len(env_label) + 2))
        env_val = ink.good("applied") if env_on else ink.dim("not applied")
        print(f"    {ink.bold(f'[{env_i}]')} {env_label} {env_dots} {env_val}", file=err)
        print(f"    {ink.bold('[d]')} restore machine defaults (drop project choices)", file=err)
        print(f"    {ink.bold('[b]')} done", file=err)
        print(ink.bold("    Setting: "), end="", file=err)
        try:
            choice = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if choice in ("", "b"):
            return
        if choice == "d":
            # Scoped to the team preferences: env tuning has no machine tier to
            # restore to - its own row toggles it explicitly.
            for _, key in _TOGGLE_PREFS:
                prefs.pop(key, None)
        elif choice == str(env_i):
            # The env bundle (2026-08-17 follow-up: the TTL row was on the defaults
            # table but missing here). ON adds the missing recommended keys, add-only,
            # same contract as the go-time propagation; OFF removes only keys still AT
            # their recommended value, so a custom-tuned timeout survives and is
            # reported rather than silently dropped.
            try:
                import importlib.util as _ilu

                spec = _ilu.spec_from_file_location(
                    "install_helper_env2", _scripts_dir().parent / "install_helper.py"
                )
                ih = _ilu.module_from_spec(spec)
                spec.loader.exec_module(ih)
                recommended = dict(ih.RECOMMENDED_ENV)
            except Exception:
                print(ink.dim("    could not load the recommended env set - unchanged"), file=err)
                continue
            env = dict(env)
            if env_on:
                kept = [k for k in recommended if k in env and env[k] != recommended[k]]
                for k in recommended:
                    if k in env and env[k] == recommended[k]:
                        del env[k]
                if kept:
                    print(
                        ink.dim(
                            "    kept custom-tuned value(s): " + ", ".join(sorted(kept))
                        ),
                        file=err,
                    )
            else:
                for k, v in recommended.items():
                    env.setdefault(k, v)
            settings["env"] = env
            try:
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(
                    json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                print(ink.dim("    could not write settings.json - unchanged"), file=err)
            continue
        else:
            try:
                idx = int(choice)
                label, key = _TOGGLE_PREFS[idx - 1]
            except (ValueError, IndexError):
                print(ink.dim(f"    1-{env_i}, d or b, please."), file=err)
                continue
            if key == "extra_formats":
                current = "docx" in (effective.get("extra_formats") or [])
                formats = [f for f in (prefs.get("extra_formats") or []) if f != "docx"]
                prefs["extra_formats"] = formats if current else formats + ["docx"]
            else:
                prefs[key] = not bool(effective.get(key))
        try:
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            prefs_path.write_text(
                json.dumps(prefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            print(ink.dim("    could not write team-preferences.json - unchanged"), file=err)
            return


def _archive_menu(project_dir: Path, es, menu: dict) -> None:
    """Archive engagements from the go screen (2026-08-17 user request): a number
    archives that engagement, 'all' archives every listed one, [b] back. Archiving an
    OPEN pack is allowed but informed: it uses --force and the DoD checker will show it
    as ARCHIVED-OPEN - stated before confirming, never silently."""
    err = sys.stderr
    ink = _Ink()
    shown = menu.get("shown") or []
    if not shown:
        print(ink.dim("    nothing to archive"), file=err)
        return
    print("", file=err)
    print(_rule(ink, "Archive engagements"), file=err)
    for i, row in enumerate(shown, 1):
        slug = _row_resume_token(row) or "?"
        status = row.get("status") or "?"
        print(f"    {ink.bold(f'[{i}]')} {slug}  {ink.dim(status)}", file=err)
    open_rows = menu.get("open") or shown
    print(
        f"    {ink.bold('[all]')} archive ALL open engagements ({len(open_rows)})", file=err
    )
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
    targets = []
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
    import contextlib

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
        print(f"    {slug}: {marker}", file=err)


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
    while True:
        try:
            menu = engagement_state.resume_menu(project_dir / "artifacts")
        except Exception:
            return ""
        shown = menu.get("shown") or []
        if not shown:
            return ""  # nothing open (any more) - nothing to decide, plain launch
        decision = _menu_round(project_dir, engagement_state, menu, shown)
        if decision != "__again__":
            return decision


def _menu_round(project_dir: Path, engagement_state, menu: dict, shown: list) -> str:
    """One render-and-ask round of the engagement menu. Returns the decision string, ""
    for decide-in-session, or the sentinel "__again__" after a side action ([c] settings,
    [a] archive) so the caller recomputes the menu - archiving changes it - and asks
    again."""
    err = sys.stderr
    ink = _Ink()
    print("", file=err)
    print(_rule(ink, "Open engagements"), file=err)
    slug_w = max(len(_row_resume_token(r) or "?") for r in shown)
    status_w = max(len(r.get("status") or "?") for r in shown)
    for i, row in enumerate(shown, 1):
        slug = _row_resume_token(row) or "?"
        status = row.get("status") or "?"
        opened = row.get("opened") or ""
        title = row.get("title") or ""
        status_col = (
            ink.warn(status.ljust(status_w))
            if status in ("in_progress", "blocked")
            else ink.dim(status.ljust(status_w))
        )
        opened_col = ink.dim(f"opened {opened}") if opened else ""
        print(
            f"    {ink.bold(f'[{i}]')} resume {slug.ljust(slug_w)}  {status_col}  "
            f"{opened_col}  {title}",
            file=err,
        )
    more = menu.get("more") or 0
    if more:
        print(ink.dim(f"        (+{more} more not shown)"), file=err)
    print(f"    {ink.bold('[n]')} start new", file=err)
    print(
        f"    {ink.bold('[c]')} change a project setting   {ink.bold('[a]')} archive "
        "engagement(s)",
        file=err,
    )
    print(f"    {ink.dim('[Enter] decide inside the session instead')}", file=err)
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
        print(_Ink().bold("    Choice: "), end="", file=err)
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        return ""  # no tty / interrupted - fall through to deciding in-session
    if not choice:
        return ""
    if choice.lower() == "c":
        try:
            _config_editor(project_dir)
            _print_project_defaults(project_dir)
        except Exception:
            pass  # cosmetic tier
        return "__again__"
    if choice.lower() == "a":
        try:
            _archive_menu(project_dir, engagement_state, menu)
        except Exception:
            pass
        return "__again__"
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


def _rule(ink: _Ink, label: str = "", note: str = "", width: int = 64) -> str:
    if not label:
        return ink.dim("=" * width)
    body = f"--- {label} "
    pad = width - len(body) - (len(note) + 1 if note else 0)
    line = body + "-" * max(pad, 3) + (f" {note}" if note else "")
    return ink.dim(line[:width]) if not note else ink.dim(body + "-" * max(pad, 3)) + " " + ink.dim(note)


def _plugin_version() -> str:
    try:
        manifest = _scripts_dir().parent / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text(encoding="utf-8-sig")).get("version") or ""
    except Exception:
        return ""


def _print_banner(project_dir: Path) -> None:
    ink = _Ink()
    err = sys.stderr
    version = _plugin_version()
    print("", file=err)
    print(
        ink.dim("=== ") + ink.title("Virtual Surv-IT") + ink.dim(" " + "=" * 45), file=err
    )
    print(f"    project  {ink.bold(project_dir.name)}", file=err)
    if version:
        print(f"    plugin   v{version}", file=err)


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
            json.loads(
                (project_dir / ".claude" / "settings.json").read_text(encoding="utf-8")
            ).get("env")
            or {}
        )
        tuned = "applied" if "ENABLE_PROMPT_CACHING_1H" in env else "not applied"
    except Exception:
        tuned = "not applied"
    rows.append(("env tuning (1h cache TTL)", tuned))
    ink = _Ink()
    width = max(len(name) for name, _ in rows)
    print("", file=err)
    print(_rule(ink, "Project defaults", note="'virt-surv configure' to change"), file=err)
    for name, value in rows:
        dots = ink.dim("." * (width - len(name) + 2))
        head = value.split(" ")[0]
        if head in ("on", "applied", "present"):
            shown = ink.good(value)
        elif head == "locked":
            shown = ink.warn(value)
        elif head in ("off", "not", "absent"):
            shown = ink.dim(value)
        else:
            shown = value
        print(f"    {name} {dots} {shown}", file=err)


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
    print("", file=err)
    print(_rule(ink, "First-time setup"), file=err)
    print(f"    (virt-team: {project_dir} has no team configuration yet.)", file=err)
    print(ink.bold("    Run first-time project setup now? [Y/n] "), end="", file=err)
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
    if "--launch-command" in sys.argv[1:]:
        # Alias v5 support channel: print ONLY the configured launch command on stdout
        # (the shell function word-splits it), nothing else on either stream.
        print(_configured_launch_command())
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
        _print_banner(project_dir)
    except Exception:
        pass  # cosmetic
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
    # Heal from the REAL entry point only - never on module import (tests load and call
    # main() directly; the heal touching a developer's actual shell rc from inside a
    # test run is exactly the kind of side effect that split is for).
    _heal_stale_alias_once()
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open - never block a claude launch over this optimisation
