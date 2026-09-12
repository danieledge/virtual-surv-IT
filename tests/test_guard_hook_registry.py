"""Every registered hook script must be write-protected (2026-09-12 audit, H-16).

The protected set in guard-consent-writes.py was written when the dispatcher was the only
scripts/-resident hook, and was widened reactively twice after that. Both widenings missed
files that were already wired: `prompt_hook_dispatcher.py` and `stop_hook_dispatcher.py` are
named directly in settings.json/hooks.json, `locked_menu_guard.py` is a BLOCKING PreToolUse
hook, `module_form_redirect.py` holds the permission-decision channel, and seven more run on
a hook event. All were model-writable.

This test is the thing that fails when the next hook is registered without being added to the
list. It reads the WIRING (settings.json, hooks.json, the dispatcher registries) and asserts
the staged consent guard covers everything it finds - deriving the EXPECTATION from the wiring
while the guard keeps its own explicit list, which is the point: the guard must not derive its
protection from a file it is protecting.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CONSENT = REPO / "scripts" / "staged_hooks" / "guard-consent-writes.py"

_NO_CONSENT_DIR = tempfile.mkdtemp(prefix="hook-registry-project-")


def _blocks(path: str) -> bool:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = _NO_CONSENT_DIR
    payload = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
    proc = subprocess.run(
        [sys.executable, str(CONSENT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode == 2


def _wired_hook_scripts() -> set:
    """Script basenames named in the hook COMMANDS of settings.json and hooks.json."""
    found: set = set()
    for wiring in (REPO / ".claude" / "settings.json", REPO / "hooks" / "hooks.json"):
        try:
            text = wiring.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in re.finditer(r"scripts[/\\]([A-Za-z_][A-Za-z0-9_]*)\.py", text):
            found.add(match.group(1))
        for match in re.finditer(r"run-guard\.sh[\"'\s]+\S*?([A-Za-z_][A-Za-z0-9_]*)\.py", text):
            found.add(match.group(1))
    return found


def _dispatcher_registered() -> set:
    """Script basenames the three dispatchers load on a hook event."""
    found: set = set()
    for name in ("bash_hook_dispatcher", "prompt_hook_dispatcher", "stop_hook_dispatcher"):
        for base in (REPO / "scripts", REPO / "scripts" / "staged_hooks"):
            path = base / f"{name}.py"
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r'_SCRIPTS_DIR\s*/\s*"([A-Za-z_][A-Za-z0-9_]*)\.py"', text):
                found.add(match.group(1))
            for match in re.finditer(r'"([A-Za-z_][A-Za-z0-9_]*)\.py"', text):
                found.add(match.group(1))
        found.add(name)
    # Only the ones that really exist as scripts - the regexes above are deliberately broad.
    return {n for n in found if (REPO / "scripts" / f"{n}.py").is_file()}


def test_the_wiring_actually_names_some_hook_scripts():
    """A guard against this file passing because it found nothing to check."""
    assert _wired_hook_scripts(), "no hook scripts found in settings.json / hooks.json"
    assert len(_dispatcher_registered()) >= 5


@pytest.mark.parametrize("name", sorted(_wired_hook_scripts() | _dispatcher_registered()))
def test_a_registered_hook_script_cannot_be_written(name):
    assert _blocks(f"scripts/{name}.py"), (
        f"scripts/{name}.py runs on a hook event but is not in guard-consent-writes' "
        "_HOOK_SCRIPT_NAMES - a model that can edit it can neuter what it decides"
    )


def test_an_ordinary_team_script_is_still_writable():
    """The other direction. This protection must not creep across all of scripts/ - the
    build agents write tooling there all the time."""
    for name in ("ingest", "render_html", "engagement_state"):
        assert not _blocks(f"scripts/{name}.py"), name
