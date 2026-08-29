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
    ap.add_argument("command", nargs="?", choices=["go"], default=None,
                    help="go: the engagement launcher for the folder you are in")
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
    a = ap.parse_args(argv)

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

    if launching or a.settings:
        # Real engagement state for the folder the user is standing in - not a mock,
        # and it says which folder it read.
        from .ui import VirtSurvApp
        project = Path(a.project).expanduser() if a.project else Path.cwd()
        rows, note = ([], "")
        if launching:
            rows, note = E.load_engagements(repo, project)
        app = VirtSurvApp(start="launch" if launching else "settings",
                          project=project, rows=rows, note=note)
        app.run()
        return 0

    from .live import InstallerTuiApp

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
