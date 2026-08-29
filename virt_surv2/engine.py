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
        menu = engagement_state.resume_menu(Path(project), max_shown=_FULL_MENU)
    except Exception as exc:            # noqa: BLE001 — an unreadable project is normal
        return [], f"could not read engagements in this folder: {exc}"
    rows = menu.get("open") or []
    if not rows:
        archived = menu.get("archived") or 0
        return [], (f"no open engagements here ({archived} archived)" if archived
                    else "no open engagements in this folder")
    default = menu.get("default") or ""
    try:
        return [launcher.row_view(r, default_slug=default, of_many=len(rows) > 1)
                for r in rows], ""
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
    "configure":    lambda ih, st, mk, repo: ih.run_configure(
        Path(ih.ask("  Which project directory?", ".", False, style=st) or "."),
        st, mk, False, False),
    "howto":        lambda ih, st, mk, repo: ih.run_howto(st),
    "aliasmanage":  lambda ih, st, mk, repo: ih.run_alias_manage(st, mk, False, False, repo),
    "gitbashperf":  lambda ih, st, mk, repo: ih.run_gitbash_perf(st, mk, False, False),
    "extensions":   lambda ih, st, mk, repo: ih.run_extensions_editor(st, mk),
    "reprobe":      lambda ih, st, mk, repo: ih.run_tool_reprobe(st, mk),
    "relocate":     lambda ih, st, mk, repo: ih.run_relocate_to_vsit(st, mk),
}


def run_action(ih, app, screen, action: str, choices: dict, repo: Optional[Path],
               demo: bool, broker: "PromptBroker | None" = None) -> int:
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
            fn = RUN_FUNCTIONS.get(action)
            if fn is not None:
                observer.step(1, 1, action)
                code = fn(ih, ih.Style(False), ih.marks(), args.repo) or 0
            else:
                subset = "full" if action == "demo" else action
                inst = ih.Installer(args, ih.Style(False), ih.marks(), subset=subset)
                inst.observer = observer
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
