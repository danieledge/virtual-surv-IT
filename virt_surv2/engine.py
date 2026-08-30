#!/usr/bin/env python3
"""Bridge between `install_helper.py`'s Installer and the Textual UI.

The engine is NOT reimplemented. Every Windows fix in it — `find_claude`,
`find_working_claude`, the PATH-shim fallback, `windows_shim_cmdline`,
`_windows_registry_path_dirs`, `register_plugin_directly`, the cp1252 handling — runs
exactly as it does today. This file only changes where its output goes and where its
questions are answered.

Three seams:

  OUTPUT   `Installer.observer` — `line` / `step` / `result`. Already in the engine
           (added 2026-08-29 for exactly this reason).

  INPUT    module-level `ask()` and `confirm()`. These call raw `input()` with no
           observer awareness, which is why a full-screen UI still drops out at all
           28 prompts. Patched here rather than in the repo, so this is provably a
           drop-in before anything upstream changes.

  STRAYS   two raw `print()` calls survive in the bashrc step (install_helper.py 3571
           and 3577), and a stray write tears a full-screen frame. stdout and stderr
           are captured for the duration rather than trusted.

The Installer is synchronous and blocking, so it runs on a worker thread and marshals
onto the UI thread with `App.call_from_thread`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional


# ── locating and loading the engine ───────────────────────────────────────────

class EngineNotFound(Exception):
    """No usable clone. Carries a message meant for a human, not a traceback."""


def find_repo(explicit: Optional[str] = None) -> Path:
    """The clone, in the order a user would expect it to be found."""
    tried: list[str] = []

    if explicit:
        p = Path(explicit).expanduser()
        try:
            p = p.resolve()
        except OSError as exc:
            raise EngineNotFound(f"--repo {explicit!r} is not a usable path ({exc})") from exc
        if (p / "install_helper.py").exists():
            return p
        raise EngineNotFound(f"no install_helper.py in {p}")

    try:
        here = Path.cwd()
    except OSError:                     # cwd deleted out from under us
        here = Path.home()
    for cand in (here, *here.parents):
        if (cand / "install_helper.py").exists():
            return cand
    tried.append(f"{here} and its parents")

    # The installer's own saved location — the same file `install`/`update` auto-detect
    # from, so a TUI launched from anywhere finds the clone the user already has.
    cfg = Path.home() / ".config" / "virt-surv-it" / "installer.json"
    try:
        saved = json.loads(cfg.read_text(encoding="utf-8")).get("repo")
        if saved and (Path(saved) / "install_helper.py").exists():
            return Path(saved)
        tried.append(str(cfg))
    except FileNotFoundError:
        tried.append(f"{cfg} (not present)")
    except (OSError, ValueError, AttributeError) as exc:
        tried.append(f"{cfg} (unreadable: {exc})")

    for guess in (Path.home() / "virtual-surv-IT", Path.home() / "virt-survtecb"):
        if (guess / "install_helper.py").exists():
            return guess
        tried.append(str(guess))

    raise EngineNotFound("could not find a virtual-surv-IT clone. Looked in:\n  - "
                         + "\n  - ".join(tried))


def load_engine(repo: Path):
    """Import install_helper with the repo's vendored deps on the path, the way the
    engine expects when it runs as `python install_helper.py`."""
    for p in (str(repo / "vendor"), str(repo)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import install_helper
    except Exception as exc:            # noqa: BLE001 — any import failure is fatal here
        raise EngineNotFound(
            f"install_helper.py in {repo} could not be imported:\n  "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    missing = [n for n in ("Installer", "Style", "marks", "ask", "confirm")
               if not hasattr(install_helper, n)]
    if missing:
        raise EngineNotFound(
            f"install_helper.py in {repo} is missing {', '.join(missing)} — "
            "this clone is too old or too new for this front end."
        )
    return install_helper


# ── answering the engine's questions ──────────────────────────────────────────

# Maps a prompt to a decision key. Matched on a lowercase substring because the engine
# builds several prompts with f-strings ("{detail}. Shall I discard them...").
#
# Anything NOT matched here is a conditional interrupt — a dirty clone, an unusable
# claude CLI, an existing status line. Those are exactly the questions that SHOULD
# still stop and ask, so they fall through to the modal. Never guess on those: two of
# them (stash, discard) can lose a user's uncommitted work.
ANSWER_MAP: list[tuple[str, str]] = [
    ("which channel", "channel"),
    ("where shall i keep", "clone"),
    ("optional dev requirements", "pip"),
    ("wire the status line", "statusline"),
    ("virt-surv' alias", "alias"),
    ("enable the team for a project", "project_enable"),
    ("which project directory", "project"),
    ("recommended defaults for all", "quick"),
    ("walk through this machine's default settings", "machine_defaults"),
]

# The review analysers the team's reviewers actually drive. They live in
# requirements-review.txt alongside the two tree-sitter packages, and the engine
# installs ONLY those two ("the analysers in it are a separate decision the user may
# already have taken") — so ruff/black/mypy/bandit/sqlfluff are never installed by any
# path, and the probe then reports them missing. This front end offers them.
ANALYSER_REQUIREMENTS = "requirements-review.txt"
CODE_INTEL_PREFIXES = ("tree-sitter", "tree-sitter-language-pack")


def analyser_specs(repo: Optional[Path]) -> list[str]:
    """Pinned specs from requirements-review.txt, minus the code-intelligence pair the
    engine's own step already handles. Pins are kept: installing bare names would
    bypass the version floors the file exists to hold."""
    if not repo:
        return []
    try:
        raw_lines = (Path(repo) / ANALYSER_REQUIREMENTS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    specs = []
    for raw in raw_lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = line.split(">")[0].split("<")[0].split("=")[0].strip()
        if name not in CODE_INTEL_PREFIXES:
            specs.append(line)
    return specs


class Answers:
    """Resolves an engine prompt to a decided answer, or escalates to the UI."""

    def __init__(self, choices: dict, escalate: Callable[[str, str, Any], Any]) -> None:
        self.choices = dict(choices)
        # NOT True. `quick_defaults` makes optional_pip take a `wanted = True` branch
        # that never reaches its confirm(), so answering "yes" here silently overrode
        # the Document-output toggle and installed regardless. Answering "no" makes the
        # engine ask each question individually — which is exactly what the decide
        # screen has already answered.
        self.choices["quick"] = False
        # Machine-wide defaults are configuration, not installation; they belong on the
        # settings screen, so this offer is declined rather than escalated.
        self.choices["machine_defaults"] = False
        self.choices["project_enable"] = bool(choices.get("project"))
        self.escalate = escalate
        self.asked: list[tuple[str, Any, str]] = []        # (prompt, answer, source)

    def _lookup(self, prompt: str):
        low = (prompt or "").lower()
        for needle, key in ANSWER_MAP:
            if needle in low and key in self.choices:
                return True, self.choices[key]
        return False, None

    def ask(self, prompt: str, default: str, assume_yes: bool = False, style=None) -> str:
        try:
            hit, value = self._lookup(prompt)
            _trace("ask", "decided" if hit else "escalate", prompt)
            if hit:
                self.asked.append((prompt, value, "decided"))
                return str(value) if value not in (None, "") else default
            value = self.escalate("ask", prompt, default)
            self.asked.append((prompt, value, "prompted"))
            return default if value is None else str(value)
        except Exception:               # noqa: BLE001 — a prompt must never kill a run
            return default

    def confirm(self, prompt: str, default: bool, assume_yes: bool = False, style=None) -> bool:
        try:
            hit, value = self._lookup(prompt)
            _trace("confirm", "decided" if hit else "escalate", prompt)
            if hit:
                self.asked.append((prompt, bool(value), "decided"))
                return bool(value)
            value = self.escalate("confirm", prompt, default)
            self.asked.append((prompt, value, "prompted"))
            return bool(default if value is None else value)
        except Exception:               # noqa: BLE001
            return default


# ── the observer the engine already speaks ────────────────────────────────────

class UiObserver:
    """The three calls `Installer` makes. Every one arrives on the ENGINE thread and
    is marshalled onto the UI thread; a direct widget write from here is a race.

    Every call is guarded: once the app is shutting down `call_from_thread` raises,
    and an observer that propagates that turns a clean quit into a traceback.
    """

    def __init__(self, app, screen) -> None:
        self.app, self.screen = app, screen

    def _post(self, fn, *args) -> None:
        try:
            self.app.call_from_thread(fn, *args)
        except Exception:               # noqa: BLE001 — app gone, or loop closed
            pass

    def line(self, text: str) -> None:
        self._post(self.screen.engine_line, text)

    def step(self, number: int, total: int, title: str) -> None:
        self._post(self.screen.engine_step, number, total, title)

    def result(self, name: str, status: str, detail: str = "") -> None:
        self._post(self.screen.engine_result, name, status, detail)


class _DemoRunner:
    """Install the engine's own dry-run stand-in for the length of a run.

    --demo promises "executes nothing, writes nothing", and v1 delivers that by
    swapping the MODULE-GLOBAL run_cmd for make_demo_runner. Setting args.demo alone
    does not: several steps have no self.demo branch precisely because the swap is
    assumed - dashboard_step says so in its own docstring - so v2's --demo was running
    npm install, git fetch, claude plugin install/uninstall and pip install for real.
    """

    def __init__(self, ih, demo: bool) -> None:
        self.ih, self.demo, self.saved = ih, demo, None

    def __enter__(self):
        # Best-effort: a clone without make_demo_runner is older than this feature, and
        # failing the whole run over a dry-run helper would be a worse outcome than
        # running it wet - which is why the caller also still sets args.demo.
        if not self.demo:
            return self
        maker = getattr(self.ih, "make_demo_runner", None)
        if maker is None:
            return self
        try:
            self.saved = self.ih.run_cmd
            self.ih.run_cmd = maker(self.ih.Style(False))
        except Exception:               # noqa: BLE001
            self.saved = None
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            self.ih.run_cmd = self.saved
        return False


class _Capture:
    """Line-buffered stand-in for stdout/stderr while the engine runs.

    install_helper still has two raw `print()` calls (3571, 3577) and any future one
    would tear the frame silently. Nothing reaches the real terminal during the run.
    """

    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit, self.buf = emit, ""

    def write(self, s: str) -> int:
        try:
            self.buf += s
            while "\n" in self.buf:
                line, _, self.buf = self.buf.partition("\n")
                if line.strip():
                    self.emit(line)
        except Exception:               # noqa: BLE001
            pass
        return len(s)

    def flush(self) -> None:
        if self.buf.strip():
            try:
                self.emit(self.buf)
            except Exception:           # noqa: BLE001
                pass
        self.buf = ""

    def isatty(self) -> bool:
        return False

    def fileno(self):
        raise OSError("captured stream has no fileno")


def _trace(event: str, *parts) -> None:
    """Append a line to $VS_TUI_TRACE, if set. A full-screen UI redraws over its own
    history, so the only way to see what the engine actually asked — and how often —
    is to write it down somewhere else."""
    path = os.environ.get("VS_TUI_TRACE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{event}\t" + "\t".join(str(p).replace(chr(10), " ")[:160]
                                                for p in parts) + "\n")
    except OSError:
        pass


class PromptBroker:
    """Blocking round-trips from the engine thread to a modal.

    Tracks every waiter so `release_all()` can unblock them on shutdown. Without that,
    quitting while a question is on screen leaves the engine thread parked on an Event
    that will never be set, and the app cannot exit.
    """

    def __init__(self, app, screen) -> None:
        self.app, self.screen = app, screen
        self._pending: set[threading.Event] = set()
        self._lock = threading.Lock()
        self._closed = False

    def escalate(self, kind: str, prompt: str, default):
        _trace("escalate", kind, prompt, default)
        if self._closed:
            return default
        box: dict = {}
        done = threading.Event()
        with self._lock:
            self._pending.add(done)
        try:
            try:
                self.app.call_from_thread(self.screen.open_prompt, kind, prompt, default, box, done)
            except Exception:           # noqa: BLE001 — no UI to ask; take the default
                return default
            done.wait()
            answer = box.get("value", default)
            _trace("answered", kind, answer)
            return answer
        finally:
            with self._lock:
                self._pending.discard(done)

    def release_all(self) -> None:
        """Unblock every waiter. Called on shutdown; safe to call more than once."""
        self._closed = True
        with self._lock:
            pending, self._pending = list(self._pending), set()
        for ev in pending:
            ev.set()


# The launcher's stdout contract, reused verbatim: stdout carries the decision the
# shell wrapper hands to Claude Code, and exit 97 means "the human backed out, launch
# nothing". Both are shared with `virt-surv go`, so one wrapper shape serves both.
ABORT_EXIT_CODE = 97


def engage_command(repo: Optional[Path], project: Path) -> str:
    """The engage command spelling THIS project answers to.

    Namespaced under a plugin install, bare in repo-as-project mode - which is exactly
    why it is resolved rather than hardcoded.
    """
    if repo is None:
        return "/compliance-surveillance-team:engage"
    scripts = Path(repo) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import virt_team_launcher as launcher
        return launcher._engage_command(Path(project))
    except Exception:                   # noqa: BLE001
        return "/compliance-surveillance-team:engage"


def resume_token(repo: Optional[Path], row: dict) -> str:
    """The identifier a --resume decision carries for this row - the launcher's own
    _row_resume_token, which prefers the workspace dir and has a documented exception
    for flat-layout packs that once emitted a literal `--resume (flat)`."""
    if repo is None:
        return ""
    scripts = Path(repo) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import virt_team_launcher as launcher
        return launcher._row_resume_token(row.get("row") or row) or ""
    except Exception:                   # noqa: BLE001
        return ""


# What `virt-surv go` does BEFORE it shows you anything. None of it was happening in
# v2, so the probe and tool caches started cold every time (Morgan then reads a cache
# that was never written), a previous go's request handoff was carried forward, the
# project never reached the explorer's recent list, and the guard interpreter was
# resolved lazily mid-session instead of warmed here.
#
# Order and names are v1's (virt_team_launcher.main, 4313-4379). Each is best-effort:
# v1's own comment is that a failure here must cost only the cache refresh, never the
# resume decision.
PRELAUNCH_STEPS = (
    ("_check_plugin_cache_lag", "checking the plugin cache"),
    ("_expire_stale_auto_consent", "expiring stale auto-consent"),
    ("_apply_new_recommended_defaults", "applying new recommended defaults"),
    ("_remember_project", "remembering this project"),
    ("_prewarm_guard_interpreter", "warming the guard interpreter"),
    ("_clear_request_handoff", "clearing any stale request"),
    ("_write_probe_cache", "pre-computing the engagement probe"),
    ("_refresh_tool_cache", "checking installed tools"),
)


def run_prelaunch(repo: Optional[Path], project: Path, report=None) -> list:
    """Run go's pre-flight. Returns [(label, ok, detail)] for anything worth showing."""
    out: list = []
    try:
        launcher = _launcher(repo)
    except Exception as exc:            # noqa: BLE001
        return [("pre-flight", False, str(exc))]
    for name, label in PRELAUNCH_STEPS:
        fn = getattr(launcher, name, None)
        if fn is None:
            continue                    # older clone: not a failure
        try:
            if report:
                report(label)
            fn(Path(project))
            out.append((label, True, ""))
        except Exception as exc:        # noqa: BLE001 — never block the launcher
            out.append((label, False, f"{type(exc).__name__}: {exc}"))
    return out


def new_decision(repo: Optional[Path], project: Path, request: str = "",
                 auto: bool = False) -> str:
    """The opening command for NEW work, with an optional pre-seeded request.

    Built by the launcher's own _new_command, never here: the request travels in a
    FILE rather than inside the command string, because PowerShell 5.1 hands embedded
    double quotes to a native .exe unescaped and claude.exe then re-splits the line and
    keeps the first token. Two users hit that on the same day. An empty request gives
    exactly the plain --new.
    """
    try:
        return _launcher(repo)._new_command(Path(project), request, auto)
    except Exception:                   # noqa: BLE001
        return f"{engage_command(repo, project)} --new"


def archive_engagements(repo: Optional[Path], project: Path, views: list) -> str:
    """Archive the packs you PICKED, through the launcher's own _archive_perform.

    v2 called run_archive_engagements, which archives every closed pack with no
    selection at all - a different operation under the same key. Archiving in place
    deletes nothing; an OPEN pack archives with --force and then shows as ARCHIVED-OPEN
    in checks, which is why v1 states that before you press the key rather than after.
    """
    if not views:
        return "nothing selected"
    launcher = _launcher(repo)
    import engagement_state

    rows = [v.get("row") for v in views if v.get("row")]
    if not rows:
        return "could not identify those engagements"
    perform = getattr(launcher, "_archive_perform", None)
    if perform is None:
        return "this clone has no _archive_perform"
    perform(engagement_state, rows)
    return f"archived {len(rows)}"


def guard_running_inside_target(ih, repo: Optional[Path]) -> str:
    """v1's Windows guard, run before the engine touches the clone.

    _relocate_if_running_inside_target_repo exists because on Windows `git checkout`
    cannot overwrite a running install_helper.py. v2 is MORE exposed than v1, not less:
    it imports the module from the clone and then runs the sync in that same process.
    """
    fn = getattr(ih, "_relocate_if_running_inside_target_repo", None)
    if fn is None or repo is None:
        return ""
    try:
        fn(Path(repo))
        return ""
    except SystemExit:
        raise
    except Exception as exc:            # noqa: BLE001 — advisory, never fatal
        return f"{type(exc).__name__}: {exc}"


def update_available(ih, cfg_args) -> str:
    """Whether a newer version is on the channel this machine tracks.

    v1 shows this right after the banner and before the menu, "so 'there's an update'
    is visible no matter which option you pick". v2's menu never mentioned one.
    """
    checker = getattr(ih, "check_for_update_upfront", None)
    if checker is None:
        return ""
    import io as _io

    buf = _io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    try:
        checker(ih.load_config(ih.config_path()), ih.Style(False), cfg_args)
    except Exception:                   # noqa: BLE001 — never block the menu
        return ""
    finally:
        sys.stdout = saved
    return buf.getvalue().strip()


def warn_if_abort_ignored(repo: Optional[Path]) -> None:
    """A pre-v7 wrapper ignores exit 97, so Esc would open an unexplained session."""
    try:
        _launcher(repo)._warn_if_abort_will_be_ignored()
    except Exception:                   # noqa: BLE001
        pass


def recent_projects(repo: Optional[Path]) -> list:
    """Folders the launcher has seen, newest first - what v1's explorer offers."""
    try:
        return [p for p in (_launcher(repo)._recent_projects() or []) if p]
    except Exception:                   # noqa: BLE001
        return []


def jira_needs_key(repo: Optional[Path], project: Path) -> bool:
    try:
        return bool(_launcher(repo)._jira_needs_key(Path(project)))
    except Exception:                   # noqa: BLE001
        return False


def set_jira_key(repo: Optional[Path], project: Path, key: str) -> str:
    """Jira write-back is unusable in the "on (key UNSET)" state, and v2 had no way to
    leave it - it could only start work FROM a ticket, never name the project key."""
    try:
        return _launcher(repo).set_jira_project_key(Path(project), key) or ""
    except Exception as exc:            # noqa: BLE001
        return f"could not set the project key: {exc}"


def dispatch_decision(repo: Optional[Path], project: Path, decision: str,
                      report=None) -> bool:
    """v1's post-decision dispatch: headless, or a new window, or neither.

    Returns True when the session has ALREADY been started here - the caller must then
    exit 97 so the shell wrapper launches nothing, exactly as v1 does. False means "hand
    it to the wrapper as usual".

    Without this the `new_window` project preference was silently ignored - honoured by
    virt-surv, dropped by virt-surv2 - and an unattended run had nowhere to go. v1's own
    comment on this block: "a control that quietly does nothing is the defect class this
    repo has met five times in a week; the fix each time is to make it speak." So every
    reason NOT to open a window is reported.
    """
    try:
        launcher = _launcher(repo)
    except Exception:                   # noqa: BLE001
        return False

    def say(msg: str) -> None:
        if report:
            report(msg)

    try:
        pending = launcher._pending_auto(Path(project)) or {}
    except Exception:                   # noqa: BLE001
        pending = {}
    unattended = bool(pending.get("auto")) and "--auto" in (decision or "").split()

    try:
        if pending.get("run_mode") == "headless" and decision:
            # Started HERE, not handed to the shell: a headless run has no terminal for
            # the shell to launch into, and the launcher is what will watch it.
            if launcher._start_headless(Path(project), decision, pending):
                say("started headless - watch it from the launcher")
                return True
    except Exception as exc:            # noqa: BLE001
        say(f"could not start headless: {exc}")

    try:
        wants_window = bool(launcher._new_window_wanted(Path(project)))
    except Exception:                   # noqa: BLE001
        wants_window = False

    if not wants_window:
        say("new window off - opening here ([c] -> open the session in a new window)")
        return False

    try:
        if launcher._launch_in_window(Path(project), decision, pending.get("slug", "")):
            say("opened in a new window")
            return True
    except Exception as exc:            # noqa: BLE001
        say(f"could not open a window: {exc}")

    if unattended and decision:
        # No window and the run is UNATTENDED. Falling back in place would hand the
        # terminal to Claude Code and take the launcher - and the monitor - with it,
        # leaving a run nobody can watch or stop. Headless keeps the launcher, and an
        # unattended run answers no questions anyway.
        say("no window available - running headless instead so you can still watch it")
        try:
            if launcher._start_headless(Path(project), decision, pending):
                return True
        except Exception as exc:        # noqa: BLE001
            say(f"could not start headless: {exc}")
    return False


def finished_engagements(repo: Optional[Path], project: Path):
    """DONE and ARCHIVED packs - the ones the resume menu never shows.

    Returns (views, note). Each view carries the row_view display fields plus `signed`
    (who signed it off, or "") and `token`. Sign-off is read fresh rather than cached
    because pressing [s] must change what the screen says.
    """
    if repo is None:
        return [], "no clone found"
    try:
        launcher = _launcher(repo)
        import engagement_state
        root = launcher._vsit_paths().engagements_dir(Path(project))
        rows = engagement_state.finished_engagements(root)
    except Exception as exc:            # noqa: BLE001
        return [], f"could not read finished engagements: {exc}"
    if not rows:
        return [], "nothing done or archived in this folder yet"
    out = []
    for r in rows:
        try:
            view = launcher.row_view(r)
        except Exception:               # noqa: BLE001
            view = {"title": r.get("slug") or "?", "lines": []}
        token = ""
        try:
            token = launcher._row_resume_token(r) or ""
        except Exception:               # noqa: BLE001
            pass
        view["token"] = token
        view["archived"] = bool(r.get("archived"))
        view["signed"] = _sign_off_state(launcher, Path(project), token)
        out.append(view)
    return out, ""


def _sign_off_state(launcher, project: Path, token: str) -> str:
    if not token:
        return ""
    try:
        return launcher._sign_off_state(Path(project), token) or ""
    except Exception:                   # noqa: BLE001
        return ""


def sign_off(repo: Optional[Path], project: Path, token: str) -> str:
    """Record a HUMAN sign-off. The control exists so an agent cannot sign its own
    work, which is why it is a deliberate keypress and not a side effect of closing."""
    launcher = _launcher(repo)
    return launcher._record_sign_off(Path(project), token) or ""


def review_decision(repo: Optional[Path], project: Path, token: str) -> str:
    return f"{engage_command(repo, project)} --review {token}"


def supersede_decision(repo: Optional[Path], project: Path, token: str) -> str:
    """New work that REPLACES a finished pack. The link lives on the new engagement,
    so the closed record stays exactly as closed."""
    try:
        return _launcher(repo)._supersede_command(Path(project), token)
    except Exception:                   # noqa: BLE001
        return f"{engage_command(repo, project)} --new --supersedes {token}"


def settings_rows(repo: Optional[Path], project: Path):
    """The project's REAL settings, grouped, from the launcher's own editor.

    Returns (groups, note) where groups is [(title, [row, ...])] and a row carries
    key/label/value/on/help. Values come from _editor_layout, so they are what this
    project is actually configured to do - including the "(machine default)" and
    "(default)" provenance v1 appends, which is the difference between inherited and
    explicitly set.

    The previous version rendered a GENERATED constant: fixed labels, guessed defaults,
    no project involved. It showed values it had never read.
    """
    if repo is None:
        return [], "no clone found, so this project's settings cannot be read"
    try:
        launcher = _launcher(repo)
        layout = launcher._editor_layout(Path(project))
    except Exception as exc:            # noqa: BLE001
        return [], f"could not read this project's settings: {exc}"
    if layout is None:
        return [], "could not read this project's settings"

    keys = {}
    for label, key in launcher._TOGGLE_PREFS:
        keys[label] = key
    keys[launcher._ENV_ROW_LABEL] = launcher._ENV_KEY
    keys[launcher._JIRA_ROW_LABEL] = launcher._JIRA_KEY
    for label, key, _values, _default in launcher._CHOICE_PREFS:
        keys[label] = key

    groups: list = []
    for title, label, value, on in layout:
        if title or not groups:
            groups.append((title or "Other", []))
        help_text = ()
        try:
            help_text = launcher.setting_help(label) or ()
        except Exception:               # noqa: BLE001
            pass
        groups[-1][1].append({
            "key": keys.get(label, label),
            "label": label,
            "value": value,
            "on": bool(on),
            "what": help_text[0] if help_text else "",
            "off": help_text[1] if len(help_text) > 1 else "",
        })
    return groups, ""


def settings_apply(repo: Optional[Path], project: Path, row_key: str) -> str:
    """Apply ONE setting and return the launcher's own note. This is the write."""
    launcher = _launcher(repo)
    return launcher._editor_apply_key(Path(project), row_key) or ""


def settings_restore_defaults(repo: Optional[Path], project: Path) -> str:
    """'d' - DELETE the project-level keys so the machine tier applies again.

    Not "set every value back to a snapshot": key presence is what resolve_preferences
    reads, so deleting and re-writing the same value are different states.
    """
    launcher = _launcher(repo)
    return launcher._editor_apply(Path(project), "d") or ""


def project_is_configured(repo: Optional[Path], project: Path) -> Optional[bool]:
    """Is the team enabled for this folder? None when the question cannot be answered.

    Same check `virt-surv go` makes before offering first-time setup - the launcher's
    own _plugin_enabled - so the two cannot disagree about what "set up" means.
    """
    if repo is None:
        return None
    scripts = Path(repo) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import virt_team_launcher as launcher
        return bool(launcher._plugin_enabled(Path(project)))
    except Exception:                   # noqa: BLE001 — unknown, not "not set up"
        return None


def load_engagements(repo: Optional[Path], project: Path):
    """Real engagement rows for ONE project, or a reason there are none.

    Returns (rows, note). rows are row_view() dicts - the launcher's own single source
    of an engagement row's display content, so this cannot render them differently from
    `virt-surv go`. note is a human sentence when the list is empty or unreadable, which
    is the case the mock never had: an empty list and "could not read them" look
    identical on screen unless one of them says so.
    """
    if repo is None:
        return [], "no clone found, so no engagement state to read"
    scripts = Path(repo) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import engagement_state
        import virt_team_launcher as launcher
    except Exception as exc:            # noqa: BLE001
        return [], f"could not load the engagement reader: {exc}"
    try:
        # The ENGAGEMENTS dir, not the project root: resume_menu does a one-level scan
        # of whatever it is given, so passing the root found nothing, always. The
        # launcher resolves it through vsit_paths for the same reason - the VSIT
        # migration moved where packs live.
        root = launcher._vsit_paths().engagements_dir(Path(project))
        menu = engagement_state.resume_menu(root, max_shown=_FULL_MENU)
    except Exception as exc:            # noqa: BLE001 — an unreadable project is normal
        return [], f"could not read engagements in this folder: {exc}"
    rows = menu.get("open") or []
    if not rows:
        archived = menu.get("archived") or 0
        return [], (f"no open engagements here ({archived} archived)" if archived
                    else "no open engagements in this folder")
    default = menu.get("default") or ""
    try:
        views = []
        for r in rows:
            v = launcher.row_view(r, default_slug=default, of_many=len(rows) > 1)
            v["row"] = r        # the raw row, so a --resume token can be derived later
            views.append(v)
        return views, ""
    except Exception as exc:            # noqa: BLE001
        return [], f"could not render engagements: {exc}"


_FULL_MENU = 9999   # the launcher's own "no cap" value for resume_menu


# ── running it ────────────────────────────────────────────────────────────────

def build_args(choices: dict, repo: Optional[Path], demo: bool) -> SimpleNamespace:
    """The six attributes `Installer` reads off its args, plus `demo`.

    `yes` stays False on purpose: --yes makes the engine take its unattended path, and
    we want the ordinary interactive path with its prompts answered from the decide
    screen — same code, same order, no questions.
    """
    return SimpleNamespace(
        branch=choices.get("channel", "dev"),
        mode=None,
        pip=bool(choices.get("pip", False)),
        # The DECISION wins, not the discovery: the decide screen is seeded with the
        # discovered clone, so if the value differs the user changed it on purpose and
        # the engine should honour it (that row is the engine's own "Where shall I keep
        # your local clone?" question).
        repo=(choices.get("clone") or (str(repo) if repo else None)),
        statusline=bool(choices.get("statusline", True)),
        yes=False,
        demo=demo,
    )


def _install_analysers(ih, observer, repo: Optional[Path], demo: bool, installer=None) -> int:
    """ruff/black/mypy/bandit/sqlfluff. Never fatal: like the engine's own optional
    pip steps, a locked-down box with no pip must not fail an otherwise-good install."""
    import sys as _sys

    specs = analyser_specs(repo)
    total = getattr(observer.screen, "total", 0) or 0
    observer.step(total + 1, total + 1, "Review analysers")
    if not specs:
        observer.result("Review analysers", "skip",
                        f"no {ANALYSER_REQUIREMENTS} in the clone")
        return 0
    if demo:
        observer.result("Review analysers", "skip",
                        "dry run - would install " + ", ".join(specs))
        return 0
    observer.line("pip install " + " ".join(specs))
    try:
        proc = ih.run_cmd([_sys.executable, "-m", "pip", "install", *specs], timeout=900)
        rc = proc.returncode
    except Exception as exc:            # noqa: BLE001 — pip absent, blocked, anything
        observer.result("Review analysers", "skip", f"could not run pip: {exc}")
        return 0
    if rc == 0:
        observer.result("Review analysers", "ok", ", ".join(s.split(">")[0] for s in specs))
        # The probe caches tool availability on a 7-day TTL and Morgan reads it at
        # engagement open. Installing analysers and leaving that cache alone means the
        # team keeps reporting them missing for up to a week AFTER they were installed -
        # "the user did exactly what they were told and nothing changed", which is what
        # run_tool_reprobe exists to rescue. The engine's code-intel step invalidates it
        # for its own install; this does the same for these.
        drop = getattr(installer, "_invalidate_tool_cache", None)
        if drop is not None:
            try:
                drop()
                observer.result("Tool cache", "ok", "cleared - the team will re-probe")
            except Exception as exc:    # noqa: BLE001 — best-effort, never fatal
                observer.result("Tool cache", "skip", f"not cleared: {exc}")
    else:
        observer.result("Review analysers", "skip",
                        "pip install failed - reviews fall back to their built-in checks")
    return 0


# Advanced/diagnostics actions that are NOT an Installer subset: main() reaches these
# through a run_* function, so this does the same rather than reimplementing them.
RUN_FUNCTIONS = {
    # `configure` is a free function in main(), not an Installer subset - it needs no
    # clone-management state. It asks for the directory itself, which our patched ask()
    # escalates to the modal, so the user still names the project.
    "configure":    lambda ih, st, mk, repo, project=None, demo=False: ih.run_configure(
        Path(project or ih.ask("  Which project directory?", ".", False, style=st) or "."),
        st, mk, False, demo),
    # `onboard` is configure with every default applied and zero prompts - the same
    # thing v1's first-time-setup screen runs for its "use the defaults" answer.
    "onboard":      lambda ih, st, mk, repo, project=None, demo=False: ih.run_configure(
        Path(project or "."), st, mk, True, demo),
    "howto":        lambda ih, st, mk, repo, project=None, demo=False: ih.run_howto(st),
    "aliasmanage":  lambda ih, st, mk, repo, project=None, demo=False: ih.run_alias_manage(
        st, mk, False, demo, repo),
    "gitbashperf":  lambda ih, st, mk, repo, project=None, demo=False: ih.run_gitbash_perf(
        st, mk, False, demo),
    "extensions":   lambda ih, st, mk, repo, project=None, demo=False: ih.run_extensions_editor(
        st, mk),
    "reprobe":      lambda ih, st, mk, repo, project=None, demo=False: ih.run_tool_reprobe(st, mk),
    "archive":      lambda ih, st, mk, repo, project=None, demo=False: ih.run_archive_engagements(
        Path(project or "."), st, mk, demo),
    "finished":     lambda ih, st, mk, repo, project=None, demo=False: ih.run_list_engagements(
        Path(project or "."), st, mk),
    # watch and artifacts have plain, text-only fallbacks in the launcher precisely
    # because their full-screen versions cannot always run. Those are what this calls:
    # their output lands in the capture and renders as run output, rather than a second
    # prompt_toolkit app fighting this one for the terminal.
    "watch":        lambda ih, st, mk, repo, project=None, demo=False: _launcher_call(
        repo, "_watch_running_engagement", Path(project or ".")),
    "artifacts":    lambda ih, st, mk, repo, project=None, demo=False, slug="":
        _launcher_artifacts(repo, Path(project or "."), slug),
    "relocate":     lambda ih, st, mk, repo, project=None, demo=False: ih.run_relocate_to_vsit(st, mk),
}


def _launcher(repo: Optional[Path]):
    if repo is None:
        raise RuntimeError("no clone found")
    scripts = Path(repo) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import virt_team_launcher
    return virt_team_launcher


def _launcher_call(repo, name: str, *args) -> int:
    fn = getattr(_launcher(repo), name, None)
    if fn is None:
        print(f"  {name} is not available in this clone")
        return 0
    fn(*args)
    return 0


def _launcher_artifacts(repo, project: Path, slug: str = "") -> int:
    """The artifacts view for a NAMED engagement, or the most recent if none given.

    v1 asks which one when several are open; v2 hardcoded rows[0], so with three open
    packs it always showed the same one regardless of what you had highlighted.
    """
    launcher = _launcher(repo)
    if not slug:
        rows, _note = load_engagements(repo, project)
        if not rows:
            print("  no open engagements in this folder")
            return 0
        slug = resume_token(repo, rows[0])
    if not slug:
        print("  could not identify an engagement to show artifacts for")
        return 0
    plain = getattr(launcher, "_artifacts_plain", None)
    if plain is None:
        print("  the artifacts view is not available in this clone")
        return 0
    plain(project, slug)
    return 0


def jira_decision(repo: Optional[Path], project: Path, ref: str) -> str:
    """The decision `virt-surv go` emits for a Jira ticket, resolved by its own
    _jira_command so the spelling cannot drift."""
    try:
        launcher = _launcher(repo)
        return launcher._jira_command(Path(project), ref)
    except Exception:                   # noqa: BLE001
        return f"{engage_command(repo, project)} --new {ref}".strip()


def run_action(ih, app, screen, action: str, choices: dict, repo: Optional[Path],
               demo: bool, broker: "PromptBroker | None" = None,
               project: Optional[Path] = None, slug: str = "") -> int:
    """One advanced/diagnostics item. Blocking; call on a worker thread.

    Same guarantees as run_installer: engine_finished always lands, streams and the
    prompt helpers are always restored, and no exception escapes into the worker.
    """
    broker = broker or PromptBroker(app, screen)
    answers = Answers(choices, broker.escalate)
    observer = UiObserver(app, screen)

    orig_ask, orig_confirm = ih.ask, ih.confirm
    orig_out, orig_err = sys.stdout, sys.stderr
    code, failure = 1, None

    try:
        args = build_args(choices, repo, demo or action == "demo")
        ih.ask, ih.confirm = answers.ask, answers.confirm
        cap = _Capture(observer.line)
        sys.stdout = sys.stderr = cap
        try:
            dry = demo or action == "demo"
            with _DemoRunner(ih, dry):
                fn = RUN_FUNCTIONS.get(action)
                if fn is not None:
                    observer.step(1, 1, action)
                    # The real demo flag, not a hardcoded False: these five write to
                    # settings.json, ~/.bashrc, ~/.bash_profile and the archive.
                    kw = {"slug": slug} if "slug" in fn.__code__.co_varnames else {}
                    code = fn(ih, ih.Style(False), ih.marks(), args.repo,
                              str(project) if project else None, dry, **kw) or 0
                else:
                    subset = "full" if action == "demo" else action
                    inst = ih.Installer(args, ih.Style(False), ih.marks(), subset=subset)
                    inst.observer = observer
                    _disarm_self_reexec(inst, observer, screen)
                    code = inst.run()
        finally:
            cap.flush()
            sys.stdout, sys.stderr = orig_out, orig_err
            ih.ask, ih.confirm = orig_ask, orig_confirm
    except BaseException as exc:        # noqa: BLE001
        sys.stdout, sys.stderr = orig_out, orig_err
        ih.ask, ih.confirm = orig_ask, orig_confirm
        failure = f"{type(exc).__name__}: {exc}"
        screen.crash_detail = traceback.format_exc()
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        broker.release_all()
        try:
            app.call_from_thread(screen.engine_finished, code, answers.asked, failure)
        except Exception:               # noqa: BLE001
            pass
    return code


def _disarm_self_reexec(installer, observer, screen) -> None:
    """Stop the engine re-launching the CLASSIC installer underneath this UI.

    _reexec_if_self_updated exists because a sync that pulls a new install_helper.py
    leaves the rest of the run executing the OLD in-memory logic. Its fix is to
    subprocess the fresh script and sys.exit() - correct for a terminal program, wrong
    here: the child would write into our stdout capture and be invisible, and the
    sys.exit lands in a worker thread, so a successful update would report as a failure.

    So it is replaced with a note. The run finishes on the code it started with -
    exactly what the engine does when the re-exec fails - and the finish screen says to
    run virt-surv2 again.
    """
    original = getattr(installer, "_reexec_if_self_updated", None)
    if original is None:
        return

    def _note_instead() -> None:
        try:
            fresh = (installer.repo / "install_helper.py") if installer.repo else None
            if not fresh or not fresh.is_file():
                return
            import pathlib as _pl
            running = _pl.Path(installer.__class__.__module__ and
                               sys.modules[installer.__class__.__module__].__file__).resolve()
            if running.read_bytes() == fresh.read_bytes():
                return
        except OSError:
            return
        screen.self_updated = True
        observer.line("the installer updated itself - run virt-surv2 again to use it")

    installer._reexec_if_self_updated = _note_instead


def run_installer(ih, app, screen, choices: dict, repo: Optional[Path],
                  demo: bool, subset: str = "full", broker: PromptBroker | None = None) -> int:
    """Blocking; call on a worker thread. Returns the engine's own exit code.

    Guarantees, in order of how badly their absence bites:
      * `engine_finished` is ALWAYS delivered, including on an unexpected exception —
        otherwise the UI sits on a spinner forever with no way to know it is dead.
      * `ask`/`confirm` and stdout/stderr are always restored, even on a crash.
      * No exception escapes into the worker, where it would be swallowed silently.
    """
    broker = broker or PromptBroker(app, screen)
    answers = Answers(choices, broker.escalate)
    observer = UiObserver(app, screen)

    orig_ask, orig_confirm = ih.ask, ih.confirm
    orig_out, orig_err = sys.stdout, sys.stderr
    code, failure = 1, None

    try:
        installer = ih.Installer(build_args(choices, repo, demo), ih.Style(False),
                                 ih.marks(), subset=subset)
        installer.observer = observer
        _disarm_self_reexec(installer, observer, screen)

        ih.ask, ih.confirm = answers.ask, answers.confirm
        cap = _Capture(observer.line)
        sys.stdout = sys.stderr = cap
        try:
            with _DemoRunner(ih, demo):
                code = installer.run()
        finally:
            cap.flush()
            sys.stdout, sys.stderr = orig_out, orig_err
            ih.ask, ih.confirm = orig_ask, orig_confirm

            # An extra step the engine has no equivalent for. Reported through the same
        # observer so it renders as step N+1 rather than as a surprise after the run.
            if code == 0 and choices.get("analysers"):
                code = _install_analysers(ih, observer, repo, demo, installer)

    except BaseException as exc:        # noqa: BLE001 — includes KeyboardInterrupt
        sys.stdout, sys.stderr = orig_out, orig_err
        ih.ask, ih.confirm = orig_ask, orig_confirm
        failure = f"{type(exc).__name__}: {exc}"
        screen.crash_detail = traceback.format_exc()
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        broker.release_all()
        try:
            app.call_from_thread(screen.engine_finished, code, answers.asked, failure)
        except Exception as exc:        # noqa: BLE001 — usually just "app already gone"
            # But not always: a bug in the finish handler raises here too, and
            # swallowing it silently makes a broken final screen look like a clean one
            # (live: _show_next_steps was called but never defined, and nothing said so).
            _trace("engine_finished failed", type(exc).__name__, exc)

    return code
