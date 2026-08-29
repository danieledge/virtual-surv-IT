#!/usr/bin/env python3
"""Regression tests for the drop-in. Every case here is a bug that actually happened.

    .venv/bin/python tests/test_drop_in.py        (or ./run.sh --test)

Deliberately not pytest: this has to be runnable from the container, where only the
vendored/user-installed textual exists.

NOTE ON HARNESS CHOICE. Textual's `run_test()` deadlocks when a thread worker calls
`call_from_thread`, which is what the engine bridge does — so anything involving the
worker is tested under a real pty via tools/pty_probe.py, not here. What lives here is
everything that can be tested without the worker.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "vendor", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FAILED: list[str] = []

_FAKE_ENGINE = None


def fake_engine():
    """Load tests/fake_engine.py BY PATH.

    `from tests import fake_engine` looked right and was wrong: an unrelated `tests`
    package in site-packages shadows this directory under pytest, so the import
    resolved there and failed. A path load cannot be shadowed by a name.
    """
    global _FAKE_ENGINE
    if _FAKE_ENGINE is None:
        import importlib.util
        path = Path(__file__).resolve().parent / "fake_engine.py"
        spec = importlib.util.spec_from_file_location("vs2_fake_engine", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _FAKE_ENGINE = mod
    return _FAKE_ENGINE



UNDER_PYTEST = "pytest" in sys.modules


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {name:<52} got={got!r}")
    if not ok:
        FAILED.append(f"{name}: got {got!r}, want {want!r}")
        if UNDER_PYTEST:
            raise AssertionError(f"{name}: got {got!r}, want {want!r}")


# ── the bridge, with a stub app (no Textual threading) ────────────────────────

class StubScreen:
    def __init__(self, answer=None):
        self.events, self.finished, self.crash_detail = [], None, ""
        self.answer = answer

    def engine_line(self, t): self.events.append(("line", t))
    def engine_step(self, n, tot, ti): self.events.append(("step", n, tot, ti))
    def engine_result(self, n, s, d=""): self.events.append(("result", n, s, d))
    def engine_finished(self, c, a, f=None): self.finished = (c, len(a), f)

    def open_prompt(self, kind, prompt, default, box, done):
        if self.answer is not None:
            box["value"] = self.answer
            done.set()          # else: never answers, for the deadlock test


class StubApp:
    def call_from_thread(self, fn, *a):
        return fn(*a)


def test_bridge() -> None:
    from virt_surv2 import engine as E
    FE = fake_engine()

    choices = {"channel": "main", "pip": False, "statusline": True,
               "alias": True, "clone": "/tmp/x", "project": ""}

    for mode, want_code in (("normal", 0), ("escalate", 0), ("crash", 1), ("stray", 0)):
        FE.MODE = mode
        scr = StubScreen(answer=True)
        out_before, ask_before = sys.stdout, FE.ask
        code = E.run_installer(FE, StubApp(), scr, choices, None, True)
        check(f"{mode}: engine exit code", code, want_code)
        # The one that matters most: a crash must still deliver engine_finished, or the
        # UI sits on a spinner forever with no way to know the run is dead.
        check(f"{mode}: engine_finished delivered", scr.finished is not None, True)
        check(f"{mode}: stdout restored", sys.stdout is out_before, True)
        check(f"{mode}: ask restored", FE.ask is ask_before, True)

    FE.MODE = "crash"
    scr = StubScreen(answer=True)
    E.run_installer(FE, StubApp(), scr, choices, None, True)
    check("crash: failure message reported", "RuntimeError" in (scr.finished[2] or ""), True)

    # A stray print() must be captured, never written to the real terminal.
    FE.MODE = "stray"
    scr = StubScreen(answer=True)
    E.run_installer(FE, StubApp(), scr, choices, None, True)
    lines = [e[1] for e in scr.events if e[0] == "line"]
    check("stray print captured into the log", any("stray print" in x for x in lines), True)

    # Quitting with a modal open must not leave the engine thread parked forever.
    FE.MODE = "escalate"
    scr = StubScreen(answer=None)                  # never answers
    broker = E.PromptBroker(StubApp(), scr)
    threading.Timer(0.5, broker.release_all).start()
    code = E.run_installer(FE, StubApp(), scr, {"channel": "dev"}, None, True, broker=broker)
    check("release_all unblocks a parked engine thread", code, 0)

    # Destructive questions must never be auto-answered.
    a = E.Answers({"channel": "dev"}, lambda *_: "ESCALATED")
    for q in ("  Shall I stash them and carry on?",
              "  Local changes. Shall I discard them and match origin?",
              "  Full path to the claude CLI"):
        check(f"escalates: {q.strip()[:34]}", a.ask(q, "x"), "ESCALATED")
    check("answers from choices: channel", a.ask("  Which channel shall I track for you?", "x"),
          "dev")


# ── the modal's keys ──────────────────────────────────────────────────────────

def test_modal_keys() -> None:
    from textual.app import App

    from virt_surv2.live import PromptModal

    class T(App):
        def __init__(self, kind, default):
            super().__init__()
            self.kind, self.default = kind, default
            self.box, self.done = {}, threading.Event()

        def on_mount(self):
            self.push_screen(PromptModal(self.kind, "Shall I?", self.default,
                                         self.box, self.done, "ctx"))

    async def press(kind, default, keys):
        app = T(kind, default)
        async with app.run_test(size=(90, 30)) as p:
            await p.pause()
            for k in keys:
                await p.press(k)
            await p.pause()
            return app.done.is_set(), app.box.get("value", "<unset>")

    async def run():
        # y/n regressed twice: the hidden Input kept focus and ate printable keys, so
        # on_key was never reached and only Esc got through.
        for kind, default, keys, want in (
            ("confirm", True, ["y"], True),
            ("confirm", True, ["n"], False),
            ("confirm", True, ["escape"], True),
            ("confirm", False, ["escape"], False),
            ("confirm", True, ["enter"], True),
            ("ask", "claude", ["escape"], "claude"),
            ("ask", "claude", ["enter"], "claude"),
        ):
            answered, value = await press(kind, default, keys)
            check(f"modal {kind}/{'+'.join(keys)}", (answered, value), (True, want))

    asyncio.run(run())


def test_screen_keys() -> None:
    from virt_surv2 import ui as A

    async def run():
        # A Screen's binding action resolves against the SCREEN, so a bare "quit" found
        # nothing and neither q nor esc did anything on any screen.
        for start in ("decide", "install", "launch"):
            for key in ("q", "escape"):
                a = A.VirtSurvApp(start=start, frozen=True)
                async with a.run_test(size=(92, 30)) as p:
                    await p.pause()
                    await p.press(key)
                    await p.pause()
                    check(f"{start}: {key} quits", a._running, False)

        # The hidden edit box used to take focus and swallow left/right and q.
        a = A.VirtSurvApp(start="decide", frozen=True)
        async with a.run_test(size=(92, 30)) as p:
            await p.pause()
            await p.press("right")
            check("decide: right changes channel", a.screen.get("channel"), "main")
            # By key, not by position — adding a row must not break this test.
            scr = a.screen
            scr.cursor = next(i for i, d in enumerate(scr.decisions) if d.key == "intel")
            before = scr.get("intel")
            await p.press("space")
            check("decide: space toggles", scr.get("intel"), not before)
            scr.cursor = next(i for i, d in enumerate(scr.decisions) if d.key == "clone")
            await p.press("enter")
            check("decide: enter opens the edit box", a.screen.editing, True)
            await p.press("escape")
            check("decide: esc cancels the edit, does not quit",
                  (a.screen.editing, a._running), (False, True))

    asyncio.run(run())


def test_settings() -> None:
    from virt_surv2 import ui as A

    async def run():
        a = A.VirtSurvApp(start="settings", frozen=True)
        async with a.run_test(size=(104, 34)) as p:
            await p.pause()
            scr = a.screen
            check("settings rows from the generated data", len(scr.rows), 25)
            check("settings: groups", len(A.SETTING_GROUPS), 7)
            check("settings: every row has help text",
                  all(r["what"] for r in scr.rows), True)

            first = scr.rows[0]
            before = first["value"]
            await p.press("space")
            check("settings: space toggles", first["value"], not before)
            check("settings: change is tracked", first["label"] in scr.changed, True)
            await p.press("d")
            check("settings: d restores defaults", first["value"], before)
            check("settings: d clears the change list", scr.changed, [])

            # qa depth is the choice row; walk to it and cycle.
            qa = next(i for i, r in enumerate(scr.rows) if r["label"] == "qa depth")
            for _ in range(qa):
                await p.press("down")
            await p.press("right")
            check("settings: right cycles a choice", scr.rows[qa]["value"], "quick")

        # Esc from settings opened over the launcher returns, it does not quit.
        a = A.VirtSurvApp(start="launch", frozen=True)
        async with a.run_test(size=(104, 34)) as p:
            await p.pause()
            await p.press("c")
            await p.pause()
            check("launcher: c opens settings", type(a.screen).__name__, "SettingsScreen")
            await p.press("escape")
            await p.pause()
            check("settings: esc returns to the launcher",
                  (type(a.screen).__name__, a._running), ("LaunchScreen", True))

    asyncio.run(run())


def test_v1_registers_v2_alias() -> None:
    """`virt-surv`'s own alias step must stamp BOTH shortcuts.

    Both definitions carry the same version stamp, so _strip_stamped_definitions
    removes them together and heal_stale_aliases keeps them current - bumping
    _ALIAS_VERSION is what upgrades a machine that already has the old single alias.
    """
    import install_helper as ih

    repo = Path(ih.__file__).resolve().parent
    line = ih._alias_line_for(Path.home() / ".bashrc", "python3",
                              repo / "scripts" / "virt_team_launcher.py",
                              repo / "install_helper.py")
    lines = line.splitlines()
    check("alias step writes two definitions", len(lines), 2)
    check("both are stamped",
          all(ih._ALIAS_STAMP_ANY_RE.search(x) for x in lines), True)
    check("v2 function is named virt-surv2",
          any(x.lstrip().startswith(ih._ALIAS2_MARKER) for x in lines), True)

    # Strip must take both, or an upgrade leaves a dead definition behind - the exact
    # bug the stamp mechanism was added to fix.
    stripped, removed = ih._strip_stamped_definitions("# before\n" + line + "\n# after\n")
    check("strip removes both", len(removed), 2)
    check("no marker survives the strip", ih._ALIAS_MARKER in stripped, False)

    for marker in (ih._ALIAS_MARKER, ih._ALIAS2_MARKER):
        ok, note = ih._verify_alias_line("bash", Path.home() / ".bashrc", line, marker=marker)
        check(f"{marker} resolves in a shell", ok, True)

    # virt-surv2's function must carry the SAME go handshake, or the launcher can
    # emit a decision that nothing acts on - a launcher that does not launch.
    v2_line = next(x for x in lines if x.lstrip().startswith(ih._ALIAS2_MARKER))
    check("virt-surv2 handles go", '"$1" = "go"' in v2_line, True)
    check("virt-surv2 honours the abort code", "97" in v2_line, True)
    check("virt-surv2 passes the decision to the launch command",
          "__v2_d" in v2_line, True)
    check("virt-surv2 supports the cd handshake",
          "VIRT_SURV_CD_FILE" in v2_line, True)
    check("virt-surv2 resolves the launch command like v1 does",
          "--launch-command" in v2_line, True)

    # Two constants in two files have to agree or heal_stale_aliases never fires and
    # every existing machine silently keeps the old single-alias block forever.
    import re as _re
    launcher = (repo / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    expected = int(_re.search(r"_EXPECTED_ALIAS_VERSION = (\d+)", launcher).group(1))
    check("launcher's expected alias version matches install_helper's",
          expected, ih._ALIAS_VERSION)


def test_summary_names_virt_surv2() -> None:
    """The install must NAME the second shortcut and say a new shell is needed.

    Live report: the alias was written correctly, the closing text never mentioned it,
    and typing virt-surv2 in the shell that had just run the install said "command not
    found" - because no shell reloads its own profile mid-session.
    """
    import inspect

    import install_helper as ih

    src = inspect.getsource(ih.Installer.print_summary)
    check("summary names virt-surv2", "virt-surv2" in src, True)
    check("summary uses the shared reload hint", "alias_reload_hint" in src, True)

    # Both shells, or a Windows user gets an instruction that cannot work. One source,
    # so the summary and the alias step can never drift apart.
    hint = ih.alias_reload_hint(ih.Style(False))
    check("hint covers PowerShell", "$PROFILE" in hint, True)
    check("hint covers bash", "source ~/.bashrc" in hint, True)
    check("hint covers zsh", "zshrc" in hint, True)
    check("hint offers a new terminal", "new terminal" in hint, True)
    check("alias step uses the same source",
          "alias_reload_hint" in inspect.getsource(ih.run_setup_alias), True)


def test_finish_screen_renders() -> None:
    """The completion screen must actually paint.

    _show_next_steps was CALLED but never defined - a patch targeted an indented
    `def _wrap` that is module-level, so the edit silently did nothing. The resulting
    AttributeError was then swallowed by run_installer's finally, so a crashed final
    screen looked exactly like a clean finish that just had not repainted.
    """
    from virt_surv2.live import LiveInstallScreen

    check("_show_next_steps exists",
          callable(getattr(LiveInstallScreen, "_show_next_steps", None)), True)

    async def run():
        from textual.app import App

        class T(App):
            CSS_PATH = str(Path(__file__).resolve().parent.parent
                           / "virt_surv2" / "ui.tcss")

            def on_mount(self):
                self.scr = LiveInstallScreen({"channel": "dev"}, True)
                self.push_screen(self.scr)

        app = T()
        async with app.run_test(size=(92, 30)) as p:
            await p.pause()
            scr = app.scr
            scr.engine_step(1, 1, "Preflight checks")
            scr.engine_finished(0, [], None)      # must not raise
            await p.pause()
            body = scr.query_one("#steps")
            text = getattr(body, "content", None)
            text = text.plain if hasattr(text, "plain") else str(text)
            check("finish screen says installed", "installed" in text, True)
            check("finish screen tells you to open a new terminal",
                  "new terminal" in text, True)
            check("finish screen names virt-surv go", "virt-surv go" in text, True)
            check("panel title becomes done",
                  str(scr.query_one("#panel").border_title), "done")

    asyncio.run(run())


def test_css_paths() -> None:
    """Every App class must point at a stylesheet that exists.

    live.InstallerTuiApp kept CSS_PATH="app.tcss" after the file was renamed to
    ui.tcss; ui.VirtSurvApp was fixed, so every screen-only run passed and only the
    engine path crashed — on startup, with a traceback where the UI should be.
    """
    from virt_surv2 import ui as U
    from virt_surv2 import live as L

    pkg = Path(U.__file__).resolve().parent
    for app_cls in (U.VirtSurvApp, L.InstallerTuiApp):
        css = getattr(app_cls, "CSS_PATH", None)
        check(f"{app_cls.__name__}.CSS_PATH set", bool(css), True)
        check(f"{app_cls.__name__} -> {css} exists", (pkg / str(css)).is_file(), True)


def test_retry() -> None:
    """The failure footer offers 'r'; it must actually do something."""
    from virt_surv2 import ui as A
    from virt_surv2.live import LiveInstallScreen

    async def run():
        app = A.VirtSurvApp(start="decide", frozen=True)
        async with app.run_test(size=(96, 34)) as p:
            await p.pause()
            scr = LiveInstallScreen({"channel": "main"}, True)
            app.push_screen(scr)
            await p.pause()
            # Mid-run: r must be inert, or it would abandon a live worker.
            await p.press("r")
            await p.pause()
            check("r during a run is inert", type(app.screen).__name__, "LiveInstallScreen")
            scr.engine_finished(1, [], "boom")
            await p.pause()
            await p.press("r")
            await p.pause()
            check("r after a failure returns to decide",
                  type(app.screen).__name__, "DecideScreen")
            check("app still running after retry", app._running, True)

    asyncio.run(run())


def test_responsive() -> None:
    from virt_surv2 import ui as A

    async def run():
        for start in ("launch", "settings", "decide"):
            for width, want in ((100, False), (62, True)):
                a = A.VirtSurvApp(start=start, frozen=True)
                async with a.run_test(size=(width, 34)) as p:
                    await p.pause()
                    check(f"{start} @{width} cols: narrow={want}", a.screen.narrow, want)

    asyncio.run(run())


if __name__ == "__main__":
    print("\nbridge")
    test_bridge()
    print("\nmodal keys")
    test_modal_keys()
    print("\nscreen keys")
    test_screen_keys()
    print("\nsettings")
    test_settings()

    print("\nv1 registers v2")
    test_v1_registers_v2_alias()

    print("\nsummary")
    test_summary_names_virt_surv2()

    print("\nfinish screen")
    test_finish_screen_renders()

    print("\ncss paths")
    test_css_paths()

    print("\nretry")
    test_retry()

    print("\nresponsive")
    test_responsive()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED:")
        for f in FAILED:
            print("  - " + f)
        raise SystemExit(1)
    print("all passed")
