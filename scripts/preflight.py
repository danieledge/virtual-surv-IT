#!/usr/bin/env python3
"""What the launcher knows BEFORE it starts an action, in one declared table.

WHY THIS EXISTS (2026-09-10 TUI walkthrough). Nearly every user-facing defect in that
review had the same shape: an action starts, discovers a precondition halfway through, and
each of the three rendering tiers invents its own way of telling the user, or does not tell
them at all. Setup failed and the user was told they were in the wrong directory. The
update screen promised a stash the run then refused. An option was missing and nothing said
which precondition made it missing.

More `except` blocks do not fix that. A single table does: every precondition is a NAMED
check with a sentence written for a person, actions declare which checks they need, and one
place answers "why is this option unavailable".

THREE RULES THIS FILE KEEPS.

1. **A check never raises and never blocks for long.** A predicate that throws resolves to
   "could not determine", which WARNS rather than blocks - refusing to launch because a
   `git` call failed would be worse than the thing being checked for. Anything shelling out
   carries a timeout.
2. **Evaluated once, read many times.** `Report` caches, because the menu asks the same
   questions on every repaint and some answers cost a subprocess.
3. **No launcher imports.** This module is imported BY the launcher, tests it without a
   terminal, and must never import it back.

WHAT THIS IS NOT. It does not decide what happens on a failure. The caller does: dim a row,
refuse an action, print a line. Preflight only answers what is true and supplies the words.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# A check that shells out gets this long, once. Slow enough for a cold corporate box with
# an antivirus in the path, short enough that a menu repaint never visibly stalls.
_TIMEOUT = 5

# How the one captured subprocess here decodes its output (2026-09-12 audit, L-9). NEVER a
# bare text=True: that decodes with the CONSOLE code page on Windows, and cp1252 has
# undefined bytes (0x81, 0x8d, ...), so git output carrying one raises UnicodeDecodeError
# inside subprocess's own reader thread. install_helper.run_cmd was fixed for exactly that
# after a live corporate report; this call and nine in the launcher were not.
_DECODE = {"encoding": "utf-8", "errors": "replace"}

BLOCKS = "blocks"
WARNS = "warns"


@dataclass(frozen=True)
class Check:
    """One precondition.

    `sentence` is shown to a PERSON, so it says what is wrong and what to do, never which
    function returned False. `severity` is the caller's hint, not an instruction: BLOCKS
    means an action needing this cannot sensibly run, WARNS means it can but the user
    should know.
    """

    name: str
    sentence: str
    severity: str = BLOCKS


@dataclass
class Result:
    check: Check
    ok: bool
    detail: str = ""  # what was actually found, when it helps ("branch has no upstream")

    @property
    def undetermined(self) -> bool:
        """The predicate could not answer. Treated as a warning, never as a block."""
        return self.detail.startswith("could not determine")


# --------------------------------------------------------------------------- the table
#
# Order is display order. Keep the sentences in the second person and free of internals: a
# person reading "VIRT_SURV_CD_FILE is unset" learns nothing they can act on.

CHECKS: tuple[Check, ...] = (
    Check(
        "git",
        "git is not on PATH, so anything that reads or updates this checkout will fail.",
    ),
    Check(
        "git_repo",
        "This folder is not a git repository. Run virt-surv from your project root.",
    ),
    Check(
        "claude_on_path",
        "The `claude` command cannot be found from this shell. Check your PATH, or "
        "reinstall the CLI.",
    ),
    Check(
        "wrapper_current",
        "Your shell is still running an out-of-date virt-surv function, which ignores the "
        "launcher's exit code: pressing Esc, or choosing a new window, can start a second "
        "session anyway. Open a new terminal, or re-source your shell profile.",
    ),
    Check(
        "project_configured",
        "The team is not set up in this project, so a session here is plain Claude Code. "
        "Run virt-surv configure to set it up.",
        severity=WARNS,
    ),
    Check(
        "config_writable",
        "This project's .claude/ directory is not writable, so settings and consent "
        "cannot be recorded.",
    ),
    Check(
        "clean_tree",
        "This checkout has uncommitted changes. An update refuses to run on a dirty tree "
        "rather than risk them: commit or stash first.",
    ),
    Check(
        "upstream",
        "This branch has no upstream, so there is nothing to update from.",
    ),
    Check(
        "not_home_dir",
        "This looks like your home directory rather than a project. Running the team here "
        "would treat your whole home folder as the codebase.",
        severity=WARNS,
    ),
)

_BY_NAME = {c.name: c for c in CHECKS}


# ----------------------------------------------------------------------- the predicates


def _run(args: list, cwd: Path) -> tuple[int, str]:
    """A bounded, non-raising subprocess. Returns (code, stdout); code 127 means it could
    not be run at all, which every caller treats as undetermined rather than as False."""
    try:
        done = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            **_DECODE,
            timeout=_TIMEOUT,
            check=False,
        )
        return done.returncode, (done.stdout or "").strip()
    except Exception:  # noqa: BLE001 - a check must never raise
        return 127, ""


def _git(project_dir: Path) -> tuple[bool, str]:
    return (shutil.which("git") is not None, "")


def _git_repo(project_dir: Path) -> tuple[bool, str]:
    if shutil.which("git") is None:
        return True, "could not determine: git is not installed"
    code, out = _run(["git", "rev-parse", "--is-inside-work-tree"], project_dir)
    if code == 127:
        return True, "could not determine: git would not run"
    return out == "true", ""


def _claude_on_path(project_dir: Path) -> tuple[bool, str]:
    # shutil.which only, deliberately: running `claude --version` to prove it works costs
    # a process start on every launch, and a shim that exists but is policy-blocked is the
    # corporate case this cannot detect anyway.
    return (shutil.which("claude") is not None, "")


def _wrapper_current(project_dir: Path) -> tuple[bool, str]:
    # VIRT_SURV_CD_FILE is exported by the v7 wrapper and by nothing else: the cd handshake
    # and the exit-code check landed together, so its absence means an older function is
    # loaded in this shell and will ignore exit 97. A child process cannot change its
    # parent's loaded functions, so this can only be reported, never fixed from here.
    if os.environ.get("VIRT_SURV_CD_FILE"):
        return True, ""
    # Not launched through the wrapper at all (a direct `python virt_team_launcher.py`) is
    # not the failure this describes, and saying so would be noise.
    if not os.environ.get("VIRT_SURV_VIA_WRAPPER", ""):
        return True, "not launched through the shell wrapper"
    return False, "pre-v7 wrapper loaded in this shell"


def _project_configured(project_dir: Path) -> tuple[bool, str]:
    if (project_dir / ".claude" / "team-preferences.json").is_file():
        return True, ""
    if (project_dir / "VSIT" / "config" / "preferences.json").is_file():
        return True, ""
    return False, ""


def _config_writable(project_dir: Path) -> tuple[bool, str]:
    target = project_dir / ".claude"
    probe = target if target.is_dir() else project_dir
    return (os.access(probe, os.W_OK), "")


def _clean_tree(project_dir: Path) -> tuple[bool, str]:
    if shutil.which("git") is None:
        return True, "could not determine: git is not installed"
    code, out = _run(["git", "status", "--porcelain"], project_dir)
    if code != 0:
        return True, "could not determine: git status would not run"
    return (out == "", f"{len(out.splitlines())} changed files" if out else "")


def _upstream(project_dir: Path) -> tuple[bool, str]:
    if shutil.which("git") is None:
        return True, "could not determine: git is not installed"
    code, _out = _run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], project_dir
    )
    if code == 127:
        return True, "could not determine: git would not run"
    return code == 0, "" if code == 0 else "branch has no upstream"


def _not_home_dir(project_dir: Path) -> tuple[bool, str]:
    try:
        return (project_dir.resolve() != Path.home().resolve(), "")
    except Exception:  # noqa: BLE001
        return True, "could not determine: the path would not resolve"


_PREDICATES = {
    "git": _git,
    "git_repo": _git_repo,
    "claude_on_path": _claude_on_path,
    "wrapper_current": _wrapper_current,
    "project_configured": _project_configured,
    "config_writable": _config_writable,
    "clean_tree": _clean_tree,
    "upstream": _upstream,
    "not_home_dir": _not_home_dir,
}


# ------------------------------------------------------------- what each action needs
#
# The point of naming these: an action whose checks fail is still SHOWN, dimmed, with the
# failing check's sentence as the reason. A missing option nobody can explain is the defect
# this table exists to remove.

REQUIRES: dict = {
    "update": ("git", "git_repo", "clean_tree", "upstream"),
    "new_window": ("wrapper_current",),
    "headless": ("config_writable",),
    "configure": ("config_writable", "not_home_dir"),
    "engage": ("project_configured",),
}


@dataclass
class Report:
    """Every check, evaluated once for one project directory."""

    project_dir: Path
    results: dict = field(default_factory=dict)

    def result(self, name: str) -> Result:
        if name not in self.results:
            check = _BY_NAME[name]
            try:
                ok, detail = _PREDICATES[name](self.project_dir)
            except Exception as exc:  # noqa: BLE001 - rule 1: a check never raises
                ok, detail = True, f"could not determine: {exc.__class__.__name__}"
            self.results[name] = Result(check, bool(ok), detail)
        return self.results[name]

    def ok(self, name: str) -> bool:
        return self.result(name).ok

    def failing(self, names) -> list:
        """The failed checks among `names`, in table order, worst first."""
        failed = [self.result(n) for n in names if not self.result(n).ok]
        return sorted(failed, key=lambda r: 0 if r.check.severity == BLOCKS else 1)

    def blocks(self, action: str) -> bool:
        """True when this action cannot sensibly run. WARNS-level failures never block."""
        return any(r.check.severity == BLOCKS for r in self.failing(REQUIRES.get(action, ())))

    def why_unavailable(self, action: str) -> str:
        """The one sentence to show a person, or "" when the action is fine.

        This is the whole point of the table: every screen, in every tier, gets the same
        answer to "why can I not do this", from one place.
        """
        failed = self.failing(REQUIRES.get(action, ()))
        return failed[0].check.sentence if failed else ""


def preflight(project_dir: Path | str | None = None) -> Report:
    """The report for a project. Nothing is evaluated until something is asked."""
    return Report(Path(project_dir) if project_dir else Path.cwd())
