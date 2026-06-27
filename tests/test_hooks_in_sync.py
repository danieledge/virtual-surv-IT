"""Guard against hook-config drift between plugin mode and project mode.

The PreToolUse guards (raw-data + code-execution) are declared in TWO places by design:
- `hooks/hooks.json`     - loaded when installed as a Claude Code plugin.
- `.claude/settings.json` - loaded when the repo is opened as a project.

Both must stay byte-for-byte identical so the two defence-critical guards can't silently
diverge between the two run modes. This test fails loudly if they drift.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _pretooluse(path: Path):
    data = json.loads(path.read_text())
    hooks = data.get("hooks", data)  # settings.json nests under "hooks"; hooks.json also does
    return hooks["PreToolUse"]


def test_plugin_and_project_hooks_are_identical():
    plugin = _pretooluse(REPO / "hooks" / "hooks.json")
    project = _pretooluse(REPO / ".claude" / "settings.json")
    assert plugin == project, (
        "hooks/hooks.json and .claude/settings.json PreToolUse hooks have DRIFTED. "
        "They must stay identical (plugin mode vs project mode). Re-sync them."
    )


def test_both_guards_are_registered():
    pre = _pretooluse(REPO / "hooks" / "hooks.json")
    commands = " ".join(h["command"] for entry in pre for h in entry["hooks"])
    assert "guard-raw-data.py" in commands, "raw-data guard missing from hooks"
    assert "guard-code-execution.py" in commands, "code-execution guard missing from hooks"
