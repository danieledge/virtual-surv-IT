#!/usr/bin/env python3
"""One command, one minute, one finished deliverable, zero tokens (step 8.1, 2026-09-13).

    python scripts/try_engagement.py            # a temp project; opens the evidence room
    python scripts/try_engagement.py --dir ~/vsit-try --no-open
    python scripts/try_engagement.py --replay   # the shipped sample engagement, as it was

Creates a throwaway project, runs a complete synthetic review engagement through the team's own
state machine (init, a findings pack rendered to a review report, the summary email, the close
sequence and the mechanical Definition-of-Done gate, which renders the evidence room), and opens
the evidence room in the browser. Every step is a vendored team script; no model is called and
nothing leaves the machine. The findings are planted and say so.

`--replay` (step 8.2 / 1.7, 2026-09-14) opens the SHIPPED sample instead: a real engagement the
team ran on synthetic data, frozen under `examples/engagements/` with its state, findings pack,
summary email, START-HERE page and evidence room. It is copied into the throwaway project
unchanged and opened; nothing is regenerated and no model is called. The `/demo` Replay flavour
is this command.

If the close gate refuses (it should not; when it does, that is a real defect worth reporting)
the refusal is printed verbatim, the room is rendered anyway so there is still something to look
at, and the exit code is 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed argv, shell=False: the team's own scripts
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SLUG = "spoofing-review"
SAMPLES = REPO / "examples" / "engagements"


def shipped_samples(root: Path | None = None) -> list[Path]:
    """The frozen sample engagements, oldest name first: every directory under
    examples/engagements/ that carries an engagement-state.json."""
    base = root or SAMPLES
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if (p / "engagement-state.json").is_file())


def replay(
    project: Path, open_browser: bool = True, log=print, samples: Path | None = None
) -> tuple[int, Path | None]:
    """Copy the shipped sample engagement into `project` and open its evidence room.

    A copy, not a link, so the viewer can poke at it freely and the shipped copy stays what it
    was. Returns (exit code, room); 1 with no room when nothing is shipped or the sample has no
    evidence room, both of which are packaging defects worth reporting."""
    import shutil

    found = shipped_samples(samples)
    if not found:
        log(f"no sample engagement is shipped under {samples or SAMPLES}")
        return 1, None
    sample = found[0]
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text("# replay project (synthetic)\n", encoding="utf-8")
    pack_dir = project / "VSIT" / "engagements" / sample.name
    shutil.copytree(sample, pack_dir, dirs_exist_ok=True)
    room = next(iter(sorted(pack_dir.glob("EVIDENCE-ROOM-*.html"))), None)
    start = next(iter(sorted(pack_dir.glob("START-HERE*.md"))), None)
    log(
        f"Replay: the shipped sample engagement '{sample.name}', copied as it was, no tokens spent."
    )
    log(f"  workspace: {pack_dir}")
    if start:
        log(f"  start here: {start}")
    if room is None:
        log("  the sample ships no evidence room - a packaging defect worth reporting")
        return 1, None
    log(f"  evidence room: {room}")
    if open_browser:
        try:
            webbrowser.open(room.as_uri())
        except Exception:  # noqa: BLE001 - a browser that will not open is not a failure of the run
            log("  (could not open a browser here; open the file above by hand)")
    return 0, room


def _plugin_version() -> str:
    try:
        return json.loads(
            (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        ).get("version", "")
    except (OSError, ValueError):
        return ""


def _pack(slug: str) -> dict:
    return {
        "slug": slug,
        "kind": "review",
        "scope": "rules/spoofing.py",
        "mode": "audit",
        "verdict": "conditional",
        "title": "Spoofing detector review (synthetic, planted findings)",
        "executive_summary": (
            "A synthetic review produced by `virt-surv try` to show a finished engagement. No model "
            "was called; the two findings are planted and labelled as such."
        ),
        "tooling_coverage": (
            "Synthetic run: no analyser was executed. ruff, bandit and gitleaks would run on a real "
            "Python review; their absence here is stated, not hidden, and every finding is marked "
            "planted."
        ),
        "developer_guidance": (
            "Record the rationale and the tuning date beside every threshold (CLAUDE.md §4), and "
            "validate any path taken from the environment before opening it."
        ),
        "limitations": "Everything in this report is synthetic; it demonstrates the shape of a close, not a review of real code.",
        "findings": [
            {
                "id": "COR-1",
                "title": "Cancel-ratio threshold hard-coded without rationale or tuning date (planted)",
                "severity": "warning",
                "location": "rules/spoofing.py:1",
                "basis": "measured",
                "standard": "CLAUDE.md §4",
                "problem": "planted for the try run - the threshold has no comment recording why it is 0.8 or when it was last tuned",
                "likely_cause": "n/a (synthetic)",
                "impact": "an auditor cannot trace the alert to a decision (synthetic)",
                "fix": {
                    "diff": "n/a (synthetic)",
                    "why": "record the rationale and the tuning date beside the value",
                },
                "disposition": "open",
            },
            {
                "id": "SEC-1",
                "title": "Order feed path built from an environment variable without validation (planted)",
                "severity": "info",
                "location": "rules/spoofing.py:1",
                "basis": "inferred",
                "standard": "CWE-20",
                "problem": "planted for the try run - not a real finding",
                "likely_cause": "n/a (synthetic)",
                "impact": "n/a (synthetic)",
                "fix": {"diff": "n/a (synthetic)", "why": "n/a (synthetic)"},
                "disposition": "accepted",
            },
        ],
    }


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603
        [sys.executable, *argv], cwd=str(cwd), capture_output=True, text=True, timeout=120
    )


def run(project: Path, open_browser: bool = True, log=print) -> tuple[int, Path | None]:
    """Build and close the synthetic engagement under `project`. Returns (exit code, room)."""
    started = time.monotonic()
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text("# try project (synthetic)\n", encoding="utf-8")
    state = REPO / "scripts" / "engagement_state.py"
    pack_dir = project / "VSIT" / "engagements" / SLUG
    version = _plugin_version()
    steps: list[tuple[str, list[str]]] = [
        (
            "init",
            [
                str(state),
                "init",
                "--dir",
                str(pack_dir),
                "--title",
                "Spoofing detector review (synthetic)",
                "--slug",
                SLUG,
                "--team-version",
                f"v{version}" if version else "v0",
            ],
        ),
    ]
    failures: list[str] = []

    def step(label: str, argv: list[str], must: bool = True) -> subprocess.CompletedProcess:
        proc = _run(argv, project)
        log(f"  {'ok ' if proc.returncode == 0 else 'ERR'} {label}")
        if proc.returncode != 0 and must:
            failures.append(f"{label}: {(proc.stderr or proc.stdout).strip()[-600:]}")
        return proc

    for label, argv in steps:
        step(label, argv)
    data = pack_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    pack_path = data / f"findings-{SLUG}.jsonl"
    pack_path.write_text(json.dumps(_pack(SLUG)) + "\n", encoding="utf-8")
    step(
        "render findings", [str(REPO / "scripts" / "render_findings.py"), str(pack_path), "--html"]
    )
    email = pack_dir / f"engagement-summary-{SLUG}.txt"
    email.write_text(
        "Hi,\n\n"
        "This is the summary of a synthetic spoofing-detector review produced by `virt-surv try`\n"
        "to show what a finished engagement looks like. No model was called and no real code\n"
        "was reviewed: the two findings are planted and labelled as such.\n\n"
        "Verdict: conditional (synthetic). Findings: 1 warning, 1 info. Footprint: 0 tokens, two\n"
        "synthetic reviewer roles (🤖 Ravi, code review; 🤖 Pip, review scoring).\n\n"
        "🤖 Morgan (PM), Virtual Surveillance IT\n",
        encoding="utf-8",
    )
    step(
        "dod --fix",
        [str(REPO / "scripts" / "check_artifacts.py"), str(pack_dir.parent), "--fix"],
        must=False,
    )
    step(
        "add-artifact review",
        [
            str(state),
            "--dir",
            str(pack_dir),
            "add-artifact",
            f"REVIEW-{SLUG}.md",
            "--title",
            "Review report (synthetic)",
            "--final",
        ],
    )
    step(
        "add-artifact email",
        [
            str(state),
            "--dir",
            str(pack_dir),
            "add-artifact",
            email.name,
            "--title",
            "Engagement summary email",
            "--final",
        ],
    )
    step("set-status closing", [str(state), "--dir", str(pack_dir), "set-status", "closing"])
    step(
        "set-team",
        [
            str(state),
            "--dir",
            str(pack_dir),
            "set-team",
            "Ravi (code-reviewer, synthetic)",
            "Pip (review-scorer, synthetic)",
        ],
    )
    step("finalise-artifacts", [str(state), "--dir", str(pack_dir), "finalise-artifacts"])
    step(
        "set-footprint",
        [str(state), "--dir", str(pack_dir), "set-footprint", "--agents", "2", "--tokens", "0"],
    )
    step(
        "set-status closed",
        [
            str(state),
            "--dir",
            str(pack_dir),
            "set-status",
            "closed",
            "--verdict",
            "Ready (synthetic)",
        ],
    )
    room = next(iter(sorted(pack_dir.glob("EVIDENCE-ROOM-*.html"))), None)
    if room is None:
        step(
            "render evidence room",
            [str(REPO / "scripts" / "render_evidence_room.py"), str(pack_dir), "--force"],
            must=False,
        )
        room = next(iter(sorted(pack_dir.glob("EVIDENCE-ROOM-*.html"))), None)
    elapsed = time.monotonic() - started
    log("")
    if failures:
        log("The close was REFUSED or a step failed; this is a real defect worth reporting:")
        for f in failures:
            log("  " + f.replace("\n", "\n  "))
    else:
        log(f"Closed: a finished synthetic engagement in {elapsed:.0f} s, no tokens spent.")
    log(f"  workspace: {pack_dir}")
    if room:
        log(f"  evidence room: {room}")
        if open_browser:
            try:
                webbrowser.open(room.as_uri())
            except Exception:  # noqa: BLE001 - a browser that will not open is not a failure of the run
                log("  (could not open a browser here; open the file above by hand)")
    else:
        log("  no evidence room was rendered")
    return (1 if failures or room is None else 0), room


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dir", type=Path, default=None, help="project directory (default: a new temp dir)"
    )
    parser.add_argument(
        "--no-open", action="store_true", help="do not open the evidence room in a browser"
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="open the shipped sample engagement (examples/engagements/) instead of building one",
    )
    args = parser.parse_args(argv)
    project = args.dir or Path(tempfile.mkdtemp(prefix="virt-surv-try-"))
    if args.replay:
        print(f"virt-surv try --replay: opening the shipped sample engagement under {project}")
        code, _room = replay(project.resolve(), open_browser=not args.no_open)
        return code
    print(f"virt-surv try: building a synthetic review engagement under {project}")
    code, _room = run(project.resolve(), open_browser=not args.no_open)
    return code


if __name__ == "__main__":
    sys.exit(main())
