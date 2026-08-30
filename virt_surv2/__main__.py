#!/usr/bin/env python3
"""virt-surv2 — a Textual front end for the existing installer and launcher.

Runs ALONGSIDE `virt-surv`, it does not replace it. Same engine: `install_helper.py`
is imported and driven, never reimplemented, so every Windows fix in it — claude-CLI
discovery, the PATH-shim fallback, `windows_shim_cmdline`, cp1252 handling — applies
here unchanged.

    python -m virt_surv2               the menu - the same seven options as virt-surv
    python -m virt_surv2 --install     straight to the install decisions
    python -m virt_surv2 --update      update only, keeping every setting
    python -m virt_surv2 --demo        dry run: executes nothing, writes nothing
    python -m virt_surv2 --launch      the launcher screen (virt-surv go)
    python -m virt_surv2 --settings    project settings
    python -m virt_surv2 --repo PATH   point at a specific clone

Exit code is the engine's own, so this substitutes for `install_helper.py` in a script.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _bootstrap_path() -> None:
    """Vendored deps first, exactly as install_helper expects when run from the clone.

    Nothing here may import textual before this runs — the whole point of vendoring is
    that a user needs no pip.
    """
    for p in (REPO / "vendor", REPO):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


ALIAS_MARKER = "# --virt-surv2 shortcut (added by python -m virt_surv2 --alias)"


def alias_line() -> str:
    """A function, not an alias: it has to cd into the clone so `python -m` resolves
    the package, and return you to where you were."""
    return (
        f"{ALIAS_MARKER}\n"
        f'virt-surv2() {{ ( cd "{REPO}" && "${{VS_PYTHON:-python3}}" -m virt_surv2 "$@" ); }}\n'
    )


def _rc_candidates() -> list[Path]:
    home = Path.home()
    out = [home / ".bashrc"]
    if (home / ".zshrc").exists():
        out.append(home / ".zshrc")
    return out


def install_alias(write: bool) -> int:
    """Stamp the shortcut into the user's shell rc files, once.

    Kept separate from install_helper's own alias step on purpose: that one owns
    `virt-surv`, and the entire point of virt-surv2 is that both exist side by side.
    """
    line = alias_line()
    if not write:
        print(line, end="")
        return 0

    touched, already = [], []
    for rc in _rc_candidates():
        try:
            existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
        except OSError as exc:
            print(f"  could not read {rc}: {exc}", file=sys.stderr)
            continue
        if ALIAS_MARKER in existing:
            already.append(rc)
            continue
        try:
            sep = "" if existing.endswith("\n") or not existing else "\n"
            with rc.open("a", encoding="utf-8") as fh:
                fh.write(sep + "\n" + line)
            touched.append(rc)
        except OSError as exc:
            print(f"  could not write {rc}: {exc}", file=sys.stderr)

    for rc in touched:
        print(f"  added virt-surv2 to {rc}")
    for rc in already:
        print(f"  virt-surv2 already in {rc}")
    if touched:
        print("\n  open a new terminal, then:  virt-surv2 --demo")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="virt-surv2", description=__doc__.splitlines()[0])
    # `go` for parity with `virt-surv go`, which is how everyone already reaches the
    # launcher. Positional so `virt-surv2 go` reads the same as v1.
    ap.add_argument("command", nargs="?", default=None,
                    help="go: the engagement launcher for the folder you are in. "
                         "Any other subcommand is handed to install_helper unchanged.")
    ap.add_argument("--project", help="folder to read engagements from (default: cwd)")
    ap.add_argument("--repo", help="path to the clone (default: find it)")
    ap.add_argument("--demo", action="store_true",
                    help="dry run — the engine executes nothing and writes nothing")
    ap.add_argument("--launch", action="store_true", help="open the launcher screen")
    ap.add_argument("--settings", action="store_true", help="open project settings")
    ap.add_argument("--advanced", action="store_true", help="advanced / one-off settings")
    ap.add_argument("--diagnostics", action="store_true", help="diagnostics")
    ap.add_argument("--install", action="store_true",
                    help="skip the menu and go straight to the install decisions")
    ap.add_argument("--update", action="store_true",
                    help="update only: new code + plugin, keeping every setting")
    ap.add_argument("--alias", action="store_true",
                    help="register the 'virt-surv2' shell shortcut (idempotent)")
    ap.add_argument("--print-alias", action="store_true",
                    help="print the shell line instead of writing it")
    argv = list(sys.argv[1:] if argv is None else argv)
    a, unknown = ap.parse_known_args(argv)

    # ANYTHING this front end has no screen for goes to the engine's own CLI, verbatim.
    # v2 claims to substitute for install_helper.py in a script; without this it did
    # not - --version, --yes, --branch, --configure DIR, --extensions, --permissions,
    # --archive, --list-engagements and the rest all exited 2 with "unrecognized
    # arguments", and so did every subcommand except `go`.
    passthrough = a.command not in (None, "go", "engage")
    if unknown or passthrough:
        _bootstrap_path()
        try:
            from . import engine as E
            repo = E.find_repo(a.repo)
            ih = E.load_engine(repo)
        except Exception as exc:        # noqa: BLE001
            print(f"virt-surv2: {exc}", file=sys.stderr)
            return 2
        # Its own argv, its own exit code, its own output - the point is that a script
        # calling virt-surv2 gets exactly what install_helper.py would have given it.
        return ih.main(argv) or 0

    if a.alias or a.print_alias:
        return install_alias(write=a.alias)

    _bootstrap_path()

    try:
        from . import engine as E
    except ImportError as exc:
        print(f"virt-surv2 needs textual: {exc}", file=sys.stderr)
        print(f"  expected it vendored at {REPO / 'vendor'}", file=sys.stderr)
        return 2

    # Screens with no engine behind them: useful for looking at the UI, and the only
    # thing that works if the clone cannot be found.


    launching = a.launch or a.command == "go"
    try:
        repo = E.find_repo(a.repo)
        ih = E.load_engine(repo)
    except E.EngineNotFound as exc:
        print(f"virt-surv2: {exc}", file=sys.stderr)
        print("  run it from inside the clone, or pass --repo PATH", file=sys.stderr)
        return 2

    if launching:
        # Self-heal the shortcut, exactly as `virt-surv go` does on its own entry point:
        # both functions live in one stamped block, so a stale block means a stale
        # virt-surv2 too - and until this, only running v1 could fix v2's shortcut.
        try:
            ih.heal_stale_aliases()
        except Exception:               # noqa: BLE001 — never let a heal cost a launch
            pass

    from .live import InstallerTuiApp

    if launching or a.settings:
        # Real engagement state for the folder the user is standing in - not a mock,
        # and it says which folder it read. Engine-backed, because an unconfigured
        # folder gets the first-time setup offer and that has to be able to run it.
        project = Path(a.project).expanduser() if a.project else Path.cwd()
        if launching:
            # Everything `virt-surv go` does before it shows you anything: caches
            # warmed, stale request cleared, project remembered. Skipping it left the
            # probe and tool caches cold, which Morgan then reads at engagement open.
            for label, ok, detail in E.run_prelaunch(repo, project):
                if not ok:
                    print(f"  ! {label}: {detail}", file=sys.stderr)
        rows, note = E.load_engagements(repo, project) if launching else ([], "")
        app = InstallerTuiApp(ih, repo, a.demo,
                              start="launch" if launching else "settings",
                              project=project, rows=rows, note=note)
        app.run()
        if not launching:
            return app.exit_code
        # The launcher's contract, shared with `virt-surv go`: the decision is the ONLY
        # thing on stdout, and 97 means the human backed out so the wrapper launches
        # nothing. A bare print of None would put "None" on the decision channel.
        # If the user opened a different folder in the launcher, ask the parent shell
        # to cd there - a child process cannot do it, which is exactly why the wrapper
        # passes a temp file. Same VIRT_SURV_CD_FILE contract virt-surv go uses.
        cd_file = os.environ.get("VIRT_SURV_CD_FILE")
        chosen = getattr(app, "project", None)
        if cd_file and chosen and Path(chosen).resolve() != project.resolve():
            try:
                Path(cd_file).write_text(str(Path(chosen).resolve()), encoding="utf-8")
            except OSError:
                pass                    # cosmetic - never fail a launch over a cd

        decision = getattr(app, "decision", None)
        if decision is None:
            return E.ABORT_EXIT_CODE

        # Headless / new-window, exactly as virt-surv go decides it. If the session has
        # already been started here, 97 tells the wrapper to launch nothing - otherwise
        # the user gets two.
        started = E.dispatch_decision(
            repo, Path(getattr(app, "project", project) or project), decision,
            report=lambda m: print(f"    {m}", file=sys.stderr))
        if started:
            return E.ABORT_EXIT_CODE
        if decision:
            if sys.stdout.isatty():
                # Nothing is capturing stdout, so no wrapper is going to act on this.
                # Printing the bare decision here is what "selecting new engagement just
                # sent /engage --new to the terminal" looked like: correct output, no
                # reader. Say what happened instead of emitting it into the void.
                print("", file=sys.stderr)
                print("  This chose:", file=sys.stderr)
                print(f"    {decision}", file=sys.stderr)
                print("", file=sys.stderr)
                print("  ...but nothing is set up to launch it. The 'virt-surv2' shell",
                      file=sys.stderr)
                print("  shortcut is what starts Claude Code with that. Yours is out of",
                      file=sys.stderr)
                print("  date or missing.", file=sys.stderr)
                print("", file=sys.stderr)
                print("  Fix it:  virt-surv2 --advanced  ->  Manage the shell shortcuts",
                      file=sys.stderr)
                print("  then open a new terminal.", file=sys.stderr)
                return 0
            print(decision)
        return 0

    start = ("advanced" if a.advanced else
             "diagnostics" if a.diagnostics else
             "decide" if a.install else
             "menu")
    app = InstallerTuiApp(ih, repo, a.demo, start=start)
    if a.update:
        app.start = "menu"
        app.pending_action = "update"
    app.run()
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
