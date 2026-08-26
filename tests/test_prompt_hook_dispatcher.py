"""One UserPromptSubmit hook instead of two (F4, 2026-08-26 perf audit).

`persona_anchor.py` and `engage_probe_prefetch.py` were registered as two independent
UserPromptSubmit entries, so every user message paid two full launcher chains - two shells,
two interpreter cold starts, two daemon round trips - for hooks whose actual work measures
0.88ms and 0.66ms. `scripts/prompt_hook_dispatcher.py` runs both in one process, the same
pattern `bash_hook_dispatcher.py` already established for the five Bash hooks.

These hooks are NOT safety guards: they inject context by printing to stdout and always
return 0. So the properties worth pinning are different from the Bash dispatcher's - output
fidelity and ORDER, not exit codes and short-circuiting - and the failure polarity is the
opposite: a crash must cost the injected context, never the user's prompt.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DISPATCHER = REPO / "scripts" / "prompt_hook_dispatcher.py"


def _load():
    spec = importlib.util.spec_from_file_location("prompt_hook_dispatcher", DISPATCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(prompt: str = "hello") -> str:
    return json.dumps(
        {
            "session_id": "t",
            "transcript_path": "/tmp/x",
            "cwd": str(REPO),
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
        }
    )


def _run(payload: str, script: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout


# --------------------------------------------------------------- output fidelity


@pytest.mark.parametrize("prompt", ["/engage", "/compliance-surveillance-team:engage --new"])
def test_the_dispatcher_emits_exactly_what_the_two_hooks_emitted(prompt):
    """The whole justification is that nothing observable changes. Uses prompts that make
    the prefetch hook actually produce output - an all-empty comparison would pass whatever
    the dispatcher did."""
    payload = _payload(prompt)
    _, anchor = _run(payload, REPO / "scripts" / "persona_anchor.py")
    _, prefetch = _run(payload, REPO / "scripts" / "engage_probe_prefetch.py")
    code, combined = _run(payload, DISPATCHER)
    assert code == 0
    assert combined == anchor + prefetch
    assert combined, "this prompt must produce output, or the test proves nothing"


def test_a_dormant_prompt_still_emits_nothing_at_all():
    """Dormancy is a product requirement, not an optimisation: an ordinary prompt in an
    un-engaged session must inject no context. No blank lines, no separators."""
    code, out = _run(_payload("what is the weather"), DISPATCHER)
    assert code == 0
    assert out == ""


# --------------------------------------------------------------- order and isolation


def test_order_is_preserved(monkeypatch, tmp_path):
    """Order is the contract - it is the order the two separate entries ran in, and so the
    order the injected context appeared in the prompt."""
    module = _load()
    calls = []

    class _Fake:
        def __init__(self, tag):
            self.tag = tag

        def main(self):
            calls.append(self.tag)
            print(f"[{self.tag}]", end="")
            return 0

    monkeypatch.setattr(module, "_PROMPT_HOOKS", (("a", tmp_path), ("b", tmp_path)))
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    tags = iter(["a", "b"])
    monkeypatch.setattr(module, "_load", lambda name, path: _Fake(next(tags)))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(_payload()))
    out = __import__("io").StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    module.main()
    assert calls == ["a", "b"]
    assert out.getvalue() == "[a][b]"


def test_one_hook_crashing_does_not_cost_the_other_or_the_prompt(monkeypatch, tmp_path):
    """Fail-open, the opposite polarity to the Bash dispatcher. Neither hook is a safety
    guard; losing injected context is acceptable, losing the user's turn is not."""
    module = _load()

    class _Boom:
        def main(self):
            raise RuntimeError("hook exploded")

    class _Fine:
        def main(self):
            print("survived", end="")
            return 0

    monkeypatch.setattr(module, "_PROMPT_HOOKS", (("boom", tmp_path), ("fine", tmp_path)))
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    mods = iter([_Boom(), _Fine()])
    monkeypatch.setattr(module, "_load", lambda name, path: next(mods))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(_payload()))
    out = __import__("io").StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert module.main() == 0, "a crashing hook must never block the prompt"
    assert out.getvalue() == "survived"


def test_a_hook_that_exits_still_contributes_what_it_printed(monkeypatch, tmp_path):
    """Both real hooks call sys.exit(main()); bypassing their __main__ block means a
    SystemExit can still surface from inside main() itself."""
    module = _load()

    class _Exiter:
        def main(self):
            print("printed-then-exited", end="")
            raise SystemExit(0)

    monkeypatch.setattr(module, "_PROMPT_HOOKS", (("exiter", tmp_path),))
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(module, "_load", lambda name, path: _Exiter())
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(_payload()))
    out = __import__("io").StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert module.main() == 0
    assert out.getvalue() == "printed-then-exited"


def test_a_malformed_payload_fails_open():
    proc = subprocess.run(
        [sys.executable, str(DISPATCHER)], input="not json", capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_a_missing_hook_file_is_skipped_not_fatal(monkeypatch, tmp_path):
    module = _load()
    monkeypatch.setattr(module, "_PROMPT_HOOKS", (("gone", tmp_path / "nope.py"),))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(_payload()))
    out = __import__("io").StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert module.main() == 0
    assert out.getvalue() == ""


def test_it_dispatches_the_two_real_hooks_in_the_registered_order():
    """Guards against someone adding a hook by inserting rather than appending."""
    module = _load()
    names = [name for name, _ in module._PROMPT_HOOKS]
    assert names == ["persona_anchor", "engage_probe_prefetch"]
    for _, path in module._PROMPT_HOOKS:
        assert path.is_file(), f"registered hook missing: {path}"
