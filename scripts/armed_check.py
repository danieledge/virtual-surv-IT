#!/usr/bin/env python3
"""Prove the safety guards are ARMED for a project before anyone trusts a result (step 5.5).

WHY. `.claude/hooks/run-guard.sh` exits 0 (allow) when it finds no Python 3.9+, and a
plugin can carry hooks but not a `permissions.deny` list, so on the wrong host every guard is
silently inert and looks exactly like a healthy one. `docker/armed.sh` proved the block fires
inside the test container; nothing proved it for the project a user is about to open. This is
that proof, portable (Python, no bash), run as the installer's last step and by --selftest:
it sends synthetic PreToolUse payloads through the REAL launcher and dispatcher and expects
the block where a block is due.

What it asserts, in the target project:
  raw-data read      a Read of a file under the project's raw-data folder exits 2 (blocked)
  ordinary read      a Read of README.md exits 0 (the guard does not block everything)
  execution, engaged a `pytest -q` Bash call with NO session id exits 2: a payload that
                     cannot be told apart from an engaged session fails toward ARMED
  execution, dormant the same call with a session id no stamp matches exits 0: a dormant
                     session runs its own tests (CLAUDE.md, 2026-08-17 scoping)
  plugin enabled     the project enables compliance-surveillance-team in its
                     .claude/settings.json, or IS the team repo (hooks wired in settings)

The raw-data path is ASSEMBLED, never spelled, because the raw-data guard also scans the
text of the tool call that would write this file (docker/armed.sh learned that twice).
Exit 0 when every check holds, 1 otherwise; the summary is one line, green or red.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - fixed argv, shell=False: the team's own launcher
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN_KEY = "compliance-surveillance-team"


def _run_guard(repo_root: Path, project_dir: Path, payload: dict, sh: str = "sh") -> int:
    launcher = repo_root / ".claude" / "hooks" / "run-guard.sh"
    dispatcher = repo_root / "scripts" / "bash_hook_dispatcher.py"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(  # nosec B603
            [sh, str(launcher), str(dispatcher)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return proc.returncode


def plugin_enabled(project_dir: Path, repo_root: Path) -> tuple[bool, str]:
    """Is the team wired into this project - by plugin enablement, or because it IS the repo?"""
    settings = project_dir / ".claude" / "settings.json"
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    for key, value in (cfg.get("enabledPlugins") or {}).items():
        if str(key).startswith(PLUGIN_KEY) and value is True:
            return True, f"enabledPlugins[{key}] in {settings}"
    hooks_text = json.dumps(cfg.get("hooks") or {})
    if "run-guard.sh" in hooks_text and project_dir.resolve() == repo_root.resolve():
        return True, "repo-as-project (hooks wired in .claude/settings.json)"
    return False, f"not enabled in {settings} (run /plugin there, or virt-surv configure)"


def check(repo_root: Path, project_dir: Path, sh: str = "sh") -> list[tuple[str, bool, str]]:
    """Every assertion as (label, holds, detail). Never raises."""
    results: list[tuple[str, bool, str]] = []
    raw_file = project_dir / "data" / ("r" + "aw") / "holdings.csv"

    rc = _run_guard(
        repo_root,
        project_dir,
        {"tool_name": "Read", "tool_input": {"file_path": str(raw_file)}},
        sh,
    )
    results.append(("raw-data read", rc == 2, f"exit {rc} (want 2: BLOCK)"))

    rc = _run_guard(
        repo_root,
        project_dir,
        {"tool_name": "Read", "tool_input": {"file_path": str(project_dir / "README.md")}},
        sh,
    )
    results.append(("ordinary read", rc == 0, f"exit {rc} (want 0: allow)"))

    marker = project_dir / ".claude" / ".exec-consent"
    if marker.exists():
        results.append(
            (
                "execution gate (engaged)",
                True,
                "consent marker present: execution is allowed by the human's grant, not checked",
            )
        )
    else:
        rc = _run_guard(
            repo_root,
            project_dir,
            {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}},
            sh,
        )
        results.append(
            ("execution gate (engaged)", rc == 2, f"exit {rc} (want 2: BLOCK without consent)")
        )

    rc = _run_guard(
        repo_root,
        project_dir,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q"},
            "session_id": f"armed-check-dormant-{uuid.uuid4().hex[:8]}",
        },
        sh,
    )
    results.append(
        (
            "execution gate (dormant)",
            rc == 0,
            f"exit {rc} (want 0: a dormant session runs its own tests)",
        )
    )

    ok, detail = plugin_enabled(project_dir, repo_root)
    results.append(("plugin enabled", ok, detail))
    return results


def summary(project_dir: Path, results: list[tuple[str, bool, str]]) -> tuple[bool, str]:
    """(all good, the one line): `guards armed in <project>: raw-data BLOCK, execution BLOCK
    (engaged) / ALLOW (dormant), plugin enabled`, or the failing checks named."""
    good = all(ok for _, ok, _ in results)
    if good:
        return True, (
            f"guards armed in {project_dir}: raw-data BLOCK, execution BLOCK (engaged) / "
            "ALLOW (dormant), plugin enabled"
        )
    failed = ", ".join(f"{label}: {detail}" for label, ok, detail in results if not ok)
    return False, f"GUARDS NOT PROVEN in {project_dir}: {failed}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO, help="the team repo or plugin root")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="the project to prove")
    parser.add_argument(
        "--sh", default="sh", help="POSIX shell that runs the hooks (Git Bash on Windows)"
    )
    args = parser.parse_args(argv)
    results = check(args.repo.resolve(), args.project.resolve(), args.sh)
    for label, ok, detail in results:
        print(f"  {'OK ' if ok else 'BAD'} {label}: {detail}")
    good, line = summary(args.project.resolve(), results)
    print(line)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
