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


_ENV_ROW_LABEL = "env tuning (timeouts + 1h cache TTL)"


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
            json.loads(
                (project_dir / ".claude" / "settings.json").read_text(encoding="utf-8")
            ).get("env")
            or {}
        )
    except Exception:
        env = {}
    env_on = "ENABLE_PROMPT_CACHING_1H" in env
    rows.append((_ENV_ROW_LABEL, "applied" if env_on else "not applied", env_on))
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
    if action != "d":
        try:
            action = int(action)  # the input() tier hands over strings
        except (TypeError, ValueError):
            return f"1-{env_i}, d or b, please."
    if action == "d":
        for _, key in _TOGGLE_PREFS:
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
            return f"1-{env_i}, d or b, please."
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
        out.append(
            ("class:dim", "  Enter/Space/click toggles · d machine defaults · Esc done")
        )
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
            print(ink.dim(f"    {note}"), file=err)


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
    while True:
        try:
            menu = engagement_state.resume_menu(project_dir / "artifacts")
        except Exception:
            return ""
        shown = menu.get("shown") or []
        # Zero open engagements used to skip the pause entirely (straight plain
        # launch); the menu now shows regardless (2026-08-17 user preference: "I
        # prefer it always pauses") - [c]/[a] stay reachable, and non-interactive
        # callers are unaffected: no tty means input() raises EOFError, which is the
        # same plain launch as before.
        decision = _menu_round(project_dir, engagement_state, menu, shown)
        if decision != "__again__":
            return decision


def _pt_menu_round(p, project_dir: Path, engagement_state, menu: dict, shown: list) -> str:
    """prompt_toolkit tier of the go menu: arrow/mouse picker over the same entries as
    the numbered flow, same return contract (decision, "" for in-session/plain, or
    "__again__" after a side action)."""
    entries = []
    slug_w = max((len(_row_resume_token(r) or "?") for r in shown), default=0)
    for i, row in enumerate(shown):
        slug = _row_resume_token(row) or "?"
        status = row.get("status") or "?"
        opened = row.get("opened") or ""
        title = row.get("title") or ""
        frags = [
            ("", "resume "),
            ("class:slug", slug.ljust(slug_w)),
            ("class:warn" if status in ("in_progress", "blocked") else "class:dim", f"  {status}"),
        ]
        if opened:
            frags.append(("class:dim", f"  opened {opened}"))
        if title:
            frags.append(("", f"  {title}"))
        entries.append((("resume", i), frags, None))
    subtitle = ""
    if not shown:
        archived = menu.get("archived") or 0
        subtitle = f"none open ({archived} archived)" if archived else "none open"
    entries.append((("new",), "start new", "n"))
    entries.append((("settings",), "change a project setting", "c"))
    if shown:
        entries.append((("archive",), "archive engagement(s)", "a"))
    launch_label = "decide inside the session instead" if shown else "just launch"
    entries.append((("launch",), launch_label, None))
    default_index = 0
    default_slug = menu.get("default") or ""
    for i, row in enumerate(shown):
        if (_row_resume_token(row) or "") == default_slug:
            default_index = i
            break
    pick = _pt_pick(
        p,
        "Open engagements" if shown else "Engagements",
        entries,
        default_index=default_index,
        subtitle=subtitle,
    )
    ink = _Ink()
    if pick is _PT_FAILED:
        return "__pt_fallback__"
    if pick is None or pick[0] == "launch":
        print(ink.dim("    -> launching"), file=sys.stderr)
        return ""
    if pick[0] == "settings":
        try:
            _run_settings_editor(project_dir)
        except Exception:
            pass  # cosmetic tier
        return "__again__"
    if pick[0] == "archive":
        try:
            _archive_menu(project_dir, engagement_state, menu)
        except Exception:
            pass
        return "__again__"
    engage_cmd = _engage_command(project_dir)
    if pick[0] == "new":
        print(ink.dim("    -> starting new"), file=sys.stderr)
        return f"{engage_cmd} --new"
    slug = _row_resume_token(shown[pick[1]])
    if slug:
        print(ink.dim(f"    -> resuming {slug}"), file=sys.stderr)
        return f"{engage_cmd} --resume {slug}"
    return ""


def _menu_round(project_dir: Path, engagement_state, menu: dict, shown: list) -> str:
    """One render-and-ask round of the engagement menu. Returns the decision string, ""
    for decide-in-session, or the sentinel "__again__" after a side action ([c] settings,
    [a] archive) so the caller recomputes the menu - archiving changes it - and asks
    again."""
    err = sys.stderr
    ink = _Ink()
    p = _ptk_ui()
    if p:
        decision = _pt_menu_round(p, project_dir, engagement_state, menu, shown)
        if decision != "__pt_fallback__":
            return decision
        # The pt widget could not run in this console (live Windows report
        # 2026-08-17: a silent plain launch) - the numbered tier below takes over.
    print("", file=err)
    _print_rule("Open engagements" if shown else "Engagements")
    if shown:
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
    else:
        archived = menu.get("archived") or 0
        note = f"none open ({archived} archived)" if archived else "none open"
        print(ink.dim(f"    {note}"), file=err)
    print(f"    {ink.bold('[n]')} start new", file=err)
    settings_opt = f"    {ink.bold('[c]')} change a project setting"
    if shown:
        settings_opt += f"   {ink.bold('[a]')} archive engagement(s)"
    print(settings_opt, file=err)
    enter_label = "just launch" if not shown else "decide inside the session instead"
    print(f"    {ink.dim(f'[Enter] {enter_label}')}", file=err)
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
            _run_settings_editor(project_dir)
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
            if hot and not sel:
                out.append(("class:dim", "  ", _click))
                out.append(("class:hot", f"[{hot}]", _click))
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
        cache = project_dir / ".claude" / ".guard-interpreter"
        if cache.is_file() or not cache.parent.is_dir():
            return
        cache.write_text(Path(sys.executable).as_posix() + "\n", encoding="utf-8")
    except Exception:
        pass  # cosmetic tier - the fallback heredoc still works without it


def _morgan_line() -> str:
    """Morgan's greeting for the go screen (2026-08-17 user request: the persona should
    be visible from the very first touchpoint) - with the mandatory AI-identity
    attribution, same wording family as install_helper's opening line. The 🎩 marker is
    encoding-probed like every other glyph (cp1252 corp consoles)."""
    try:
        "🎩".encode(getattr(sys.stderr, "encoding", None) or "utf-8")
        hat = "🎩 "
    except (UnicodeEncodeError, LookupError):
        hat = ""
    return f"{hat}Morgan (PM) here - I'm an AI agent with Virtual Surveillance IT."


def _print_banner(project_dir: Path) -> None:
    version = _plugin_version()
    r = _rich_ui()
    if r:
        body = r["Text"]()
        body.append("project  ", style="dim")
        body.append(project_dir.name, style="bold")
        if version:
            body.append("\nplugin   ", style="dim")
            body.append(f"v{version}")
        r["console"].print()
        r["console"].print(
            r["Panel"](
                body,
                title="[bold cyan]Virtual Surv-IT[/]",
                title_align="left",
                box=r["panel_box"],
                border_style="cyan",
                padding=(0, 2),
                expand=False,
            )
        )
        r["console"].print("  " + _morgan_line(), style="cyan")
        return
    ink = _Ink()
    err = sys.stderr
    print("", file=err)
    print(
        ink.dim("=== ") + ink.title("Virtual Surv-IT") + ink.dim(" " + "=" * 45), file=err
    )
    print(f"    project  {ink.bold(project_dir.name)}", file=err)
    if version:
        print(f"    plugin   v{version}", file=err)
    print(f"    {ink.title(_morgan_line())}", file=err)


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
    r = _rich_ui()
    print("", file=err)
    _print_rule("Project defaults", note="'virt-surv configure' to change")
    if r:
        table = r["Table"](box=None, show_header=False, padding=(0, 1), pad_edge=False)
        table.add_column(style="default", no_wrap=True)
        table.add_column()
        style_map = {"good": "green", "warn": "yellow", "dim": "dim", "": "default"}
        for name, value in rows:
            table.add_row("  " + name, r["Text"](value, style=style_map[_value_style(value)]))
        r["console"].print(table)
        return
    ink = _Ink()
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        dots = ink.dim("." * (width - len(name) + 2))
        style = _value_style(value)
        shown = {"good": ink.good, "warn": ink.warn, "dim": ink.dim}.get(style, lambda t: t)(value)
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
    _print_rule("First-time setup")
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
        _prewarm_guard_interpreter(project_dir)
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
