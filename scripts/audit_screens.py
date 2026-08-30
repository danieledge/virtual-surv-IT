#!/usr/bin/env python3
"""Every menu option, every screen, and whether each is actually wired.

WHY THIS IS A SCRIPT AND NOT A README. The launcher has three tiers, two menu systems and
about twenty options, and every wiring bug this month was invisible from the outside: a
screen that could not be imported looked merely unavailable, a menu that printed its own
numbered list looked like a tier falling back, and a helper shadowed by an older function
of the same name looked like a fix that did not work. None of those were findable by
reading, and all three were findable by asking the code.

So this asks. It is read-only and consent-free (allow-listed in the code-execution guard),
and it is meant to be run before a release and after any menu change:

    python -m scripts.audit_screens            # the report
    python -m scripts.audit_screens --strict   # exit 1 if anything is unwired

WHAT IT CHECKS, and what each column means:

  reached      the menu key resolves to an action, and the action is dispatched somewhere.
               An option nobody can reach is the worst kind of dead code, because the menu
               still advertises it.
  asks         where this option's questions are put: a screen, a typed prompt, or none.
  streams      whether the work scrolls past as a step log.
  tiers        which of the three renderings can actually draw this option's screens.

It deliberately does NOT judge whether streaming is wrong. Diagnostics stream on purpose:
their output is the deliverable, and a bounded pane would hide it.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for candidate in (REPO, REPO / "scripts", REPO / "vendor"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

PROMPTS = ("ask", "confirm", "input")
SCREEN_CALLS = (
    "_tiered_installer_screen",
    "_submenu_screen",
    "_choose_submenu",
    "_ask",
    "_agreed",
    "_pick_project",
    "run_subset_in_app",
    "run_update_in_app",
    "agree",
    "pick_project",
    "_machine_defaults_grid",
    "_review_tool_grid",
    # The framework's own entry points. `_ask().choose(...)` parses as a call to `choose`,
    # so stopping at `_ask` alone still walked into _PlainQuestions.choose and found its
    # input() - the stand-in's fallback, reported as if it were a bare prompt.
    "choose",
)


def _index(tree):
    """Every function in the file by name, methods included.

    Flat rather than scoped, which is a simplification worth naming: two functions with the
    same name in different classes would collide here. install_helper has none - there is a
    test asserting exactly that, added after a duplicate _repo_hint silently shadowed a new
    one - so the flat index is safe for this file and would not be for an arbitrary one.
    """
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _prompt_lines(node, targets, screen_names):
    """Line numbers of prompts in `node` that are NOT a screen's fallback.

    A prompt after a screen attempt in the same function is that screen's fallback - see
    the module note. Source order, not control flow; deliberately.
    """
    screens = [
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and (
            getattr(call.func, "id", None) in screen_names
            or getattr(call.func, "attr", None) in screen_names
        )
    ]
    first_screen = min(screens) if screens else None
    out = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        if name not in targets:
            continue
        if isinstance(call.func, ast.Attribute):
            continue  # self.confirm-style calls are the helpers, not the prompt
        if first_screen is not None and call.lineno > first_screen:
            continue  # the screen's own fallback
        out.append((call.lineno, name))
    return out


def _reaches(name, index, targets, seen=None, stop_at=()):
    """Whether anything in `targets` is callable from `name`, following the call graph.

    Recursive because the interesting cases are never at the top: fixbashrc and
    cleanplugincache both look quiet at the step and both ask, one and two calls down, and
    a step that asks inside a full-screen app does not degrade - it hangs.

    `stop_at` names functions not to descend into. It exists for one specific distortion:
    every screen helper ENDS with the typed question it replaced, for the console that
    cannot draw one. Walking through those found a prompt behind every option in the
    product and reported all of them - a checker that says the same thing about everything
    says nothing. A prompt reachable only through a screen-first helper is the documented
    fallback; a prompt reachable any other way is one somebody actually meets.
    """
    seen = seen if seen is not None else set()
    if name in seen or name not in index:
        return False
    seen.add(name)
    if targets == set(PROMPTS) and _prompt_lines(index[name], targets, set(stop_at)):
        return True
    for call in ast.walk(index[name]):
        if not isinstance(call, ast.Call):
            continue
        direct = getattr(call.func, "id", None)
        attr = getattr(call.func, "attr", None)
        if targets != set(PROMPTS) and (direct in targets or attr in targets):
            return True
        for nested in (direct, attr):
            if nested and nested in index and nested not in stop_at and nested not in targets:
                if _reaches(nested, index, targets, seen, stop_at):
                    return True
    return False


def _path_to(name, index, targets, seen=None, stop_at=(), chain=()):
    """The call chain from `name` to the first thing in `targets`, or None.

    Same walk as _reaches, but it keeps the route. "There is a typed question somewhere
    below this" is not something anyone can act on; "format_preferences_step ->
    _ask_review_tool_overrides -> confirm()" is.
    """
    seen = seen if seen is not None else set()
    if name in seen or name not in index:
        return None
    seen.add(name)
    chain = chain + (name,)
    if targets == set(PROMPTS):
        hits = _prompt_lines(index[name], targets, set(stop_at))
        if hits:
            return " -> ".join(chain) + f" -> {hits[0][1]}()"
    for call in ast.walk(index[name]):
        if not isinstance(call, ast.Call):
            continue
        direct = getattr(call.func, "id", None)
        attr = getattr(call.func, "attr", None)
        if targets != set(PROMPTS) and (direct in targets or attr in targets):
            return " -> ".join(chain) + f" -> {direct or attr}()"
        for nested in (direct, attr):
            if nested and nested in index and nested not in stop_at and nested not in targets:
                found = _path_to(nested, index, targets, seen, stop_at, chain)
                if found:
                    return found
    return None


def _dispatch_blocks(index):
    """{action: source of the branch that handles it} from the interactive menu loop."""
    main = index.get("_main")
    if main is None:
        return {}
    blocks = {}
    for node in ast.walk(main):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare) and getattr(test.left, "id", "") == "action"):
            continue
        for comparator in test.comparators:
            value = getattr(comparator, "value", None)
            if isinstance(value, str):
                blocks[value] = "\n".join(ast.unparse(stmt) for stmt in node.body)
    return blocks


def audit():
    import install_helper as ih

    source = (REPO / "install_helper.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    index = _index(tree)
    dispatched = _dispatch_blocks(index)

    class _Args:
        def __getattr__(self, _name):
            return None

    rows = []
    menus = (
        ("top", ih.MENU_ACTIONS),
        ("advanced", ih._ADVANCED_ACTIONS),
        ("diagnostics", ih._DIAGNOSTICS_ACTIONS),
    )
    for menu, table in menus:
        for key, action in sorted(table.items(), key=lambda kv: (len(kv[0]), kv[0])):
            if action in ("back", "quit"):
                continue
            if action in ("diagnostics", "advanced"):
                # Submenu openers, not runnable subsets: they loop back to choose_action.
                # Building a plan for them returns the FULL plan, so they inherited the
                # full install's questions and reported as findings of their own.
                rows.append(
                    {
                        "menu": menu,
                        "key": key,
                        "action": action,
                        "entry": "(submenu)",
                        "reached": True,
                        "asks": "screen",
                        "also_typed": False,
                        "streams": False,
                        "route": None,
                    }
                )
                continue
            block = dispatched.get(action)
            entry = None
            if block:
                for name in index:
                    if name.startswith("run_") and f"{name}(" in block:
                        entry = name
                        break

            if entry:
                # The DOOR first - what the dispatch branch itself does - then the handler.
                # Item 2 picks its project on a screen and hands an already-configured
                # project to the settings editor before run_configure is reached at all,
                # so judging the handler alone called the option typed when it is not.
                door_screen = any(call in block for call in SCREEN_CALLS)
                asks_screen = door_screen or _reaches(entry, index, set(SCREEN_CALLS))
                asks_typed = _reaches(entry, index, set(PROMPTS), stop_at=set(SCREEN_CALLS))
                route = _path_to(entry, index, set(PROMPTS), stop_at=set(SCREEN_CALLS))
                streams = False
                reached = True
            else:
                # No named handler: it is an Installer subset, run through the generic
                # branch. Its questions live in the steps of its own plan.
                subset = "full" if action == "full" else action
                try:
                    plan = ih.Installer(
                        _Args(), ih.Style(False), ih.marks(), subset=subset
                    ).build_plan()
                    steps = [step.__name__ for _title, step in plan]
                    reached = bool(steps)
                except Exception:
                    steps, reached = [], False
                asks_screen = any(_reaches(s, index, set(SCREEN_CALLS)) for s in steps)
                asks_typed = any(
                    _reaches(s, index, set(PROMPTS), stop_at=set(SCREEN_CALLS)) for s in steps
                )
                route = next(
                    (
                        r
                        for r in (
                            _path_to(s, index, set(PROMPTS), stop_at=set(SCREEN_CALLS))
                            for s in steps
                        )
                        if r
                    ),
                    None,
                )
                in_app = subset in ih._IN_APP_SUBSETS
                if subset == "update":
                    # Dispatched through the generic branch, but it has a screen in front
                    # of it: run_update_in_app asks its two questions on a decision screen
                    # and then watches the run on a progress screen. Reading only the plan
                    # missed that and reported it as typed-only.
                    asks_screen, asks_typed, in_app = True, False, True
                streams = not in_app
                entry = f"subset:{subset}"

            rows.append(
                {
                    "menu": menu,
                    "key": key,
                    "action": action,
                    "entry": entry,
                    "reached": reached,
                    "asks": ("screen" if asks_screen else ("typed" if asks_typed else "-")),
                    # A screen at the door with typed questions behind it. Worth seeing
                    # rather than flagging: a long guided sequence is the same shape as the
                    # full install, which is deliberately left alone.
                    "also_typed": asks_screen and asks_typed,
                    "route": route,
                    "streams": streams,
                }
            )
    return rows


def tier_report():
    """Which screens each tier can draw, and where they disagree.

    A screen present in one tier and missing from the other is not a bug by itself - the
    installer's tier legitimately has fewer - but a MISMATCHED SIGNATURE is, because the
    dispatcher calls both with the same arguments.
    """
    import inspect

    import install_helper as ih

    out = {}
    for name in ("launcher_textual", "installer_app"):
        module = ih._import_from_scripts(name)
        if module is None:
            out[name] = None
            continue
        out[name] = {
            # Parameter NAMES, not the rendered signature. The dispatcher calls both tiers
            # with the same keyword arguments, so a differing type annotation is not a
            # disagreement - and comparing the rendered form reported one that was not
            # there (`repo: Path | None = None` against `repo=None`).
            attr: list(inspect.signature(getattr(module, attr)).parameters)
            for attr in dir(module)
            if attr.endswith("_screen") and callable(getattr(module, attr))
        }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--strict", action="store_true", help="exit 1 if anything is unwired")
    args = parser.parse_args(argv)

    rows = audit()
    print("\n  MENU OPTIONS")
    print(f"  {'menu':<12} {'key':>3}  {'action':<18} {'reached':<8} {'asks':<7} streams")
    problems = []
    for row in rows:
        flag = "" if row["reached"] else "  <- UNREACHABLE"
        if not row["reached"]:
            problems.append(f"{row['menu']}/{row['key']} ({row['action']}) is not dispatched")
        deeper = "  (asks deeper in - see below)" if row["also_typed"] else ""
        print(
            f"  {row['menu']:<12} {row['key']:>3}  {row['action']:<18} "
            f"{str(row['reached']):<8} {row['asks']:<7} {str(row['streams']):<6}{flag}{deeper}"
        )

    print("\n  SCREENS BY TIER")
    tiers = tier_report()
    textual = tiers.get("launcher_textual") or {}
    installer = tiers.get("installer_app") or {}
    for name in sorted(set(textual) | set(installer)):
        in_t, in_i = name in textual, name in installer
        note = ""
        if in_t and in_i and textual[name] != installer[name]:
            note = "  <- SIGNATURES DIFFER"
            problems.append(f"{name}: tiers disagree on arguments")
        print(
            f"  {name:<26} textual={'yes' if in_t else ' - '} "
            f"installer={'yes' if in_i else ' - '}{note}"
        )

    print("\n  SUMMARY")
    print(
        f"  {len(rows)} menu options, {sum(1 for r in rows if r['asks'] == 'screen')} ask on a screen"
    )
    print(f"  {sum(1 for r in rows if r['asks'] == 'typed')} still ask only at a typed prompt")
    deeper = [r for r in rows if r["also_typed"]]
    if deeper:
        print(f"\n  {len(deeper)} open on a screen and then ask at a prompt:")
        for row in deeper:
            print(f"    {row['menu']}/{row['key']:<3} {row['action']:<18} {row['route'] or '?'}")
    print(f"  {sum(1 for r in rows if r['streams'])} stream their work as a step log")
    if problems:
        print("\n  PROBLEMS")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("\n  no unreachable options and no tier disagreements")
    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
