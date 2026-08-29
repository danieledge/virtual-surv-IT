#!/usr/bin/env python3
"""Exhaustive matrix: every option, every combination that can be tested in-process.

    .venv/bin/python tests/test_matrix.py        (or ./run.sh --matrix)

Covers
  A  build_args over all 32 boolean combinations, plus repo precedence
  B  every ANSWER_MAP entry, both values, plus the escalation set
  C  every decide row, every interaction it supports
  D  all 18 settings rows, toggled or cycled through every option
  E  every launcher row, and the detail pane for each
  F  key fuzz on every screen — no key may crash a screen
  G  responsive breakpoint on every screen, either side of the boundary
  H  every engine failure mode
  I  find_repo / load_engine error paths
  J  the modal, every kind × every key, including typed input

What is NOT here: a real install (10 minutes each, and it writes to a machine).
That is tools/pty_probe.py against the container — see README.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
import tempfile
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

COUNT = 0


UNDER_PYTEST = "pytest" in sys.modules


def check(name: str, got, want) -> None:
    global COUNT
    COUNT += 1
    if got != want:
        FAILED.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL  {name:<62} got={got!r} want={want!r}")
        if UNDER_PYTEST:
            raise AssertionError(f"{name}: got {got!r}, want {want!r}")


def section(title: str) -> None:
    print(f"\n{title}")


# ── A. build_args, all 32 boolean combinations ────────────────────────────────

def test_build_args() -> None:
    from virt_surv2 import engine as E
    section("A  build_args — 32 boolean combinations + repo precedence")
    n = 0
    for channel, pip, statusline, alias, intel, demo in itertools.product(
            ("dev", "main"), (True, False), (True, False), (True, False),
            (True, False), (True, False)):
        choices = {"channel": channel, "pip": pip, "statusline": statusline,
                   "alias": alias, "intel": intel, "clone": "/tmp/clone",
                   "project": "/tmp/proj"}
        a = E.build_args(choices, Path("/tmp/discovered"), demo)
        check(f"branch {channel}", a.branch, channel)
        check(f"pip {pip}", a.pip, pip)
        check(f"statusline {statusline}", a.statusline, statusline)
        check(f"demo {demo}", a.demo, demo)
        # --yes must stay False in every combination: it switches the engine to its
        # unattended path, which is NOT the path the decide screen answers.
        check("yes always False", a.yes, False)
        check("mode always None", a.mode, None)
        n += 1
    print(f"  {n} combinations checked")

    # The decision wins over discovery — the row is the engine's own "where shall I
    # keep your local clone?" question, so changing it must have an effect.
    a = E.build_args({"clone": "/tmp/chosen"}, Path("/tmp/discovered"), False)
    check("clone decision beats discovery", a.repo, "/tmp/chosen")
    a = E.build_args({}, Path("/tmp/discovered"), False)
    check("falls back to discovery", a.repo, "/tmp/discovered")
    a = E.build_args({}, None, False)
    check("no repo at all", a.repo, None)


# ── B. every ANSWER_MAP entry, both values ────────────────────────────────────

def test_answers_matrix() -> None:
    from virt_surv2 import engine as E
    section("B  Answers — every mapped prompt, both values, plus escalations")

    # A real prompt containing each needle, taken from install_helper's own wording.
    PROMPTS = {
        "channel": "  Which channel shall I track for you (main/dev)?",
        "clone": "  Where shall I keep your local clone?",
        "pip": "  Shall I install the optional dev requirements (pytest, render deps)?",
        "statusline": "  Shall I wire the status line - it shows the team's state?",
        "alias": "  Shall I also set up the 'virt-surv' alias?",
        "project_enable": "  Shall I enable the team for a project now (per-project scope)?",
        "project": "  Which project directory? (blank = cwd)",
        "quick": "  Go with the recommended defaults for all of these (fast, recommended)?",
        "machine_defaults":
            "  Shall I also walk through this machine's default settings now (citations)?",
    }
    for needle, key in E.ANSWER_MAP:
        prompt = PROMPTS[key]
        check(f"map covers {key}", needle in prompt.lower(), True)

    for key, prompt in PROMPTS.items():
        for value in (True, False):
            choices = {"channel": "main", "clone": "/c", "pip": value,
                       "statusline": value, "alias": value, "project": "/p" if value else ""}
            a = E.Answers(choices, lambda *_: "ESCALATED")
            got = a.confirm(prompt, not value)
            if key in ("pip", "statusline", "alias"):
                check(f"{key}={value} answered from choices", got, value)
            elif key == "project_enable":
                check(f"project_enable follows project={value}", got, value)
            elif key == "quick":
                check("quick declined so each toggle is asked", got, False)
            elif key == "machine_defaults":
                check("machine defaults declined", got, False)

    # Strings.
    a = E.Answers({"channel": "main", "clone": "/c", "project": "/p"}, lambda *_: "ESCALATED")
    check("channel string", a.ask(PROMPTS["channel"], "dev"), "main")
    check("clone string", a.ask(PROMPTS["clone"], "/x"), "/c")
    check("project string", a.ask(PROMPTS["project"], "/x"), "/p")

    # An empty decided value must fall back to the engine's own default, not "".
    a = E.Answers({"channel": "", "clone": ""}, lambda *_: "ESCALATED")
    check("empty decided value falls back to default", a.ask(PROMPTS["channel"], "dev"), "dev")

    # quick_defaults must be declined: answering it True makes optional_pip take a
    # branch that never reaches its confirm(), silently overriding the pip toggle.
    a = E.Answers({"pip": False}, lambda *_: "ESCALATED")
    check("quick defaults declined", a.confirm(PROMPTS["quick"], True), False)
    check("pip toggle now reachable", a.confirm(PROMPTS["pip"], True), False)
    a = E.Answers({}, lambda *_: "ESCALATED")
    check("machine defaults declined, not escalated",
          a.confirm("  Shall I also walk through this machine's default settings now?", True),
          False)

    # THE SAFETY SET. These can destroy uncommitted work or silently pick a wrong
    # binary; every one must reach a human.
    a = E.Answers({"channel": "dev"}, lambda *_: "ESCALATED")
    for prompt in (
        "  You have local changes. Shall I stash them and carry on?",
        "  3 commits ahead. Shall I discard them and match origin?",
        "  Shall I bring you up to date?",
        "  Full path to the claude CLI",
        "  Shall I replace it with the team's status line?",
        "  What command launches Claude Code on this machine?",
        "  Add it?",
        "  Produce .docx by default for controlled documents in this project?",
    ):
        check(f"escalates: {prompt.strip()[:40]}", a.ask(prompt, "x"), "ESCALATED")

    # A prompt helper that blows up must not take the run with it.
    def boom(*_a):
        raise RuntimeError("modal exploded")
    a = E.Answers({}, boom)
    check("escalate raising -> engine default (ask)", a.ask("  unmapped?", "fallback"), "fallback")
    check("escalate raising -> engine default (confirm)", a.confirm("  unmapped?", True), True)
    check("None prompt is survivable", a.confirm(None, False), False)


# ── C0. the view actually reflects the model ─────────────────────────────────

def test_render_reflects_model() -> None:
    """Toggling must change what is DRAWN, not just what is stored.

    This is the bug the whole matrix missed: compose() built rows from the module-level
    GROUPS while the toggles mutated per-instance copies, so every assertion on
    scr.decisions passed while the screen never moved. Assert pixels, not state.
    """
    from virt_surv2 import ui as A
    section("C0 rendered output follows the model")

    def text_of(widget) -> str:
        # Textual 8.x exposes a Static's current renderable as .content.
        r = getattr(widget, "content", None)
        if r is None:
            r = getattr(widget, "renderable", "")
        return r.plain if hasattr(r, "plain") else str(r)

    async def run():
        a = A.VirtSurvApp(start="decide", frozen=True)
        async with a.run_test(size=(100, 34)) as p:
            await p.pause()
            scr = a.screen
            for i, d in enumerate(scr.decisions):
                w = scr.query_one(f"#row-{d.key}", A.Row)
                check(f"decide {d.key}: row renders the live object", w.d is d, True)
                if d.kind != "toggle":
                    continue
                scr.cursor = i
                before = text_of(w)
                await p.press("space")
                after = text_of(w)
                check(f"decide {d.key}: drawn state changes", before != after, True)
                check(f"decide {d.key}: box reflects value",
                      ("✓" in after), bool(d.value))

        a = A.VirtSurvApp(start="settings", frozen=True)
        async with a.run_test(size=(104, 40)) as p:
            await p.pause()
            scr = a.screen
            for r in scr.rows:
                w = scr.query_one(f"#set-{r['key'].replace('.', '-')}", A.SettingRow)
                check(f"settings {r['key']}: row renders the live object", w.row is r, True)
            r0 = scr.rows[0]
            w0 = scr.query_one(f"#set-{r0['key'].replace('.', '-')}", A.SettingRow)
            scr.cursor = 0
            before = text_of(w0)
            await p.press("space")
            check("settings: drawn state changes", text_of(w0) != before, True)

        # Two instances must not share state.
        s1, s2 = A.SettingsScreen(), A.SettingsScreen()
        s1.rows[0]["value"] = not s1.rows[0]["value"]
        check("settings screens are independent",
              s2.rows[0]["value"], A.SETTING_GROUPS[0][1][0]["value"])

    asyncio.run(run())


# ── C. every decide row ───────────────────────────────────────────────────────

def test_decide_rows() -> None:
    from virt_surv2 import ui as A
    section("C  decide — every row, every interaction")

    async def run():
        a = A.VirtSurvApp(start="decide", frozen=True)
        async with a.run_test(size=(100, 34)) as p:
            await p.pause()
            scr = a.screen
            check("7 decisions", len(scr.decisions), 7)
            for i, d in enumerate(scr.decisions):
                scr.cursor = i
                scr.paint()
                if d.kind == "toggle":
                    before = d.value
                    await p.press("space")
                    check(f"toggle {d.key} on", d.value, not before)
                    await p.press("space")
                    check(f"toggle {d.key} back", d.value, before)
                elif d.kind == "choice":
                    # Walk the whole ring and land back where it started.
                    start = d.value
                    for opt in d.options[1:] + d.options[:1]:
                        await p.press("right")
                        check(f"{d.key} -> {opt}", d.value, opt)
                    check(f"{d.key} ring returns to {start}", d.value, start)
                    await p.press("left")
                    check(f"{d.key} left goes back", d.value, d.options[-1])
                    await p.press("right")
                else:
                    await p.press("enter")
                    check(f"{d.key} enter opens edit", scr.editing, True)
                    await p.press("escape")
                    check(f"{d.key} esc cancels", scr.editing, False)

            snap = scr.snapshot()
            check("snapshot has every key", sorted(snap), sorted(d.key for d in scr.decisions))

            # Wrap-around in both directions.
            scr.cursor = 0
            await p.press("up")
            check("cursor wraps to last", scr.cursor, len(scr.decisions) - 1)
            await p.press("down")
            check("cursor wraps to first", scr.cursor, 0)

        # A committed edit must reach the snapshot.
        a = A.VirtSurvApp(start="decide", frozen=True)
        async with a.run_test(size=(100, 34)) as p:
            await p.pause()
            scr = a.screen
            scr.cursor = next(i for i, d in enumerate(scr.decisions) if d.kind == "path")
            scr.paint()
            await p.press("enter")
            inp = scr.query_one("#edit")
            inp.value = "/tmp/typed-path"
            await p.press("enter")
            await p.pause()
            check("typed path commits", scr.snapshot()["clone"], "/tmp/typed-path")
            check("edit closes after commit", scr.editing, False)

        # Defaults passed in must be honoured (the seeded clone path).
        a = A.VirtSurvApp(start="decide", frozen=True)
        async with a.run_test(size=(100, 34)) as p:
            await p.pause()
            a.screen.decisions[1].value = "/seeded"
            check("seeded default survives", a.screen.snapshot()["clone"], "/seeded")

        # Two DecideScreens must not share state (module-level Decision objects).
        s1 = A.DecideScreen()
        s1.decisions[0].value = "main"
        s2 = A.DecideScreen()
        check("screens do not share decisions", s2.decisions[0].value, "dev")

    asyncio.run(run())


# ── D. all 18 settings rows ───────────────────────────────────────────────────

def test_settings_rows() -> None:
    from virt_surv2 import ui as A
    section("D  settings — all 18 rows, every option")

    async def run():
        a = A.VirtSurvApp(start="settings", frozen=True)
        async with a.run_test(size=(104, 40)) as p:
            await p.pause()
            scr = a.screen
            check("25 rows", len(scr.rows), 25)
            labels = [r["label"] for r in scr.rows]
            check("no duplicate labels", len(set(labels)), 25)
            keys = [r["key"] for r in scr.rows]
            check("no duplicate keys", len(set(keys)), 25)

            for i, r in enumerate(scr.rows):
                scr.cursor = i
                scr.paint()
                check(f"{r['label']}: has help", bool(r["what"]), True)
                if r["kind"] == "toggle":
                    before = r["value"]
                    await p.press("space")
                    check(f"{r['label']}: toggles", r["value"], not before)
                    check(f"{r['label']}: tracked as changed", r["label"] in scr.changed, True)
                    await p.press("space")
                    check(f"{r['label']}: untracked when restored",
                          r["label"] in scr.changed, False)
                else:
                    start = r["value"]
                    for opt in r["options"][1:] + r["options"][:1]:
                        await p.press("right")
                        check(f"{r['label']} -> {opt}", r["value"], opt)
                    check(f"{r['label']}: ring closes", r["value"], start)

            # Change everything, then restore everything.
            for i, r in enumerate(scr.rows):
                scr.cursor = i
                if r["kind"] == "toggle":
                    await p.press("space")
                else:
                    await p.press("right")
            check("all rows marked changed", len(scr.changed), 25)
            await p.press("d")
            check("d restores every default",
                  [r["value"] for r in scr.rows],
                  [scr.defaults[r["label"]] for r in scr.rows])
            check("d clears the change list", scr.changed, [])

    asyncio.run(run())


# ── E. every launcher row ─────────────────────────────────────────────────────

def test_launcher_rows() -> None:
    from virt_surv2 import ui as A
    section("E  launcher — every row and its detail pane")

    async def run():
        # Real row_view-shaped rows, not the old mock constant.
        rows = [{"title": "spoofing-review", "status": "in progress", "mark": "●",
                 "mark_style": "", "recommended": True,
                 "lines": [("status", "in progress"), ("next", "tune thresholds")]},
                {"title": "wash-trade-pack", "status": "blocked", "mark": "◐",
                 "mark_style": "warn", "recommended": False,
                 "lines": [("status", "blocked"), ("next", "await feed")]}]
        a = A.VirtSurvApp(start="launch", frozen=True, project="/tmp/proj", rows=rows)
        async with a.run_test(size=(104, 36)) as p:
            await p.pause()
            scr = a.screen
            n = len(rows) + len(A.ACTIONS)
            check("every engagement and action is selectable", len(scr.selectable), n)
            for i in range(len(scr.selectable)):
                scr.cursor = i
                scr.paint()          # must not raise for any row
            check("walked every row", scr.cursor, len(scr.selectable) - 1)

            # From a known position — the loop above left the cursor at the end.
            n_sel = len(scr.selectable)
            scr.cursor = 0
            for _ in range(n_sel + 2):
                await p.press("down")
            check("down wraps past the end", scr.cursor, 2)
            for _ in range(n_sel + 4):
                await p.press("up")
            check("up wraps past the start", scr.cursor, (2 - (n_sel + 4)) % n_sel)

            check("every action has a blurb",
                  all(blurb for _k, _l, blurb in A.ACTIONS), True)
            check("every engagement has detail lines",
                  all(r["lines"] for r in rows), True)

        # Empty folder: it must say WHICH folder, not show a bare heading.
        a = A.VirtSurvApp(start="launch", frozen=True, project="/tmp/empty",
                          rows=[], note="no open engagements in this folder")
        async with a.run_test(size=(104, 36)) as p:
            await p.pause()
            scr = a.screen
            check("no phantom resume heading",
                  any(k == "group" and v == "Resume an engagement" for k, v in scr.rows),
                  False)
            check("the folder is named", "/tmp/empty" in scr._folder(), True)
            detail = scr.query_one("#detail")
            txt = getattr(detail, "content", "")
            txt = txt.plain if hasattr(txt, "plain") else str(txt)
            check("empty state names the folder", "/tmp/empty" in txt, True)

    asyncio.run(run())


# ── F. key fuzz — no key may crash a screen ───────────────────────────────────

KEYS = ["up", "down", "left", "right", "enter", "space", "tab", "escape",
        "home", "end", "pageup", "pagedown", "backspace", "delete",
        "a", "c", "d", "i", "j", "k", "n", "y", "0", "?", "/"]


def test_key_fuzz() -> None:
    from virt_surv2 import ui as A
    section("F  key fuzz — every key on every screen")

    async def run():
        for start in ("decide", "install", "launch", "settings"):
            a = A.VirtSurvApp(start=start, frozen=True)
            async with a.run_test(size=(100, 36)) as p:
                await p.pause()
                for key in KEYS:
                    if key in ("q", "escape"):
                        continue          # those legitimately leave
                    await p.press(key)
                    if not a._running:
                        check(f"{start}: {key!r} must not exit", a._running, True)
                        break
                else:
                    check(f"{start}: survived {len(KEYS)} keys", a._running, True)

    asyncio.run(run())


# ── G. responsive on every screen ─────────────────────────────────────────────

def test_responsive_matrix() -> None:
    from virt_surv2 import ui as A
    section("G  responsive — every screen either side of the breakpoint")

    async def run():
        for start in ("decide", "install", "launch", "settings"):
            for width in (40, 62, 75, 76, 100, 140):
                a = A.VirtSurvApp(start=start, frozen=True)
                async with a.run_test(size=(width, 36)) as p:
                    await p.pause()
                    check(f"{start} @{width}", a.screen.narrow, width < A.NARROW)

    asyncio.run(run())


# ── H. every engine failure mode ──────────────────────────────────────────────

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
            done.set()


class StubApp:
    def call_from_thread(self, fn, *a): return fn(*a)


class DeadApp:
    """An app that is already shutting down: call_from_thread raises."""
    def call_from_thread(self, fn, *a): raise RuntimeError("app is gone")


def test_failure_modes() -> None:
    from virt_surv2 import engine as E
    FE = fake_engine()
    section("H  engine failure modes")

    for mode, want_code, marker in (
        ("normal", 0, None),
        ("escalate", 0, None),
        ("stray", 0, None),
        ("crash", 1, "RuntimeError"),
        ("crash_keyboard", 130, "KeyboardInterrupt"),
        ("crash_os", 1, "OSError"),
        ("crash_exit", 1, "SystemExit"),
    ):
        FE.MODE = mode
        scr = StubScreen(answer=True)
        out, err, ask, conf = sys.stdout, sys.stderr, FE.ask, FE.confirm
        code = E.run_installer(FE, StubApp(), scr, {"channel": "dev"}, None, True)
        check(f"{mode}: exit code", code, want_code)
        check(f"{mode}: engine_finished delivered", scr.finished is not None, True)
        check(f"{mode}: stdout restored", sys.stdout is out, True)
        check(f"{mode}: stderr restored", sys.stderr is err, True)
        check(f"{mode}: ask restored", FE.ask is ask, True)
        check(f"{mode}: confirm restored", FE.confirm is conf, True)
        if marker:
            check(f"{mode}: names the cause", marker in (scr.finished[2] or ""), True)
            check(f"{mode}: traceback captured", bool(scr.crash_detail), True)

    # The app disappearing mid-run must not raise out of the observer or the finally.
    FE.MODE = "normal"
    scr = StubScreen(answer=True)
    code = E.run_installer(FE, DeadApp(), scr, {"channel": "dev"}, None, True)
    check("app gone mid-run: still returns a code", isinstance(code, int), True)
    check("app gone mid-run: stdout restored", sys.stdout is out, True)

    # A prompt nobody answers, released from elsewhere.
    FE.MODE = "escalate"
    scr = StubScreen(answer=None)
    broker = E.PromptBroker(StubApp(), scr)
    threading.Timer(0.4, broker.release_all).start()
    check("release_all frees the engine", E.run_installer(
        FE, StubApp(), scr, {"channel": "dev"}, None, True, broker=broker), 0)

    # Once closed, the broker must answer instantly rather than park a new caller.
    check("closed broker returns the default", broker.escalate("confirm", "x?", True), True)


# ── I. find_repo / load_engine ────────────────────────────────────────────────

def test_analysers() -> None:
    from virt_surv2 import engine as E
    section("K  review analysers — the packages no install path ever installed")

    repo = Path("/home/daniel/www/virt-survtecb")
    if (repo / "requirements-review.txt").exists():
        specs = E.analyser_specs(repo)
        names = [x.split(">")[0].split("=")[0] for x in specs]
        check("analysers found", sorted(names),
              ["bandit", "black", "mypy", "ruff", "sqlfluff"])
        check("tree-sitter excluded (the engine installs those)",
              any("tree-sitter" in x for x in specs), False)
        check("pins preserved", all(">" in x or "=" in x for x in specs), True)
    # Installing analysers without dropping the probe cache means the team keeps
    # reporting them missing for up to a week - run_tool_reprobe exists because of
    # exactly that, and the code-intel step avoids it by clearing the cache itself.
    import inspect
    src = inspect.getsource(E._install_analysers)
    check("analyser install clears the tool cache", "_invalidate_tool_cache" in src, True)
    check("cache clearing is not fatal", "never fatal" in src or "best-effort" in src, True)

    check("missing repo is survivable", E.analyser_specs(None), [])
    check("bad path is survivable", E.analyser_specs(Path("/nope/nope")), [])


def test_step_labels_make_sense() -> None:
    """Every step title a user can see must read as an outcome, not a question or
    an internal mechanism.

    Reported twice: "(optional)" on steps nobody was offered, then "Setup mode",
    which named a mechanism and meant nothing.
    """
    import re as _re

    from virt_surv2.live import TITLE_OVERRIDES, display_title
    section("M  step labels")

    import install_helper as ih
    raw = Path(ih.__file__).read_text(encoding="utf-8")
    # Titles build_plan can emit, as literals in its (title, step) rows.
    titles = set(_re.findall(r'\(\s*"([A-Z][^"]{3,60})",\s*self\.\w+\)', raw))
    check("found build_plan titles", len(titles) > 8, True)

    for title in sorted(titles):
        shown = display_title(title)
        check(f"{shown!r} is not a question", shown.endswith("?"), False)
        check(f"{shown!r} does not say optional", "optional" in shown.lower(), False)

    for shown in TITLE_OVERRIDES.values():
        check(f"{shown!r} is not a question", shown.endswith("?"), False)
        check(f"{shown!r} does not say optional", "optional" in shown.lower(), False)
        check(f"{shown!r} is not jargon-only", shown.strip() != "", True)


def test_first_run_offer() -> None:
    """An unconfigured folder must be offered first-time setup, as virt-surv go does.

    The check is the launcher's own _plugin_enabled, so v1 and v2 cannot disagree
    about what "set up" means.
    """
    from virt_surv2 import engine as E
    from virt_surv2 import ui as A
    section("N  first-time setup offer")

    import install_helper as ih
    repo = Path(ih.__file__).resolve().parent
    check("the repo reads as configured",
          E.project_is_configured(repo, repo), True)
    with tempfile.TemporaryDirectory() as td:
        check("a bare folder reads as not configured",
              E.project_is_configured(repo, Path(td)), False)
    check("no repo means unknown, not 'not set up'",
          E.project_is_configured(None, Path("/tmp")), None)

    check("three answers, like v1's setup screen", len(A.FIRST_RUN), 3)
    actions = [a for a, _l, _b in A.FIRST_RUN]
    check("offers defaults, guided and skip", sorted(actions),
          ["configure", "onboard", "skip"])
    check("onboard is runnable", "onboard" in E.RUN_FUNCTIONS, True)

    async def run():
        app = A.VirtSurvApp(start="launch", frozen=True, project="/tmp/x", rows=[],
                            note="no open engagements in this folder")
        async with app.run_test(size=(100, 30)) as p:
            await p.pause()
            # VirtSurvApp has no engine, so it shows the launcher directly; the offer
            # is the engine-backed app's job. Assert the screen at least names the
            # folder rather than inventing one.
            check("launcher names the folder", "/tmp/x" in app.screen._folder(), True)

        scr = A.FirstRunScreen("/tmp/unconfigured")
        check("first-run screen keeps the folder",
              str(scr.project), "/tmp/unconfigured")

    asyncio.run(run())


def test_menu_parity_with_v1() -> None:
    """Every option virt-surv offers must exist in virt-surv2.

    Asserted against install_helper's OWN tables, not a copy of them, so adding an
    option to v1 without adding it here fails immediately instead of leaving v2
    quietly missing a feature.
    """
    import ast

    from virt_surv2 import ui as A
    section("L  parity - every virt-surv option exists in virt-surv2")

    import install_helper as ih
    src = ast.parse(Path(ih.__file__).read_text(encoding="utf-8"))
    tables = {}
    for node in src.body:
        if isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", "")
            if name in ("MENU_ACTIONS", "_ADVANCED_ACTIONS", "_DIAGNOSTICS_ACTIONS"):
                tables[name] = ast.literal_eval(node.value)

    v1_top = {v for v in tables["MENU_ACTIONS"].values()}
    v2_top = {a for _k, a, _l, _b in A.MAIN_MENU}
    check("top-level menu covers every v1 action", sorted(v1_top - v2_top), [])
    check("top-level keys match v1", [k for k, _a, _l, _b in A.MAIN_MENU],
          list(tables["MENU_ACTIONS"].keys()))

    v1_adv = {v for v in tables["_ADVANCED_ACTIONS"].values()} - {"back"}
    v2_adv = {a for a, _l, _b in A.ADVANCED}
    # An item may be absent only if DEDUPED says where it went - so "we consolidated
    # this on purpose" and "we forgot this" can never look the same.
    check("advanced covers every v1 action (or records where it moved)",
          sorted(v1_adv - v2_adv - set(A.DEDUPED)), [])
    for action, where in A.DEDUPED.items():
        check(f"{action} names its destination", len(where) > 20, True)
        check(f"{action} is genuinely a v1 action", action in v1_adv, True)

    v1_diag = {v for v in tables["_DIAGNOSTICS_ACTIONS"].values()} - {"back"}
    v2_diag = {a for a, _l, _b in A.DIAGNOSTICS}
    check("diagnostics covers every v1 action", sorted(v1_diag - v2_diag), [])

    # Everything reachable must actually be runnable: an Installer subset, a run_*
    # function, or a screen the UI handles itself.
    from virt_surv2 import engine as E
    # Screens the UI handles itself, plus demo (run_action maps it to the full plan
    # with args.demo set, which is what v1's menu does too).
    handled = {"full", "quit", "advanced", "diagnostics", "demo"}
    # The subsets build_plan actually branches on, read from the RAW source: unparsing
    # the AST normalises quoting, so matching a double-quoted literal against it
    # silently found nothing and every check "failed".
    import re as _re
    raw = Path(ih.__file__).read_text(encoding="utf-8")
    subsets = set(_re.findall(r'self\.subset == "([a-z0-9]+)"', raw))
    check("build_plan exposes subsets", len(subsets) > 10, True)
    for action in sorted((v2_top | v2_adv | v2_diag) - handled):
        runnable = action in E.RUN_FUNCTIONS or action in subsets
        check(f"{action} is runnable", runnable, True)


def test_discovery() -> None:
    from virt_surv2 import engine as E
    section("I  find_repo / load_engine")

    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "clone"
        good.mkdir()
        (good / "install_helper.py").write_text("x = 1\n")
        check("explicit valid repo", E.find_repo(str(good)), good.resolve())

        try:
            E.find_repo(str(Path(td) / "nope"))
            check("explicit missing repo raises", False, True)
        except E.EngineNotFound as exc:
            check("explicit missing repo message", "no install_helper.py" in str(exc), True)

        # Walks up from cwd.
        deep = good / "a" / "b"
        deep.mkdir(parents=True)
        cwd = os.getcwd()
        try:
            os.chdir(deep)
            check("finds repo by walking up", E.find_repo(), good.resolve())
        finally:
            os.chdir(cwd)

        # A module missing the seams must be rejected with a readable message.
        import types
        fake = types.ModuleType("install_helper")
        sys.modules["install_helper"] = fake
        try:
            E.load_engine(good)
            check("incomplete engine rejected", False, True)
        except E.EngineNotFound as exc:
            check("incomplete engine names what is missing", "Installer" in str(exc), True)
        finally:
            del sys.modules["install_helper"]


# ── J. the modal, every kind × every key ──────────────────────────────────────

def test_modal_matrix() -> None:
    from textual.app import App

    from virt_surv2.live import PromptModal
    section("J  modal — every kind × every key")

    class T(App):
        def __init__(self, kind, default):
            super().__init__()
            self.kind, self.default = kind, default
            self.box, self.done = {}, threading.Event()

        def on_mount(self):
            self.push_screen(PromptModal(self.kind, "Shall I?", self.default,
                                         self.box, self.done, "ctx"))

    async def press(kind, default, keys, typed=None):
        app = T(kind, default)
        async with app.run_test(size=(90, 30)) as p:
            await p.pause()
            if typed is not None:
                app.screen.query_one("#modal-input").value = typed
            for k in keys:
                await p.press(k)
            await p.pause()
            return app.done.is_set(), app.box.get("value", "<unset>")

    async def run():
        for default in (True, False):
            for keys, want in ((["y"], True), (["n"], False),
                               (["enter"], default), (["escape"], default)):
                got = await press("confirm", default, keys)
                check(f"confirm default={default} {keys}", got, (True, want))

        for keys, typed, want in (
            (["enter"], None, "claude"),
            (["escape"], None, "claude"),
            (["enter"], "cc", "cc"),
            (["escape"], "cc", "claude"),      # esc discards the edit, takes the default
            (["enter"], "   ", "claude"),      # whitespace-only falls back
        ):
            got = await press("ask", "claude", keys, typed)
            check(f"ask {keys} typed={typed!r}", got, (True, want))

        # A second key after answering must not answer twice.
        app = T("confirm", True)
        async with app.run_test(size=(90, 30)) as p:
            await p.pause()
            await p.press("y")
            await p.press("n")
            await p.pause()
            check("double answer ignored", app.box.get("value"), True)

    asyncio.run(run())


if __name__ == "__main__":
    test_build_args()
    test_answers_matrix()
    test_render_reflects_model()
    test_decide_rows()
    test_settings_rows()
    test_launcher_rows()
    test_key_fuzz()
    test_responsive_matrix()
    test_failure_modes()
    test_step_labels_make_sense()
    test_first_run_offer()
    test_menu_parity_with_v1()
    test_analysers()
    test_discovery()
    test_modal_matrix()

    print(f"\n{COUNT} checks run")
    if FAILED:
        print(f"{len(FAILED)} FAILED:")
        for f in FAILED:
            print("  - " + f)
        raise SystemExit(1)
    print("all passed")
