#!/usr/bin/env python3
"""Automated live-/engage eval driver: run a full engagement cycle headlessly and score it.

The eval harness (evals/README.md) has two execution paths:

  * `/run-evals` - the subagent slice: inlines a workflow into a blind subagent brief.
    Cheap, but it cannot exercise Morgan's ORCHESTRATION (banner, gates, right-sizing,
    lifecycle discipline, close artifacts) because a subagent has no user channel and
    cannot run slash commands. The 0.27.0 baseline records exactly this gap.
  * THIS driver - the orchestration slice: launches a REAL `/engage` session headlessly
    via the Claude Agent SDK, with an LLM user-sim playing the stakeholder. The sim
    answers every AskUserQuestion gate in persona (intercepted through the SDK's
    `can_use_tool` callback), so the whole cycle runs: intake gates, brief, delivery,
    DoD gate, close artifacts, summary email.

Each case runs in a throwaway SANDBOX copy of the repo (evals/ excluded, so the
ground truth is structurally unreachable by the session-under-test), with the project
guard hooks live - they are part of the behaviour under test. Blindness boundaries:

  session-under-test  sees scenario.md only (+ the sandboxed repo)
  user-sim            sees the case's driver.md persona (or evals/driver-default.md)
                      and the question JSON - never expected.yaml / notes.md
  normalizer          sees the transcript + artifact listing only
  judge               sees the rubric + transcript - never expected.yaml
  this process        reads expected.yaml only AFTER the run, to score it

Execution consent inside the sandbox is a HUMAN-side act performed by this harness
process (it creates `<sandbox>/.claude/.exec-consent` when the sim grants intent),
mirroring the ADR-002 model: the session's own writes to the marker stay blocked by
guard-consent-writes.py; the driver is the human it stands in for.

Scoring reuses the existing deterministic scorer (scripts.eval_score) on findings
assembled from (a) a code-level artifact probe of the sandbox and (b) an
uncontaminated normalizer pass over the transcript, then adds the rubric LLM-judge.

Usage (needs the repo venv - the Agent SDK is a dev dependency, not vendored):
    . .venv/bin/activate
    python -m scripts.eval_engage --list
    python -m scripts.eval_engage --case process-right-sizing
    python -m scripts.eval_engage --all-engage --max-budget 15
    python -m scripts.eval_engage --record evals/runs   # backfill evals/results.jsonl only
Each full lifecycle run spends real tokens (it is a live engagement) - run at
milestones, not per commit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import ntpath
import os
import re
import shutil

# Sandbox setup (rsync, git init) - every call is fixed argv, no shell, local eval harness.
import subprocess  # nosec B404
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from scripts.eval_score import TripwireContext, scan_tripwires, score, tripwires_off


def _vsit_paths():
    """The layout resolver (VSIT migration), imported lazily.

    eval_engage builds a SANDBOX that a real engagement then runs inside, so the directory
    it creates must be the one the engagement itself will resolve to. That is why this file
    was held back from the mechanical stage-1 pass: getting it wrong yields a green suite
    and broken evals."""
    import sys as _sys

    _here = Path(__file__).resolve().parent
    for _candidate in (_here, _here.parent, _here.parent / "scripts"):
        if (_candidate / "vsit_paths.py").is_file():
            if str(_candidate) not in _sys.path:
                _sys.path.insert(0, str(_candidate))
            break
    import vsit_paths

    return vsit_paths


REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = REPO_ROOT / "evals" / "cases"
RUNS_ROOT = REPO_ROOT / "evals" / "runs"
RUBRICS_ROOT = REPO_ROOT / "evals" / "rubrics"
DEFAULT_PERSONA = REPO_ROOT / "evals" / "driver-default.md"
# Tracked, append-only numeric record (evals/runs/ is git-ignored and pruned by the
# retention rule, so before this file the only surviving numbers were prose baselines).
RESULTS_FILE = REPO_ROOT / "evals" / "results.jsonl"

# Never copied into the sandbox. `evals/` is the load-bearing one: it holds the ground
# truth, and excluding it makes blindness structural rather than willpower.
GUARD_DAEMON_STATE = (
    ".claude/.guard-daemon-port",
    ".claude/.guard-daemon-start-backoff",
    ".claude/.guard-coldstart-ms",
    ".claude/.guard-lock",
)

SANDBOX_EXCLUDES = (
    ".git",
    ".venv",
    "artifacts",
    "evals",
    "__pycache__",
    ".pytest_cache",
    ".claude/.exec-consent",
    # The guard daemon's per-project runtime state (2026-09-13, process-blocked-not-done
    # rerun): a sandbox that inherits this checkout's port file and token sends its first
    # hook calls to THIS checkout's daemon, which serves this project and answers the
    # sandbox with nothing - every repo-mode /engage opened without the probe injection.
    # The interpreter cache is deliberately kept (it is what makes the prefetch fire).
    *GUARD_DAEMON_STATE,
    "node_modules",
    # 2026-07-30 retention audit: the two README PNGs are 5.4M per kept sandbox (plus a
    # second copy in the sandbox's own .git) and no eval case reads them - excluding the
    # assets cuts a typical kept run by roughly two thirds.
    "docs/assets",
)

# The sandbox session must stay hermetic: nothing it does may leave the box.
_NET_BASH_RE = re.compile(
    r"\b(git\s+push|git\s+fetch|git\s+pull|git\s+clone|git\s+remote\s+update|git\s+ls-remote"
    r"|curl|wget|ssh|scp|sftp|rsync\s+[^|]*::|nc\b|ncat|netcat|telnet"
    r"|gh\s|pip[23]?\s+(?:install|download)|npm\s+(?:install|ci|publish)|pnpm\s+(?:install|add)"
    r"|yarn\s+(?:add|install)|uv\s+(?:pip|add)|poetry\s+(?:add|install)|cargo\s+(?:add|install)"
    r"|apt(?:-get)?\s+install|brew\s+install"
    # Interpreter one-liners are the obvious way around a verb list; catch the network modules
    # rather than trying to enumerate every spelling of an interpreter invocation.
    r"|urllib|requests\.(?:get|post)|httpx|socket\.(?:socket|create_connection)|aiohttp"
    r"|http\.client|fetch\(|XMLHttpRequest"
    r")\b"
)
_NET_TOOLS = {"WebFetch", "WebSearch"}

_TRANSCRIPT_CAP = 80_000  # chars of transcript handed to the normalizer / judge


def _cap_transcript(transcript: str, cap: int = _TRANSCRIPT_CAP) -> str:
    """Keep BOTH ends of a long transcript, not just the tail.

    A pure tail slice silently dropped the run's OPENING on long engagements, which is exactly
    where the banner, the intake gate, the data attestation and the right-sizing statement live.
    Several rubric dimensions score those, so a long run could be marked down for behaviour that
    happened and was then truncated out of the judged slice (review 2026-08-01). Head and tail
    are kept with the omission stated in-band so the judge knows the middle is missing rather
    than inferring the work was never done.
    """
    if len(transcript) <= cap:
        return transcript
    head = cap // 3
    tail = cap - head
    dropped = len(transcript) - cap
    return (
        transcript[:head]
        + f"\n\n[... {dropped} chars of the middle omitted to fit the judged slice ...]\n\n"
        + transcript[-tail:]
    )


# Subagent output is the WORK; the PM's own messages are the narration of it. Capturing
# only the PM (parent_tool_use_id is None) meant the normalizer and judge scored an
# engagement from its press release (2026-08-01 eval-harness audit). Subagent text is now
# retained, tagged so attribution stays clear, and capped per block so one verbose
# specialist cannot push the rest of the run out of the tail-sliced _TRANSCRIPT_CAP:
# 3_000 chars ~ 750 tokens is a specialist's findings summary, not its full working.
# Tuning date 2026-08-01. `--exclude-subagent-output` restores the old PM-only view.
_SUBAGENT_TEXT_CAP = 3_000

# What the normalizer and judge get to SEE of the deliverables. The listing used to be
# PATHS ONLY, so "evidence basis", "traceability" and "clarity" were scored from filenames
# plus the PM's narration - an eloquently-described empty document scored like a real one.
# Bodies are now inlined, truncated in-band:
#   * 6_000 chars/file (~1.5k tokens) covers a whole START-HERE or summary email, and the
#     head of a spec/review - structure, headings, evidence tags, sign-off: what the
#     rubrics actually score;
#   * 60_000 chars total (~15k tokens) keeps the added prompt weight below the 80k-char
#     transcript slice even for artifact-heavy engagements.
# Tuning date 2026-08-01; revisit if a rubric starts scoring deep body content.
_ARTIFACT_BODY_CAP = 6_000
_ARTIFACT_LISTING_CAP = 60_000
_ARTIFACT_BODY_SUFFIXES = (".md", ".txt")

# A healthy headless session emits its first (System) message within seconds of spawn;
# two minutes of total silence means it will never speak (see the watchdog in run_case).
STARTUP_TIMEOUT_S = 120

# Per-case wall clock. One global number cannot fit this corpus: the short review cases finish
# in 3-8 minutes while a full lifecycle engagement legitimately runs past 110, so a budget that
# is generous for the former kills the latter mid-close. Measured over the 2026-07-25..30
# history, four SUCCESSFUL runs exceeded the old 2400s default (the longest at 6763s), and five
# of the thirteen runs that produced no gradeable output were timeouts with no API error in the
# transcript - a budget set below what the case needs, not instability.
#
# A case declares `timeout_s:` in its manifest when it needs more than the default; an explicit
# --timeout on the command line still wins over both, so a quick smoke run can cap everything.
DEFAULT_TIMEOUT_S = 2400


def _session_env() -> dict[str, str]:
    """Env overrides for every spawned CLI, fixing two observed fidelity breaks.

    - An ANTHROPIC_API_KEY present in the host environment takes auth precedence inside
      the spawned CLI over the login interactive Claude Code uses, changing how runs are
      authenticated and billed. Blank it so headless sessions authenticate exactly like
      interactive Claude Code; empty reads as unset in the CLI's auth logic.
    - The runner itself runs from the repo venv (for the SDK), so the inherited PATH
      resolves `python3` to `.venv/bin/python3` INSIDE the session - which lacks the
      user-site Markdown/bleach, so render_html "couldn't" run (observed twice). Strip
      the venv so the session sees the same interpreter an interactive engagement does.
    """
    env = {"ANTHROPIC_API_KEY": ""}
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        env["VIRTUAL_ENV"] = ""
        env["PATH"] = os.pathsep.join(
            p for p in os.environ.get("PATH", "").split(os.pathsep) if p and not p.startswith(venv)
        )
    return env


# --------------------------------------------------------------------------- helpers
def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _extract_json(text: str) -> dict:
    """Parse the first JSON object out of an LLM reply (tolerates code fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj


def _load_case(case_id: str) -> dict:
    case_dir = CASES_ROOT / case_id
    manifest = yaml.safe_load((case_dir / "expected.yaml").read_text(encoding="utf-8"))
    manifest["_dir"] = case_dir
    return manifest


def engage_cases() -> list[str]:
    """All golden cases whose workflow is the live orchestrator."""
    out = []
    for d in sorted(p for p in CASES_ROOT.iterdir() if p.is_dir()):
        try:
            wf = yaml.safe_load((d / "expected.yaml").read_text(encoding="utf-8")).get("workflow")
        except FileNotFoundError:
            continue
        if wf in ("/engage", "/engage-light"):
            out.append(d.name)
    return out


def case_mode(manifest: dict, force_plugin: bool = False) -> str:
    """How a case is laid out: "repo" (a sandbox copy of this repo IS the project) or "plugin".

    `mode: plugin` in expected.yaml declares it per case; `--plugin-mode` forces it for every
    case in the run. The CLI wins, on the same reasoning as --timeout: an explicit flag is a
    human overriding the corpus, and forcing plugin mode across the set is how a release check
    asks "does the whole corpus still pass the way people actually install this?".
    """
    if force_plugin:
        return "plugin"
    declared = str(manifest.get("mode") or "repo").strip().lower()
    return "plugin" if declared == "plugin" else "repo"


def overlay_fixtures(fixtures: Path, dest: Path) -> None:
    """Copy a case's fixtures/ tree over `dest`. Portable (no rsync - the Windows VM has none)."""
    if not fixtures.is_dir():
        return
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixtures, dest, symlinks=False, dirs_exist_ok=True)


def case_workflow(case_id: str) -> str:
    """The live-orchestrator command a case declares (default /engage)."""
    try:
        wf = yaml.safe_load(
            (CASES_ROOT / case_id / "expected.yaml").read_text(encoding="utf-8")
        ).get("workflow")
    except FileNotFoundError:
        return "/engage"
    return wf if wf in ("/engage", "/engage-light") else "/engage"


def _claude_cfg_path() -> Path:
    return Path.home() / ".claude.json"


def ensure_workspace_trust(path: Path, configs: list[Path] | None = None) -> None:
    """Pre-accept the trust dialog for a sandbox path (headless runs cannot click it).

    Without trust, project settings are IGNORED - .claude skills would not load (no
    /engage) and, worse, the guard hooks under test would be silently disarmed. This is
    the remedy the CLI itself prints. Reverted by drop_workspace_trust() after the run.

    `configs` (2026-09-13, plugin mode): the config files to stamp. Plugin mode passes the
    THROWAWAY home's, so a plugin-mode run never writes to the developer's real ~/.claude.json
    at all - and therefore never leaves a stale trust entry in it either.
    """
    for cfg in configs or [_claude_cfg_path()]:
        data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.is_file() else {}
        data.setdefault("projects", {}).setdefault(str(path), {})["hasTrustDialogAccepted"] = True
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def drop_workspace_trust(path: Path, configs: list[Path] | None = None) -> None:
    for cfg in configs or [_claude_cfg_path()]:
        if not cfg.is_file():
            continue
        data = json.loads(cfg.read_text(encoding="utf-8"))
        if data.get("projects", {}).pop(str(path), None) is not None:
            cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_sandbox(dest: Path) -> None:
    """Throwaway repo copy: guard hooks live, ground truth absent, git baseline committed."""
    args = ["rsync", "-a", "--delete"]
    for ex in SANDBOX_EXCLUDES:
        args += ["--exclude", ex]
    args += [f"{REPO_ROOT}/", f"{dest}/"]
    # Fixed argv, no shell.
    subprocess.run(args, check=True, capture_output=True)  # nosec B603
    (dest / "data" / "raw").mkdir(parents=True, exist_ok=True)
    _vsit_paths().engagements_dir(dest).mkdir(parents=True, exist_ok=True)
    env_git = [
        "git",
        "-C",
        str(dest),
        "-c",
        "user.email=eval@local",
        "-c",
        "user.name=eval-harness",
    ]
    subprocess.run([*env_git[:3], "init", "-q"], check=True, capture_output=True)  # nosec B603
    subprocess.run([*env_git, "add", "-A"], check=True, capture_output=True)  # nosec B603
    subprocess.run(  # nosec B603
        [*env_git, "commit", "-qm", "eval sandbox baseline"], check=True, capture_output=True
    )


# Never copied into a --target-path sandbox: source control internals (this harness never
# reads the target's own history), and node_modules specifically because it's typically both
# huge and gitignored by the target project itself - excluding it here just saves the rsync
# the trouble, it wouldn't have been used either way.
_TARGET_EXCLUDES = (".git", "node_modules", "__pycache__", ".venv", "venv", *GUARD_DAEMON_STATE)


def build_target_sandbox(source: Path, dest: Path, team_preferences: dict) -> None:
    """Disposable copy of an ARBITRARY external directory (--target-path mode) - never the
    live directory itself. Pre-seeds .claude/team-preferences.json with the given dict so the
    session opens already configured, rather than relying on the conversational offer-to-set
    flow. No git init here (unlike build_sandbox): the target's own history, if any, is not
    this harness's concern, and creating one would misrepresent a foreign project's provenance."""
    args = ["rsync", "-a"]
    for ex in _TARGET_EXCLUDES:
        args += ["--exclude", ex]
    args += [f"{source}/", f"{dest}/"]
    subprocess.run(args, check=True, capture_output=True)  # nosec B603 - fixed argv, no shell
    claude_dir = dest / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "team-preferences.json").write_text(
        json.dumps(team_preferences, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- plugin mode
#
# WHY (2026-09-13, owner request). Every case above runs REPO-AS-PROJECT: the sandbox is a copy
# of this repo, so the plugin root and the project root are the same directory and the hooks
# come from the repo's own .claude/settings.json. That is not how anyone installs this. The
# default install is a MARKETPLACE install: a cache copy under the user's config home, a client
# project that is not the plugin repo, hooks wired through the plugin's own hooks/hooks.json
# and ${CLAUDE_PLUGIN_ROOT}. A day of live reports from the owner's corporate Windows laptop
# found five defects, and every one of them lived in that gap.
#
# So this builds the default install's shape on disk, in a throwaway HOME:
#
#   <run>/plugin/
#     home/                                     HOME + USERPROFILE for the session
#       .claude.json                            workspace trust (never the real one)
#       .claude/                                CLAUDE_CONFIG_DIR
#         plugins/installed_plugins.json        the v2 registry, one local-scope entry
#         plugins/known_marketplaces.json       the marketplace, sourced from the copy below
#         plugins/marketplaces/<marketplace>/   the "checked-out" marketplace: a repo copy
#         plugins/cache/<mkt>/<plugin>/<ver>/   the CACHE copy the session actually loads
#     proj/                                     the CLIENT project: cwd, empty but for fixtures
#
# Portability is a requirement, not a nicety: the owner runs this by hand on a Windows VM and
# the manual CI job runs it on Linux. So the copy is shutil.copytree (never rsync, which the
# Windows box does not have), every path is a Path, nothing is symlinked, and names Windows
# cannot create are skipped on BOTH platforms so the two layouts are identical.
PLUGIN_MARKETPLACE = "virtual-surv-it"
PLUGIN_NAME = "compliance-surveillance-team"

# Never copied into the marketplace checkout or the cache copy. `evals/` is the load-bearing
# one (same reason as SANDBOX_EXCLUDES: ground truth must be structurally unreachable), and
# `docs/assets` is 5.4M of PNGs no case reads.
PLUGIN_COPY_EXCLUDES = (
    ".git",
    ".venv",
    "venv",
    "evals",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "artifacts",
    "docs/assets",
    ".claude/.exec-consent",
)

# Names Windows cannot create. Skipped on every platform, so a layout built on Linux is the
# same layout the Windows VM gets - a copy that silently differs per OS is worse than a copy
# that is missing a file both times.
_WIN_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)]
)
_WIN_FORBIDDEN_CHARS = set('<>:"|?*')
# Classic MAX_PATH is 260; anything past this in the built layout is worth warning about
# before a person watches a Windows run fail halfway through a copy.
_WIN_PATH_WARN = 240


def windows_nameable(name: str) -> bool:
    """False for a file name Windows refuses: reserved device names, `<>:"|?*`, trailing . or space."""
    if not name or name != name.rstrip(". "):
        return False
    if _WIN_FORBIDDEN_CHARS & set(name):
        return False
    return name.split(".", 1)[0].lower() not in _WIN_RESERVED


def _copy_ignore(root: Path, excludes: tuple[str, ...]):
    """shutil.copytree ignore callable honouring both bare names and repo-relative paths."""
    rel_excludes = {e.replace("\\", "/") for e in excludes if "/" in e}
    name_excludes = {e for e in excludes if "/" not in e}

    def ignore(dirpath: str, names: list[str]) -> set[str]:
        base = Path(dirpath)
        skipped: set[str] = set()
        for name in names:
            if name in name_excludes or not windows_nameable(name):
                skipped.add(name)
                continue
            try:
                rel = (base / name).relative_to(root).as_posix()
            except ValueError:
                rel = name
            if rel in rel_excludes:
                skipped.add(name)
        return skipped

    return ignore


def _tracked_files(source: Path) -> list[str] | None:
    """The files git tracks under `source`, or None when it is not a git checkout (or git is
    unavailable). A marketplace install is a git checkout: tracked files and nothing else."""
    if not (source / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(source), "ls-files", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.split("\0") if p]


def copy_plugin_tree(source: Path, dest: Path, excludes: tuple[str, ...] = PLUGIN_COPY_EXCLUDES):
    """Portable, symlink-free copy of the plugin source. Returns the destination.

    From a git checkout only TRACKED files are copied (2026-09-13, third live run of the
    plugin-mode case): a working-tree copy carried this machine's gitignored state - the
    probe cache with its interpreter path, the guard caches, settings backups, a local audit
    workspace - into the cache copy, none of which a marketplace install ever has. The
    exclusion list still applies on top, for a source that is not a checkout."""
    tracked = _tracked_files(source)
    if tracked is None:
        shutil.copytree(
            source, dest, ignore=_copy_ignore(source, excludes), symlinks=False, dirs_exist_ok=True
        )
        return dest
    ignore = _copy_ignore(source, excludes)
    for rel in tracked:
        parts = rel.split("/")
        if any(not windows_nameable(p) for p in parts):
            continue
        if any(p in ignore(str(source / "/".join(parts[:i])), [p]) for i, p in enumerate(parts)):
            continue
        src = source / rel
        if not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target, follow_symlinks=True)
    return dest


def long_paths(root: Path, limit: int = _WIN_PATH_WARN) -> list[str]:
    """Every path under `root` longer than `limit` characters - the Windows MAX_PATH warning."""
    return sorted(str(p) for p in root.rglob("*") if len(str(p)) > limit)


def long_path_note(root: Path, limit: int = _WIN_PATH_WARN) -> str:
    """One line about MAX_PATH headroom in a built layout, or "" when there is nothing to say.

    Deliberately one line with the WORST case in it, not a list. The classic Windows limit is
    260 characters and the layout is deep by construction (config home -> plugins -> cache ->
    marketplace -> plugin -> version -> the repo tree), so the actionable number is how long
    the longest path got and where the checkout would have to live to stay under it.
    """
    over = long_paths(root, limit)
    if not over:
        return ""
    worst = max(over, key=len)
    return (
        f"MAX_PATH note: {len(over)} path(s) exceed {limit} chars, longest {len(worst)} "
        f"({worst}). Only matters on Windows without long paths enabled - keep the checkout "
        "shallow there (C:\\dev\\vsit) or turn LongPathsEnabled on."
    )


@dataclass
class PluginLayout:
    """Where everything in a plugin-mode run lives. Paths only - no behaviour of its own."""

    root: Path
    home: Path
    config_dir: Path
    marketplace_dir: Path
    cache_dir: Path
    project: Path
    version: str
    marketplace: str = PLUGIN_MARKETPLACE
    plugin: str = PLUGIN_NAME

    @property
    def registry_file(self) -> Path:
        return self.config_dir / "plugins" / "installed_plugins.json"

    @property
    def marketplaces_file(self) -> Path:
        return self.config_dir / "plugins" / "known_marketplaces.json"

    @property
    def claude_json_files(self) -> list[Path]:
        # Written in both places deliberately: `~/.claude.json` is where the CLI keeps
        # per-project trust with a default config home, and a CLAUDE_CONFIG_DIR install keeps
        # it inside that directory. Writing both costs a few hundred bytes and removes the
        # need to guess which one this CLI build reads.
        return [self.home / ".claude.json", self.config_dir / ".claude.json"]

    def session_env(self) -> dict[str, str]:
        """The env that makes the session use the throwaway home and nothing else.

        HOME and USERPROFILE together, because a Windows CLI reads USERPROFILE while anything
        POSIX-shaped in the same session (Git Bash, the guard's `sh` wrapper) reads HOME.
        HOMEDRIVE/HOMEPATH follow on Windows for the same reason - a shell that expands `~`
        from those would otherwise resolve it to the real profile.
        """
        env = {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.config_dir),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
        }
        # ntpath.splitdrive, not os.path.splitdrive: the drive letter has to be recognised by
        # the SHAPE of the path, not by the platform the harness happens to be running on -
        # otherwise a layout built for a Windows path never gets HOMEDRIVE/HOMEPATH, and a
        # POSIX path is unaffected either way (ntpath finds no drive in "/home/x").
        drive, tail = ntpath.splitdrive(str(self.home))
        if drive:
            env["HOMEDRIVE"] = drive
            env["HOMEPATH"] = tail
        return env


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_plugin_layout(
    dest: Path,
    source_root: Path = REPO_ROOT,
    version: str | None = None,
    probe_cache: bool = False,
) -> PluginLayout:
    """Lay out a default marketplace install in a throwaway HOME, and return where it went.

    `probe_cache=True` pre-writes the VSIT/local/engage-probe.json that `virt-surv go` writes,
    so the open takes the corp fast path; the default is the SLOW path (nothing pre-written),
    because that is what a first `/engage` in a fresh client project actually does.
    """
    version = version or _plugin_version(source_root)
    home = dest / "home"
    config_dir = home / ".claude"
    marketplace_dir = config_dir / "plugins" / "marketplaces" / PLUGIN_MARKETPLACE
    cache_dir = config_dir / "plugins" / "cache" / PLUGIN_MARKETPLACE / PLUGIN_NAME / version
    project = dest / "proj"
    layout = PluginLayout(
        root=dest,
        home=home,
        config_dir=config_dir,
        marketplace_dir=marketplace_dir,
        cache_dir=cache_dir,
        project=project,
        version=version,
    )

    marketplace_dir.parent.mkdir(parents=True, exist_ok=True)
    copy_plugin_tree(source_root, marketplace_dir)
    # The cache copy is made FROM the marketplace checkout, which is the order the real
    # install works in - so a file the marketplace copy dropped cannot reappear in the cache.
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    copy_plugin_tree(marketplace_dir, cache_dir, excludes=())
    project.mkdir(parents=True, exist_ok=True)
    # The guard's interpreter cache is warmed the way `virt-surv go` warms it before EVERY
    # session (first live run of this case, 2026-09-13): the UserPromptSubmit prefetch hook
    # only injects the probe once that cache exists, so a layout without it produced a
    # correct-by-design silent open and the missing-injection tripwire fired on nothing.
    # A default install always goes through `go`, which is why the cache is part of the
    # layout and not a variant.
    warm_guard_interpreter(layout)

    stamp = _iso_now()
    layout.registry_file.parent.mkdir(parents=True, exist_ok=True)
    layout.registry_file.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    f"{PLUGIN_NAME}@{PLUGIN_MARKETPLACE}": [
                        {
                            # "local" (project-scoped), the shape `/plugin install` writes
                            # for a per-project install: it carries projectPath as well as
                            # installPath, and the client project is what it points at.
                            "scope": "local",
                            "projectPath": str(project),
                            "installPath": str(cache_dir),
                            "version": version,
                            "installedAt": stamp,
                            "lastUpdated": stamp,
                        }
                    ]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    layout.marketplaces_file.write_text(
        json.dumps(
            {
                PLUGIN_MARKETPLACE: {
                    # A directory source, not github/git: the marketplace here IS the sandbox
                    # copy of this repo, and a run that reached the network would not be
                    # testing the copy on disk.
                    "source": {"source": "directory", "path": str(marketplace_dir)},
                    "installLocation": str(marketplace_dir),
                    "lastUpdated": stamp,
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if probe_cache:
        write_probe_cache(layout)
    return layout


def session_interpreter() -> str:
    """The interpreter the SESSION will see, not the one this driver runs on.

    The cached probe report is served to the session verbatim, so writing `sys.executable` here
    would hand it the repo venv - the exact thing _session_env() strips from PATH, and for the
    same reason (the venv has no user-site Markdown/bleach, so render_html "could not" run,
    observed twice). Resolve the name over the same venv-less PATH the session gets.
    """
    venv = os.environ.get("VIRTUAL_ENV") or ""
    path = os.pathsep.join(
        p
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p and not (venv and p.startswith(venv))
    )
    for name in ("python3", "python", "py"):
        hit = shutil.which(name, path=path)
        if hit:
            return Path(hit).as_posix()
    return Path(sys.executable).as_posix()


def warm_guard_interpreter(layout: PluginLayout) -> Path:
    """Seed the client project's guard-interpreter cache with this interpreter, exactly as
    virt_team_launcher._prewarm_guard_interpreter does at `go`: the prefetch hook reads it
    to run the probe out of process, and stays silent without it."""
    cache = _vsit_paths().local_file("guard_interpreter", layout.project)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(neutral_interpreter(layout).as_posix() + "\n", encoding="utf-8")
    return cache


def warm_sandbox_interpreter(sandbox: Path, shim_home: Path) -> Path:
    """Repo-mode twin of warm_guard_interpreter: the sandbox is both project and plugin, and
    the shim lives beside it rather than in a throwaway home."""
    cache = _vsit_paths().local_file("guard_interpreter", sandbox)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(_shim_interpreter(shim_home).as_posix() + "\n", encoding="utf-8")
    return cache


def neutral_interpreter(layout: PluginLayout) -> Path:
    """An interpreter path that names nothing about this machine's checkout.

    First live run of the plugin-mode case (2026-09-13): the cache carried the dev venv's
    python, `<dev checkout>/.venv/bin/python`, the probe printed it on its PYTHON= line, and
    the session's first command was `cd <dev checkout>` to look for the team's docs and the
    user's file there. A real install's interpreter is a system Python; nothing in its path
    points at a checkout. On POSIX a symlink in the throwaway home's own bin stands in for
    it; on Windows a symlink needs a privilege the VM may not grant and a copied python.exe
    does not run without its DLLs, so sys.executable stays (it is a system install there).
    """
    return _shim_interpreter(layout.home)


def _shim_interpreter(home: Path) -> Path:
    if os.name == "nt":
        return Path(sys.executable)
    shim_dir = home / ".local" / "bin"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "python3"
    try:
        if shim.is_symlink() or shim.exists():
            shim.unlink()
        shim.symlink_to(Path(sys.executable).resolve())
        return shim
    except OSError:
        return Path(sys.executable)


def write_probe_cache(layout: PluginLayout) -> Path:
    """Pre-write the probe cache `virt-surv go` leaves behind (the corp fast-path variant).

    Same keys the launcher's _write_probe_cache writes, so the prefetch hook's freshness
    checks (TTL, prefs mtime, git identity, plugin version) all pass and the open serves the
    cached report instead of computing one. A non-git client project stamps empty git
    identity, which is exactly what the hook compares against for such a project.
    """
    out = _vsit_paths().local_file("engage_probe", layout.project)
    out.parent.mkdir(parents=True, exist_ok=True)
    prefs = _vsit_paths().preferences_file(layout.project)
    payload = {
        "computed_at_epoch": int(time.time()),
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "plugin_version": layout.version,
        "prefs_mtime": int(prefs.stat().st_mtime) if prefs.is_file() else 0,
        "git_branch": "",
        "git_head": "",
        "interpreter": session_interpreter(),
        "report": (
            f"PLUGIN_ROOT={layout.cache_dir.as_posix()}\n"
            f"PROJECT_DIR={layout.project.as_posix()}\n"
            "BRANCH=\nPLUGIN_VERSION=" + layout.version + "\n"
            "pre-computed by the eval harness standing in for `virt-surv go`\n"
        ),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


# Only these keys are ever read out of the real config, and only to let the throwaway home
# authenticate the same way an interactive session does. Nothing is ever written back to the
# real home, and no other key crosses over: a plugin-mode run must not inherit the developer's
# projects, trust decisions, plugin registry or preferences, because inheriting them is what
# would hide the very defects this mode exists to find.
_AUTH_KEYS = ("oauthAccount", "userID", "hasCompletedOnboarding", "firstStartTime")
_AUTH_FILES = (".credentials.json",)


def seed_session_auth(
    layout: PluginLayout,
    real_config_dir: Path | None = None,
    real_claude_json: Path | None = None,
) -> list[str]:
    """Copy ONLY the credential material into the throwaway home. Returns what was seeded."""
    real_config_dir = real_config_dir or (Path.home() / ".claude")
    real_claude_json = real_claude_json or _claude_cfg_path()
    seeded: list[str] = []
    for name in _AUTH_FILES:
        src = real_config_dir / name
        if src.is_file():
            shutil.copy2(src, layout.config_dir / name)
            seeded.append(name)
    carried: dict[str, Any] = {}
    if real_claude_json.is_file():
        try:
            data = json.loads(real_claude_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        carried = {k: data[k] for k in _AUTH_KEYS if k in data}
    if carried:
        for cfg in layout.claude_json_files:
            existing = {}
            if cfg.is_file():
                try:
                    existing = json.loads(cfg.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
            existing.update(carried)
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        seeded += sorted(carried)
    return seeded


def _bundled_cli(windows: bool) -> str | None:
    """The CLI shipped inside the installed SDK, if there is one (its first search step)."""
    try:
        import claude_agent_sdk as _sdk
    except ImportError:
        return None
    bundled = Path(_sdk.__file__).parent / "_bundled" / ("claude.exe" if windows else "claude")
    return str(bundled) if bundled.is_file() else None


def resolve_cli_path(windows: bool | None = None) -> str:
    """The `claude` executable the Agent SDK would spawn, resolved the same way it does.

    Mirrors claude_agent_sdk/_internal/transport/subprocess_cli.py::_find_cli (read
    2026-09-13): bundled first, then PATH, then a per-platform list of install locations. The
    Windows branch matters - `shutil.which("claude")` there can hand back npm's `claude.cmd`
    shim, which CreateProcess refuses to run, so a native `claude.exe` is preferred and the
    POSIX-shaped fallbacks are not probed at all. Used for --dry-run only: the real launch
    goes through the SDK, which does its own resolution.

    `windows` is a parameter rather than a read of os.name so the branch is testable without
    monkeypatching the os module out from under pathlib.
    """
    if windows is None:
        windows = os.name == "nt" or sys.platform.startswith("win")
    bundled = _bundled_cli(windows)
    if bundled:
        return bundled
    hit = shutil.which("claude")
    if hit and not windows:
        return hit
    if windows:
        exe = shutil.which("claude.exe")
        if exe:
            return exe
        native = Path.home() / ".local" / "bin" / "claude.exe"
        if native.is_file():
            return str(native)
        return hit or "claude"
    for candidate in (
        Path.home() / ".npm-global/bin/claude",
        Path("/usr/local/bin/claude"),
        Path.home() / ".local/bin/claude",
        Path.home() / "node_modules/.bin/claude",
        Path.home() / ".yarn/bin/claude",
        Path.home() / ".claude/local/claude",
    ):
        if candidate.is_file():
            return str(candidate)
    return "claude"


def launch_command(
    cwd: Path,
    plugin_root: Path | None,
    team_model: str = "opus",
    cli: str | None = None,
    windows: bool | None = None,
) -> list[str]:
    """The argv the SDK builds for a session, for --dry-run to print.

    `--plugin-dir` is the exact option (claude --help: "Load a plugin from a directory or .zip
    for this session only"), and it is what the SDK emits for
    `plugins=[{"type": "local", "path": ...}]` - subprocess_cli.py lines 602-608. Everything
    else here is the flag the corresponding ClaudeAgentOptions field produces.
    """
    cmd = [
        cli or resolve_cli_path(windows),
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        team_model,
        "--permission-mode",
        "default",
        "--setting-sources=project",
        "--include-hook-events",
    ]
    if plugin_root is not None:
        cmd += ["--plugin-dir", str(plugin_root)]
    cmd += ["--add-dir", str(cwd)]
    return cmd


def describe_dry_run(
    case_id: str,
    cwd: Path,
    plugin_root: Path | None,
    env: dict[str, str],
    workflow_cmd: str,
    team_model: str,
    extra_notes: list[str] | None = None,
) -> str:
    """The human-readable dry-run report: layout, env overrides, and the launch command.

    Exists so the owner can check a plugin-mode layout on the Windows VM without spending a
    live session on it - the copy, the registry JSON and the resolved CLI path are exactly
    what a real run would use.
    """
    lines = [
        f"# dry run: {case_id}",
        f"cwd (the project the session opens in): {cwd}",
        f"plugin root (--plugin-dir):             {plugin_root or '(none: repo-as-project mode)'}",
        f"front-door command:                     {workflow_cmd}",
        f"orchestrator model:                     {team_model}",
        "",
        "## env overrides for the spawned CLI",
    ]
    lines += [f"  {k}={v}" for k, v in sorted(env.items())]
    lines += [
        "",
        "## launch command (the SDK builds this argv; session flags it adds are omitted)",
        "  " + subprocess.list2cmdline(launch_command(cwd, plugin_root, team_model)),
    ]
    if extra_notes:
        lines += ["", "## notes", *(f"  {note}" for note in extra_notes)]
    lines += ["", "Nothing was launched. Drop --dry-run to run it for real."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- LLM calls
async def _one_shot(prompt: str, model: str) -> str:
    """A clean, tool-less, settings-less single completion via the SDK (CLI auth)."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    options = ClaudeAgentOptions(
        setting_sources=[],
        allowed_tools=[],
        max_turns=4,  # 1 flags the single reply as error_max_turns; 2 still flaked on an
        #               empty first turn (observed live) - give tool-less calls headroom
        model=model,
        cwd=str(RUNS_ROOT),
        env=_session_env(),
    )
    chunks: list[str] = []
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                chunks += [b.text for b in message.content if isinstance(b, TextBlock)]
    except Exception:
        if not chunks:  # text already streamed is still usable (e.g. a late cap error)
            raise
    return "".join(chunks)


_SIM_RULES = """
You are role-playing the HUMAN STAKEHOLDER in a delivery session run by an AI project team.
Stay in persona per the brief below. The team's PM has just asked you a set of menu
questions (JSON at the end: each has `question`, optional `header`, `options` with `label`
and `description`, and `multiSelect`).

Reply with ONLY a JSON object, no prose:
  {"answers": {"<exact question text>": "<answer>"}}

Rules:
- Answer EVERY question in the JSON, keyed by its exact `question` string.
- Prefer an option `label` verbatim. multiSelect true -> comma-separated labels.
- If an option is marked "(Recommended)" and the persona has no contrary preference, take it.
- Free-text is allowed where no option fits: keep it to one short sentence, in persona.
- Never mention that you are simulated, never talk about evaluations or tests.
"""


@dataclass
class SimTranscript:
    exchanges: list[dict] = field(default_factory=list)
    consent_granted: bool = False


async def answer_questions(
    questions: list[dict], persona: str, model: str, sandbox: Path, sim_log: SimTranscript
) -> dict[str, str]:
    prompt = f"{_SIM_RULES}\n## Persona brief\n{persona}\n\n## Questions JSON\n{json.dumps(questions, indent=2)}"
    reply = await _one_shot(prompt, model)
    try:
        answers = {str(k): _flatten_answer(v) for k, v in _extract_json(reply)["answers"].items()}
    except (ValueError, KeyError) as exc:
        print(f"    [sim] unparseable reply ({exc}); defaulting to first options", file=sys.stderr)
        answers = {}
    for q in questions:
        q_text = q.get("question", "")
        fell_back = False
        if q_text not in answers or not answers[q_text]:
            opts = q.get("options") or []
            answers[q_text] = opts[0]["label"] if opts else "Proceed"
            fell_back = True
        sim_log.exchanges.append(
            {"question": q_text, "header": q.get("header"), "answer": answers[q_text]}
        )
        # Never let a FALLBACK grant execution consent. When the simulator's reply is
        # unparseable we take the first option, which may happen to read "Yes, run it" - so an
        # SDK hiccup, not the persona's intent, would open the §7 gate. Declining on fallback is
        # the fail-safe direction: a withheld consent takes the documented static-only path,
        # whereas a spurious grant silently changes what the run is allowed to do.
        if fell_back:
            sim_log.exchanges[-1]["answer_source"] = "harness-fallback"
        else:
            _maybe_grant_consent(q, answers[q_text], sandbox, sim_log)
    return answers


def _flatten_answer(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _maybe_grant_consent(
    question: dict, answer: str, sandbox: Path, sim_log: SimTranscript
) -> None:
    """The human-side act the sim's 'yes' stands for: the HARNESS creates the marker.

    The session-under-test remains blocked from writing it (guard-consent-writes.py);
    this process is the human whose intent the intake question captured (ADR-002).
    """
    header = (question.get("header") or "").lower()
    text = (question.get("question") or "").lower()
    if not (header.startswith("exec") or "execution" in text or "consent" in text):
        return
    if answer.lower().startswith(("yes", "grant", "consent")):
        marker = sandbox / ".claude" / ".exec-consent"
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(
            f"granted by scripts.eval_engage (human-side driver) {_now_utc()}\n", encoding="utf-8"
        )
        sim_log.consent_granted = True


# --------------------------------------------------------------------------- session
@dataclass
class SessionCapture:
    events: list[dict] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    num_turns: int | None = None
    is_error: bool = False
    timed_out: bool = False
    error: str | None = None
    # The CLI's own stderr, line by line (2026-09-13). The SDK surfaces a dead CLI as
    # "Command failed with exit code 1 ... Check stderr output for details" and nothing else;
    # a rerun of process-blocked-not-done died that way at the spend cap and was read as a
    # crash for an hour. Written to cli-stderr.log beside the transcript.
    cli_stderr: list[str] = field(default_factory=list)
    spend_capped: bool = False
    # Per-message usage (2026-08-06, --target-path diagnostic mode): the final ResultMessage's
    # total_cost_usd/num_turns is enough for pass/fail scoring, but diagnosing WHERE token/time
    # budget goes needs per-turn granularity. One entry per AssistantMessage/ResultMessage that
    # carried a `usage` dict, in stream order - a small addition, always populated (not gated on
    # --target-path), since it costs nothing case runs don't already pay for capturing events.
    usage_series: list[dict] = field(default_factory=list)


def usage_attribution(usage_series: list[dict]) -> dict:
    """Track D of the token plan (2026-08-18): fold the per-message usage series into one
    attribution block, so a run's cost is inspectable per share instead of one opaque total.
    Main-loop vs subagent split comes from each assistant entry's `from_subagent` flag;
    per-model totals from the final result entry's `model_usage` when the SDK sent one.
    Purely arithmetic over what run_engage_session already captured - no new collection."""
    main_out = sub_out = main_msgs = sub_msgs = 0
    per_model: dict[str, dict] = {}
    final_result: dict = {}
    for entry in usage_series:
        if entry.get("type") == "assistant":
            out = int((entry.get("usage") or {}).get("output_tokens") or 0)
            if entry.get("from_subagent"):
                sub_out += out
                sub_msgs += 1
            else:
                main_out += out
                main_msgs += 1
            model = entry.get("model") or "unknown"
            slot = per_model.setdefault(model, {"messages": 0, "output_tokens": 0})
            slot["messages"] += 1
            slot["output_tokens"] += out
        elif entry.get("type") == "result":
            final_result = entry  # last result wins, same rule as cap.cost_usd
    totals = final_result.get("usage") or {}
    return {
        "total_cost_usd": final_result.get("total_cost_usd"),
        "num_turns": final_result.get("num_turns"),
        "totals": {
            "input_tokens": totals.get("input_tokens"),
            "output_tokens": totals.get("output_tokens"),
            "cache_read_input_tokens": totals.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": totals.get("cache_creation_input_tokens"),
        },
        "output_split": {
            "main_loop": {"messages": main_msgs, "output_tokens": main_out},
            "subagents": {"messages": sub_msgs, "output_tokens": sub_out},
        },
        "per_model_stream": per_model,
        "per_model_result": final_result.get("model_usage") or {},
    }


def _transcript_lines(
    message: Any,
    text_block_cls: type,
    tool_block_cls: type,
    from_subagent: bool,
    subagent_cap: int = _SUBAGENT_TEXT_CAP,
) -> list[str]:
    """Transcript lines for one AssistantMessage.

    The SDK block classes are passed in rather than imported so this stays usable (and
    testable) without the Agent SDK installed. PM text is verbatim; subagent text is
    tagged `[subagent]` and truncated to `subagent_cap` chars so one verbose specialist
    cannot crowd the rest of the run out of the tail-sliced transcript. AskUserQuestion
    tool calls are skipped - the gate exchange is appended separately, with the answer.
    """
    lines: list[str] = []
    tag = "[subagent] " if from_subagent else ""
    for block in message.content:
        if isinstance(block, text_block_cls):
            text = block.text
            if from_subagent and len(text) > subagent_cap:
                text = f"{text[:subagent_cap]}\n[... subagent output truncated at {subagent_cap} chars ...]"
            lines.append(f"\n{tag}{text}" if tag else text)
        elif isinstance(block, tool_block_cls) and block.name != "AskUserQuestion":
            hint = str(block.input.get("description") or block.input.get("subagent_type") or "")[
                :120
            ]
            lines.append(f"\n{tag}[tool] {block.name} {hint}\n")
    return lines


def event_entry(message: Any, msg_type: str) -> dict:
    """One captured event: the repr that was always kept, plus STRUCTURED tool traffic.

    WHY the structured fields (2026-09-13). The tripwires in scripts.eval_score read what the
    run DID - which path a Read errored on, what a Bash `ls` targeted, whether the
    UserPromptSubmit hook injected anything. All of that was present in the capture only as
    `repr(message)[:4000]`: truncated mid-object on a long tool input, and parseable only by
    picking a Python repr apart. Recording the fields directly makes the tripwires read data
    instead of prose, and the repr stays for everything else that was ever read out of it.
    """
    entry: dict = {"type": msg_type, "repr": repr(message)[:4000]}
    tools: list[dict] = []
    results: list[dict] = []
    content = getattr(message, "content", None) or []
    # A UserMessage's content may be a plain string; iterating that yields characters.
    blocks = [] if isinstance(content, str) else content
    # Blocks are recognised by their ATTRIBUTES, not by class name, for the same reason
    # _transcript_lines takes the SDK classes as parameters: this stays usable and testable
    # without the Agent SDK installed.
    for block in blocks:
        if hasattr(block, "tool_use_id"):
            results.append(
                {
                    "tool_use_id": getattr(block, "tool_use_id", ""),
                    "is_error": bool(getattr(block, "is_error", False)),
                    # Capped: a tool result can be a whole file, and the tripwires only ever
                    # look for an error phrase or a path near the top of one.
                    "text": json.dumps(getattr(block, "content", None), default=str)[:4000],
                }
            )
        elif hasattr(block, "name") and hasattr(block, "input"):
            tools.append(
                {
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
            )
    if tools:
        entry["tools"] = tools
    if results:
        entry["tool_results"] = results
    if msg_type == "HookEventMessage":
        data = getattr(message, "data", None) or {}
        entry["hook"] = {
            "event": getattr(message, "hook_event_name", "") or data.get("hook_event") or "",
            "subtype": getattr(message, "subtype", "") or "",
            "output": json.dumps(data, default=str)[:8000],
        }
    return entry


async def run_engage_session(
    cap: SessionCapture,
    scenario: str,
    sandbox: Path,
    persona: str,
    sim_model: str,
    max_turns: int,
    max_budget: float | None,
    sim_log: SimTranscript,
    workflow_cmd: str = "/engage",
    team_model: str = "opus",
    extra_env: dict[str, str] | None = None,
    include_subagents: bool = True,
    plugins: list[dict] | None = None,
    disallowed_tools: list[str] | None = None,
    live_dir: Path | None = None,
) -> SessionCapture:
    """`live_dir`, if given (--target-path mode only - every case run leaves this None,
    unaffected): transcript.md/events.jsonl/usage-series.jsonl are flushed to disk as the run
    progresses, not only after it finishes - a long live run against a real project needs to be
    watchable and killable mid-flight (a live corp report showed exactly the failure mode this
    guards against: a single-generation blowup that would otherwise only be discovered after
    burning the full budget/timeout waiting for a result that never usefully arrives). events.jsonl
    and usage-series.jsonl are append-only (one write per new entry, cheap); transcript.md is
    rewritten in full each flush (its content only grows by appending internally, so this stays
    O(final size), not O(n^2) over the run)."""
    events_fh = None
    usage_fh = None
    if live_dir is not None:
        live_dir.mkdir(parents=True, exist_ok=True)
        events_fh = (live_dir / "events.jsonl").open("a", encoding="utf-8")
        usage_fh = (live_dir / "usage-series.jsonl").open("a", encoding="utf-8")

    def _flush_transcript() -> None:
        if live_dir is not None:
            (live_dir / "transcript.md").write_text("".join(cap.transcript), encoding="utf-8")

    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        PermissionResultAllow,
        PermissionResultDeny,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        query,
    )

    async def can_use_tool(tool_name: str, input_data: dict, _context: Any):
        if tool_name in _NET_TOOLS:
            return PermissionResultDeny(message="offline eval sandbox - no network access")
        if tool_name == "Bash" and _NET_BASH_RE.search(input_data.get("command", "")):
            return PermissionResultDeny(message="offline eval sandbox - network commands blocked")
        if tool_name == "AskUserQuestion":
            questions = input_data.get("questions", [])
            answers = await answer_questions(questions, persona, sim_model, sandbox, sim_log)
            for q in questions:
                cap.transcript.append(
                    f"\n[gate] {q.get('header', '?')}: {q.get('question', '')}\n"
                    f"[user] {answers.get(q.get('question', ''), '')}\n"
                )
            return PermissionResultAllow(updated_input={"questions": questions, "answers": answers})
        return PermissionResultAllow(updated_input=input_data)

    options = ClaudeAgentOptions(
        cwd=str(sandbox),
        # Pin the ORCHESTRATOR's tier. setting_sources=["project"] already gives each SUBAGENT
        # its own `model:` frontmatter (4 opus / 11 sonnet / 1 haiku), but nothing set the model
        # for Morgan herself, so the top-level session silently inherited the SDK default while
        # the operating guide requires opus ("routing, challenging findings and the §4/§5 calls
        # are deep work"). That mattered more than it looks: the judge scores largely from the
        # PM's own narration, so evaluating the orchestrator on a cheaper tier depresses the
        # result in a way indistinguishable from a genuine regression (audit 2026-08-01).
        model=team_model,
        setting_sources=["project"],
        # "default", not "acceptEdits": every tool call must route through can_use_tool -
        # acceptEdits short-circuits some calls past the callback, and AskUserQuestion then
        # dies with no interactive user attached (observed in the first smoke run).
        permission_mode="default",
        can_use_tool=can_use_tool,
        max_turns=max_turns,
        max_budget_usd=max_budget,
        stderr=cap.cli_stderr.append,
        # Per-case env (expected.yaml `session_env:`) lets a golden case exercise
        # human-side environment mechanisms (e.g. CST_COMPANY_ALLOW) - the harness is the
        # human here, same standing as the consent-marker creation (ADR-002).
        env={**_session_env(), **(extra_env or {})},
        # Headless runs otherwise bash-sandbox with no network and no user-site packages
        # (observed: `import markdown` failed inside the session while fine outside, so
        # render_html "could not" run). Interactive engagements are not sandboxed like
        # that; matching them keeps the eval faithful. Network hygiene stays enforced by
        # the _NET_BASH_RE deny in can_use_tool.
        sandbox={"enabled": False},
        # --target-path mode only (both None/empty for every case run - additive, no
        # behaviour change to the existing sandbox-is-a-repo-copy path): `plugins` loads
        # this plugin's skills/agents regardless of what `cwd` is (the SDK's --plugin-dir
        # equivalent, SdkPluginConfig={"type": "local", "path": ...}) - needed because cwd
        # is now a FOREIGN directory, not a virt-survtecb copy, so setting_sources=["project"]
        # alone would find no .claude/skills there. `disallowed_tools` structurally removes
        # Bash from what the model can even call - the static-only guarantee for a run
        # against a real (copied) project, independent of whether any guard hook happens to
        # be loaded (foreign-project mode has no .claude/settings.json, so the usual
        # exec-consent guard is not present to enforce it another way).
        plugins=plugins or [],
        disallowed_tools=disallowed_tools or [],
        # Hook lifecycle frames in the message stream (2026-09-13). The missing-injection
        # tripwire needs to see whether the plugin's UserPromptSubmit hooks fired and what
        # they returned; without this the harness cannot tell "the anchor was not injected"
        # from "the harness cannot see injections". Purely additive capture.
        include_hook_events=True,
    )

    # can_use_tool requires streaming input mode: a single-message async iterable stands in
    # for the string prompt (slash commands still expand from the message text). The stream
    # then HOLDS stdin open until the run ends - the permission control protocol answers over
    # the same channel, and an early close interrupts tool calls (observed: the first probe
    # and the AskUserQuestion gate both died "interrupted" when the stream ended after yield).
    session_done = asyncio.Event()

    async def _prompt_stream():
        yield {
            "type": "user",
            "message": {"role": "user", "content": f"{workflow_cmd} {scenario}"},
        }
        await session_done.wait()

    # Close policy - three observed failure modes drove this shape:
    #   * close on the FIRST result -> stdin (= the permission control channel) shuts
    #     while subagents run; every later write dies "AbortError: Stream closed";
    #   * never close -> the CLI waits on stdin forever and the run hangs to timeout;
    #   * close on result + fixed silence -> a subagent working quietly >45s trips it
    #     mid-engagement (killed the first full-lifecycle run's build phase).
    # So: arm the grace close only when a result has arrived AND no subagent task is
    # in flight AND the conversation has not resumed since. Task lifecycle comes from
    # the Task*Message frames; a hung task falls through to the outer --timeout.
    from claude_agent_sdk import TERMINAL_TASK_STATUSES

    grace: asyncio.Task | None = None
    inflight: set[str] = set()
    result_pending = False

    async def _grace_close():
        await asyncio.sleep(45)
        session_done.set()

    # Dead-at-birth watchdog (2026-07-27, observed twice): a spawned CLI can sit SILENT -
    # zero events - when the subscription usage window is saturated (or auth/handshake
    # fails), and the old async-for waited the whole per-case --timeout (40+ min) before
    # scoring an empty run. A healthy session emits its init SystemMessage within seconds,
    # so cap ONLY the first message; after that the outer --timeout owns hangs (a subagent
    # legitimately works quietly for minutes mid-run).
    stream = query(prompt=_prompt_stream(), options=options).__aiter__()
    first_message = True
    try:
        while True:
            try:
                if first_message:
                    message = await asyncio.wait_for(stream.__anext__(), timeout=STARTUP_TIMEOUT_S)
                else:
                    message = await stream.__anext__()
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                session_done.set()
                raise RuntimeError(
                    f"session emitted NOTHING within {STARTUP_TIMEOUT_S}s - dead at birth. "
                    "Likely causes: subscription usage window saturated (heavy interactive use "
                    "shares the Max window), auth failure, or a CLI/SDK handshake break. "
                    "Aborting fast instead of burning the full --timeout."
                )
            first_message = False
            if grace is not None:
                grace.cancel()
                grace = None
            msg_type = type(message).__name__
            if msg_type == "RateLimitEvent":
                # Surface the shared-window status instead of discovering it via a hang.
                print(f"  rate-limit status: {repr(message)[:200]}")
            if msg_type == "TaskStartedMessage":
                inflight.add((getattr(message, "data", None) or {}).get("task_id"))
            elif msg_type in ("TaskUpdatedMessage", "TaskNotificationMessage"):
                data = getattr(message, "data", None) or {}
                status = (data.get("patch") or {}).get("status") or data.get("status")
                if status in TERMINAL_TASK_STATUSES:
                    inflight.discard(data.get("task_id"))
            elif msg_type in ("AssistantMessage", "UserMessage"):
                result_pending = False  # conversation moved on - the prior result wasn't final
            entry = event_entry(message, msg_type)
            cap.events.append(entry)
            if events_fh is not None:
                events_fh.write(json.dumps(entry, default=str) + "\n")
                events_fh.flush()
            if isinstance(message, AssistantMessage):
                from_subagent = message.parent_tool_use_id is not None
                if not from_subagent or include_subagents:
                    cap.transcript += _transcript_lines(
                        message, TextBlock, ToolUseBlock, from_subagent
                    )
                    _flush_transcript()
                if message.usage:
                    usage_entry = {
                        "type": "assistant",
                        "from_subagent": from_subagent,
                        "model": message.model,
                        "usage": message.usage,
                    }
                    cap.usage_series.append(usage_entry)
                    if usage_fh is not None:
                        usage_fh.write(json.dumps(usage_entry) + "\n")
                        usage_fh.flush()
            elif isinstance(message, ResultMessage):
                # A result can arrive MID-RUN with subagent tasks still in flight (the CLI
                # closes the main turn, TaskProgress frames keep coming, and a later result
                # follows). Do NOT signal session_done here: ending the prompt stream closes
                # stdin, stdin carries the permission control channel, and every remaining
                # tool call then dies with "AbortError: Stream closed" (observed live - it
                # killed all writes for the second half of a run). Last result wins for cost.
                cap.cost_usd = message.total_cost_usd
                cap.num_turns = message.num_turns
                cap.is_error = bool(message.is_error)
                if message.usage or message.model_usage:
                    usage_entry = {
                        "type": "result",
                        "total_cost_usd": message.total_cost_usd,
                        "num_turns": message.num_turns,
                        "duration_ms": message.duration_ms,
                        "duration_api_ms": message.duration_api_ms,
                        "usage": message.usage,
                        # ModelUsage is a TypedDict (plain dict at runtime) - dict(v) copies
                        # it without assuming any particular key set beyond what the SDK sent.
                        "model_usage": {k: dict(v) for k, v in (message.model_usage or {}).items()},
                    }
                    cap.usage_series.append(usage_entry)
                    if usage_fh is not None:
                        usage_fh.write(json.dumps(usage_entry) + "\n")
                        usage_fh.flush()
                result_pending = True
            if result_pending and not inflight:
                grace = asyncio.create_task(_grace_close())
        if grace is not None:
            grace.cancel()
        session_done.set()
        return cap
    finally:
        if events_fh is not None:
            events_fh.close()
        if usage_fh is not None:
            usage_fh.close()


# --------------------------------------------------------------------------- scoring
def probe_artifacts(sandbox: Path) -> list[dict]:
    """Deterministic, code-level findings from what the run actually left on disk."""
    findings: list[dict] = []
    art = _vsit_paths().engagements_dir(sandbox)
    if not art.is_dir():
        return findings

    # 0.31 workspaces: an engagement's pack may live at artifacts/<slug>/ instead of the
    # flat root - probe every pack (flat root first for pre-0.31 runs).
    packs = [art] + sorted(
        p for p in art.iterdir() if p.is_dir() and (p / "engagement-state.json").is_file()
    )

    for txt in sorted(art.rglob("*.txt")):
        body = txt.read_text(encoding="utf-8", errors="ignore")
        if "morgan" in body.lower():
            title = "engagement-summary email written as .txt, signed as Morgan"
            if (
                '"hi,"' in body.lower()
                or body.lstrip().lower().startswith("hi,")
                or "\nhi," in body.lower()
            ):
                title += ", opens 'Hi,'"
            findings.append(
                {
                    "severity": "warning",
                    "location": f"artifacts/{txt.name}",
                    "title": title,
                    "kind": "artifact",
                }
            )

    for pack in packs:
        where = f"artifacts/{pack.name}/" if pack != art else "artifacts/"
        start_here = pack / "START-HERE.md"
        if start_here.is_file():
            text = start_here.read_text(encoding="utf-8", errors="ignore")
            status = next((ln.strip() for ln in text.splitlines() if "status" in ln.lower()), "")
            findings.append(
                {
                    "severity": "warning",
                    "location": f"{where}START-HERE.md",
                    "title": f"START-HERE living index present ({status[:80]})",
                    "kind": "artifact",
                }
            )

        # Machine-readable engagement state (ADR-006): present + valid + fresh render is
        # the lifecycle surface; a stale render is a real process defect left on disk.
        state_file = pack / "engagement-state.json"
        if state_file.is_file():
            try:
                from scripts.engagement_state import (
                    embedded_hash,
                    state_hash,
                    validate_state,
                )

                state = json.loads(state_file.read_text(encoding="utf-8"))
                problems = validate_state(state)
                if problems:
                    findings.append(
                        {
                            "severity": "critical",
                            "location": f"{where}engagement-state.json",
                            "title": f"engagement-state invalid: {problems[0][:100]}",
                            "kind": "artifact",
                        }
                    )
                else:
                    findings.append(
                        {
                            "severity": "warning",
                            "location": f"{where}engagement-state.json",
                            "title": "machine-readable engagement state present "
                            f"(status {state.get('status')}, profile "
                            f"{state.get('profile') or 'standard'})",
                            "kind": "artifact",
                        }
                    )
                    if start_here.is_file():
                        index_text = start_here.read_text(encoding="utf-8", errors="ignore")
                        if embedded_hash(index_text) == state_hash(state):
                            findings.append(
                                {
                                    "severity": "warning",
                                    "location": f"{where}START-HERE.md",
                                    "title": "state render fresh: START-HERE generated "
                                    "from engagement-state.json (hash match)",
                                    "kind": "artifact",
                                }
                            )
                        else:
                            findings.append(
                                {
                                    "severity": "critical",
                                    "location": f"{where}START-HERE.md",
                                    "title": "state render STALE: START-HERE does not "
                                    "match engagement-state.json",
                                    "kind": "artifact",
                                }
                            )
            except Exception as exc:
                findings.append(
                    {
                        "severity": "critical",
                        "location": f"{where}engagement-state.json",
                        "title": f"engagement-state unreadable: {str(exc)[:100]}",
                        "kind": "artifact",
                    }
                )

    mds = [p for p in art.rglob("*.md") if p.name != "ENGAGEMENTS.md"]
    if mds and all((p.parent / f"{p.stem}.html").is_file() for p in mds):
        findings.append(
            {
                "severity": "warning",
                "location": "artifacts/",
                "title": "dual artifacts: every .md deliverable rendered to .html",
                "kind": "artifact",
            }
        )
    return findings


_NORMALIZER_PROMPT = """
You are a neutral transcript normalizer for a delivery-session audit. Below is the
transcript of a session run by an AI delivery team (PM voice, tool lines, [gate]
question/answer pairs) plus a listing of the artifact files it wrote.

Emit ONLY a JSON object:
  {"findings": [{"severity": "critical|warning|medium|style", "location": "", "title": "", "kind": "behaviour"}]}

One finding per DISTINCT observed behaviour, decision or claim. Cover, where present:
how the session opened (introductions, versions, banners); what questions were asked
and answered at gates; statements about team size / which specialists were engaged and
why; plans, briefs and delegations; checks, tests or gates run (and their results);
artifacts written; how it closed (summaries, emails, next steps); anything refused,
skipped or left outstanding. Also capture substantive work findings the team itself
reported. Keep each title SHORT and phrased close to the transcript's own wording -
do not invent, generalise or editorialise. Location: an artifact path or blank.
Severity: use "warning" for every observed process behaviour, decision or gate exchange
(kind "behaviour"); grade an actual code/work defect the team reported with the severity
the team itself gave it.
"""

_JUDGE_PROMPT = """
You are an independent QA judge for an AI delivery team. Score the session transcript
below against the rubric. Be strict: score only what the transcript/artifacts evidence.

Emit ONLY a JSON object:
  {"dimensions": {"<dimension name>": <0.0-1.0>, ...},
   "weighted_score": <0.0-1.0>,
   "auto_fail": <bool>, "auto_fail_reason": "<short or empty>",
   "pass": <bool>, "rationale": "<= 3 sentences>"}

Apply the rubric's weights and its pass/auto-fail rules exactly.
"""


def _artifact_listing(
    sandbox: Path,
    body_cap: int = _ARTIFACT_BODY_CAP,
    total_cap: int = _ARTIFACT_LISTING_CAP,
) -> str:
    """The run's artifacts as paths PLUS truncated bodies of the .md/.txt deliverables.

    This listing is the only view of the WORK the normalizer and judge get - the
    transcript is the team talking about it. Paths alone let narration substitute for
    substance, so each text deliverable is inlined (path order) up to `body_cap` chars
    until `total_cap` is spent; every truncation and every skipped file is stated in-band
    so the judge can tell "short" from "cut". Non-text artifacts (.html renders, data
    files) stay path-only. Unreadable files are listed with their error, never raised.
    """
    art = _vsit_paths().engagements_dir(sandbox)
    if not art.is_dir():
        return "(no artifacts/ directory)"
    files = [p for p in sorted(art.rglob("*")) if p.is_file()]
    if not files:
        return "(empty)"

    out = ["## Files", *(p.relative_to(sandbox).as_posix() for p in files)]
    bodies: list[str] = []
    spent = 0
    omitted = 0
    for path in files:
        if path.suffix.lower() not in _ARTIFACT_BODY_SUFFIXES:
            continue
        rel = path.relative_to(sandbox).as_posix()
        if spent >= total_cap:
            omitted += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            bodies.append(f"### {rel}\n(unreadable: {exc})")
            continue
        body = text[: min(body_cap, total_cap - spent)]
        spent += len(body)
        cut = (
            f"\n[... truncated: {len(body)} of {len(text)} chars shown ...]"
            if len(body) < len(text)
            else ""
        )
        bodies.append(f"### {rel}\n{body}{cut}")
    if bodies:
        out += ["", "## Deliverable contents (truncated)", *bodies]
    if omitted:
        out.append(
            f"\n[... {omitted} further text deliverable(s) omitted: listing cap reached ...]"
        )
    return "\n".join(out)


async def normalize(transcript: str, listing: str, model: str) -> list[dict]:
    reply = await _one_shot(
        f"{_NORMALIZER_PROMPT}\n## Artifact files\n{listing}\n\n## Transcript\n{_cap_transcript(transcript)}",
        model,
    )
    findings = [
        f
        for f in _extract_json(reply).get("findings", [])
        if isinstance(f, dict) and f.get("title")
    ]
    # Behaviour observations are facts, not graded defects - but the process manifests
    # set a min_severity: warning floor, and a normalizer that files them as
    # "medium"/"style" makes the scorer discard correct behaviour wholesale (observed:
    # recall 0.0 on a run whose findings named every planted behaviour). Enforce the
    # convention deterministically rather than trusting the prompt.
    for f in findings:
        if f.get("kind") == "behaviour" and f.get("severity") in ("style", "medium", None):
            f["severity"] = "warning"
    return findings


async def judge(transcript: str, listing: str, rubric: str, model: str) -> dict:
    reply = await _one_shot(
        f"{_JUDGE_PROMPT}\n## Rubric\n{rubric}\n\n## Artifact files\n{listing}\n\n"
        f"## Transcript\n{_cap_transcript(transcript)}",
        model,
    )
    return _extract_json(reply)


# --------------------------------------------------------------------------- per case
# The uncoached resume ask - deliberately says nothing about START-HERE or prior decisions:
# whether a fresh session finds the state of record and honours it IS what a resume tests.
_RESUME_PROMPT = (
    "The previous session got cut off mid-engagement. Resume the engagement in this "
    "workspace where it left off and close it out properly. Everything so far is under "
    "artifacts/."
)


async def run_case(
    case_id: str,
    args: argparse.Namespace,
    run_root: Path,
    sandbox_override: Path | None = None,
    scenario_override: str | None = None,
) -> dict:
    manifest = _load_case(case_id)
    case_dir: Path = manifest["_dir"]
    scenario = scenario_override or (case_dir / manifest["input"]).read_text(encoding="utf-8")
    # The case's declared front-door command (/engage or /engage-light); a resume never
    # re-invokes the front door, its scenario_override is the uncoached continue ask.
    workflow_cmd = "/engage" if scenario_override else case_workflow(case_id)
    persona_file = case_dir / "driver.md"
    persona = (persona_file if persona_file.is_file() else DEFAULT_PERSONA).read_text(
        encoding="utf-8"
    )
    rubric = (RUBRICS_ROOT / f"{manifest['rubric']}.md").read_text(encoding="utf-8")

    out_dir = run_root / (f"{case_id}-resume" if sandbox_override else case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = case_mode(manifest, getattr(args, "plugin_mode", False))
    layout: PluginLayout | None = None
    layout_notes: list[str] = []
    if sandbox_override is not None:
        sandbox = sandbox_override  # shared, pre-existing state - never rebuilt, never deleted
        print(f"  [{case_id}] resuming in kept sandbox {sandbox}")
        args.keep_sandbox = True
    elif mode == "plugin":
        print(f"  [{case_id}] building plugin-mode layout (throwaway HOME, cache copy)...")
        # OUTSIDE this repository's tree, in the system temp directory (2026-09-13, third
        # live run). Built under evals/runs/, the client project sat inside THIS checkout's
        # git tree, so Claude Code walked up from it, found this repo's root and CLAUDE.md,
        # and the session's first command was a Read under the dev checkout. A real client
        # project never lives inside the plugin repository; neither does this one now. The
        # run directory keeps every output; only the layout moves. Removed with the sandbox
        # unless --keep-sandbox.
        layout = build_plugin_layout(
            Path(tempfile.mkdtemp(prefix=f"vsit-eval-{case_id}-")),
            probe_cache=bool(manifest.get("probe_cache")),
        )
        layout_notes.append(f"layout built outside the repo tree at {layout.root}")
        sandbox = layout.project
        overlay_fixtures(case_dir / "fixtures", sandbox)
        if not getattr(args, "no_inherit_auth", False):
            seeded = seed_session_auth(layout)
            print(f"  [{case_id}] seeded auth into the throwaway home: {seeded or 'nothing found'}")
        layout_notes += [n for n in [long_path_note(layout.root)] if n]
        for note in layout_notes:
            # Reported, not raised. On Linux it is advice about the Windows VM; on Windows the
            # copy that just succeeded proves long paths are enabled there, so it is a note
            # about how little headroom is left before a deeper tree stops copying.
            print(f"  [{case_id}] {note}", file=sys.stderr)
    else:
        sandbox = out_dir / "sandbox"
        print(f"  [{case_id}] building sandbox...")
        build_sandbox(sandbox)
        # Same warm cache the plugin layout gets (2026-09-13, process-blocked-not-done rerun):
        # SANDBOX_EXCLUDES leaves the copy without the interpreter cache `virt-surv go` writes,
        # the prefetch hook stays silent on a cold cache, and every repo-mode open tripped
        # missing-prompt-injection once the tripwire existed to notice.
        warm_sandbox_interpreter(sandbox, out_dir / "home")
        # Optional case fixtures: a `fixtures/` tree is overlaid sandbox-relative (e.g.
        # fixtures/artifacts/x.md -> sandbox/artifacts/x.md), so a case can seed a REAL
        # drifted/partial engagement state for the session to act on. A described-only state
        # invites a plan instead of actions (first live run of process-close-reconciliation:
        # Morgan correctly refused to "fix" files that did not exist). Never overlaid on a
        # resume - the kept sandbox IS the state.
        fixtures = case_dir / "fixtures"
        if fixtures.is_dir():
            # Fixed argv; rsync deliberately resolved from PATH.
            subprocess.run(  # nosec B603 B607
                ["rsync", "-a", f"{fixtures}/", f"{sandbox}/"], check=True, capture_output=True
            )
    plugin_root = layout.cache_dir if layout else sandbox
    trust_configs = layout.claude_json_files if layout else None
    # What the tripwires need to know about this run's shape, persisted so --rescore over a
    # saved run scans against the same roots instead of guessing them from the directory.
    (out_dir / "run-meta.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "project_root": str(sandbox),
                "plugin_root": str(plugin_root),
                "workflow": workflow_cmd,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if getattr(args, "dry_run", False):
        env = {**_session_env(), **(layout.session_env() if layout else {})}
        report = describe_dry_run(
            case_id,
            sandbox,
            layout.cache_dir if layout else None,
            env,
            workflow_cmd,
            args.team_model,
            extra_notes=layout_notes,
        )
        print(report)
        (out_dir / "dry-run.txt").write_text(report + "\n", encoding="utf-8")
        return {
            "case": case_id,
            "mode": mode,
            "dry_run": True,
            "passed": True,
            "deterministic": {"recall": None, "skipped": "dry run"},
        }
    ensure_workspace_trust(sandbox, trust_configs)
    # Snapshot what the HARNESS seeded, before the team can touch it. Persisted so --rescore
    # over a saved run applies the same exclusion instead of silently re-admitting fixtures.
    baseline = fixture_baseline(sandbox)
    (out_dir / "fixture-baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    sim_log = SimTranscript()
    cap = SessionCapture()
    started = time.monotonic()
    timeout_s = case_timeout(manifest, args.timeout)
    max_budget = case_budget(manifest, args.max_budget)
    budget_note = f", ${max_budget}" if max_budget else ""
    clock_note = f", {timeout_s}s wall clock" if timeout_s > 0 else ", no wall clock"
    print(
        f"  [{case_id}] running live /engage session "
        f"(cap {args.max_turns} turns{budget_note}{clock_note})..."
    )
    try:
        await asyncio.wait_for(
            run_engage_session(
                cap,
                scenario,
                sandbox,
                persona,
                args.sim_model,
                args.max_turns,
                max_budget,
                sim_log,
                workflow_cmd=workflow_cmd,
                team_model=args.team_model,
                extra_env={
                    **{str(k): str(v) for k, v in (manifest.get("session_env") or {}).items()},
                    # Plugin mode last: the throwaway home is not negotiable by a manifest.
                    **(layout.session_env() if layout else {}),
                },
                include_subagents=not getattr(args, "exclude_subagent_output", False),
                # The CACHE copy, never the marketplace checkout and never this repo - the
                # session must load the plugin from where an install puts it.
                plugins=[{"type": "local", "path": str(layout.cache_dir)}] if layout else None,
            ),
            timeout=timeout_s if timeout_s > 0 else None,  # 0 = no wall clock; budget is the stop
        )
    except asyncio.TimeoutError:
        cap.timed_out = True
        print(f"  [{case_id}] TIMED OUT after {timeout_s}s - scoring what exists", file=sys.stderr)
    except Exception as exc:  # session died - score whatever it left behind, report the error
        cap.is_error = True
        cap.error = describe_session_death(exc, cap, max_budget)
        print(f"  [{case_id}] SESSION ERROR: {cap.error}", file=sys.stderr)
    finally:
        drop_workspace_trust(sandbox, trust_configs)
    duration = time.monotonic() - started
    if cap.cli_stderr:
        (out_dir / "cli-stderr.log").write_text("".join(cap.cli_stderr), encoding="utf-8")

    transcript = "".join(cap.transcript)
    (out_dir / "transcript.md").write_text(transcript, encoding="utf-8")
    (out_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, default=str) for e in cap.events), encoding="utf-8"
    )
    # Track D (token plan Phase 0, 2026-08-18): case runs now persist the same per-message
    # usage series --target-path mode always kept, plus the computed attribution - so cost
    # is attributable per workflow (main-loop vs subagent share, per-model split) instead of
    # one opaque total. Data was already collected in cap.usage_series; it was simply never
    # written for case runs.
    (out_dir / "usage-series.jsonl").write_text(
        "\n".join(json.dumps(u) for u in cap.usage_series), encoding="utf-8"
    )
    (out_dir / "attribution.json").write_text(
        json.dumps(usage_attribution(cap.usage_series), indent=2), encoding="utf-8"
    )
    (out_dir / "gates.json").write_text(
        json.dumps(
            {"consent_granted": sim_log.consent_granted, "exchanges": sim_log.exchanges}, indent=2
        ),
        encoding="utf-8",
    )

    result = await score_run(case_id, out_dir, sandbox, transcript, manifest, rubric, args)
    result.update(
        {
            "gates_answered": len(sim_log.exchanges),
            "consent_granted": sim_log.consent_granted,
            "cost_usd": cap.cost_usd,
            "num_turns": cap.num_turns,
            "timed_out": cap.timed_out,
            "session_error": cap.is_error,
            "spend_capped": cap.spend_capped,
            "error": cap.error,
            "duration_s": round(duration, 1),
            "mode": mode,
        }
    )
    result["passed"] = result["passed"] and not cap.timed_out and not cap.is_error
    result["outcome"] = run_outcome(result)
    (out_dir / "score.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    # evals/runs/ is git-ignored and pruned; the tracked log is what makes the numbers
    # trendable across releases rather than re-narrated in each baseline.
    append_result(result_record(result, out_dir.parent.name))

    if not args.keep_sandbox:
        # Plugin mode: the whole layout goes, not just the client project - the throwaway
        # home holds two repo copies and (when seeded) copied credential material.
        shutil.rmtree(layout.root if layout else sandbox, ignore_errors=True)
    return result


_TARGET_SCENARIO_DEFAULT = (
    "Please review this application's codebase for issues - findings pack and report as normal."
)


async def run_target(
    source: Path,
    args: argparse.Namespace,
    run_root: Path,
) -> dict:
    """Live /engage session against an ARBITRARY external directory (diagnostic mode, not a
    golden-case run): no manifest, no expected.yaml, no scoring - just a real session against a
    disposable copy of `source`, captured in full for human review. Skips build_sandbox/
    case_workflow entirely; uses build_target_sandbox instead. See the plan at
    ~/.claude/plans/golden-beaming-codd.md ("extend eval_engage.py for an arbitrary external
    target directory") for the full design rationale."""
    source = source.resolve()
    if not source.is_dir():
        raise SystemExit(f"--target-path is not a directory: {source}")

    slug = re.sub(r"[^a-z0-9]+", "-", source.name.lower()).strip("-") or "target"
    out_dir = run_root / f"target-{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    sandbox = out_dir / "sandbox"
    print(f"  [target:{slug}] building disposable copy of {source} -> {sandbox} ...")
    build_target_sandbox(
        source,
        sandbox,
        team_preferences={
            "large_context_review_split": True,
            "regulatory_citations": False,
        },
    )
    ensure_workspace_trust(sandbox)

    scenario = args.target_prompt or _TARGET_SCENARIO_DEFAULT
    persona = DEFAULT_PERSONA.read_text(encoding="utf-8")
    sim_log = SimTranscript()
    cap = SessionCapture()
    started = time.monotonic()
    timeout_s = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_S
    budget_note = f", ${args.max_budget}" if args.max_budget else ""
    clock_note = f", {timeout_s}s wall clock" if timeout_s > 0 else ", no wall clock"
    print(
        f"  [target:{slug}] running live /engage session against a copy of {source.name} "
        f"(cap {args.max_turns} turns{budget_note}{clock_note}, Bash disallowed)..."
    )
    try:
        await asyncio.wait_for(
            run_engage_session(
                cap,
                scenario,
                sandbox,
                persona,
                args.sim_model,
                args.max_turns,
                args.max_budget,
                sim_log,
                workflow_cmd="/engage",
                team_model=args.team_model,
                include_subagents=not getattr(args, "exclude_subagent_output", False),
                plugins=[{"type": "local", "path": str(REPO_ROOT)}],
                disallowed_tools=["Bash"],
                live_dir=out_dir,
            ),
            timeout=timeout_s if timeout_s > 0 else None,
        )
    except asyncio.TimeoutError:
        cap.timed_out = True
        print(f"  [target:{slug}] TIMED OUT after {timeout_s}s", file=sys.stderr)
    except Exception as exc:
        cap.is_error = True
        cap.error = f"{type(exc).__name__}: {exc}"
        print(f"  [target:{slug}] SESSION ERROR: {cap.error}", file=sys.stderr)
    finally:
        drop_workspace_trust(sandbox)
    duration = time.monotonic() - started

    transcript = "".join(cap.transcript)
    (out_dir / "transcript.md").write_text(transcript, encoding="utf-8")
    (out_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, default=str) for e in cap.events), encoding="utf-8"
    )
    (out_dir / "usage-series.jsonl").write_text(
        "\n".join(json.dumps(u) for u in cap.usage_series), encoding="utf-8"
    )
    (out_dir / "attribution.json").write_text(
        json.dumps(usage_attribution(cap.usage_series), indent=2), encoding="utf-8"
    )
    (out_dir / "gates.json").write_text(
        json.dumps(
            {"consent_granted": sim_log.consent_granted, "exchanges": sim_log.exchanges}, indent=2
        ),
        encoding="utf-8",
    )
    summary = {
        "source": str(source),
        "sandbox_kept": bool(args.keep_sandbox),
        "cost_usd": cap.cost_usd,
        "num_turns": cap.num_turns,
        "timed_out": cap.timed_out,
        "session_error": cap.is_error,
        "error": cap.error,
        "duration_s": round(duration, 1),
        "gates_answered": len(sim_log.exchanges),
        "consent_granted": sim_log.consent_granted,
        "assistant_messages_with_usage": sum(
            1 for u in cap.usage_series if u["type"] == "assistant"
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"  [target:{slug}] done - cost=${cap.cost_usd or '?'} turns={cap.num_turns} "
        f"duration={duration:.0f}s timed_out={cap.timed_out} error={cap.is_error}"
    )
    print(f"  [target:{slug}] output -> {out_dir}")

    if not args.keep_sandbox:
        shutil.rmtree(sandbox, ignore_errors=True)
    return summary


def gate_findings(out_dir: Path) -> list[dict]:
    """Turn each AskUserQuestion exchange into a deterministic finding.

    Escalation was structurally unscorable before this. A case that tests "pause and ask the
    user rather than deciding alone" recorded the question in gates.json, which the scorer never
    read; scoring ran over findings.json, whose titles are the NORMALIZER's paraphrase. So the
    behaviour was judged on someone else's summary of it.

    Found on 2026-08-01 by process-gate-selfcorrect. The team did exactly the right thing: it
    fired the question tool naming the contradiction and refusing to resolve it alone, and the
    question text matched the manifest's own keyword ("escalate"). It scored recall 0.5 and a
    FAIL anyway, because none of the normalizer's finding titles carried the wording. A false
    negative, and the costliest kind: it reads as the team failing a discipline it actually
    observed.

    The question the team asked is a fact, not an interpretation, so it belongs in the evidence
    deterministically rather than via an LLM round trip.
    """
    try:
        gates = json.loads((out_dir / "gates.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict] = []
    for exchange in gates.get("exchanges") or []:
        question = (exchange.get("question") or "").strip()
        if not question:
            continue
        header = (exchange.get("header") or "").strip()
        answer = (exchange.get("answer") or "").strip()
        out.append(
            {
                "severity": "warning",
                "location": "",
                # The full question text, so keyword matching sees the team's OWN words.
                "title": f"Asked the user via the question tool{f' [{header}]' if header else ''}: "
                f"{question}" + (f" (answered: {answer})" if answer else ""),
                "kind": "behaviour",
            }
        )
    return out


_RAW_CHUNK_CHARS = 300
_RAW_MAX_PER_SOURCE = 120
_RAW_MAX_TOTAL = 600
# Reserved slice for the PM's own prose, so an artifact-heavy run cannot crowd it out.
_RAW_TRANSCRIPT_QUOTA = 200


def _chunk_text(text: str) -> list[str]:
    """Split into line-sized chunks, because a chunk is the unit the mention-guard protects.

    Dumping a whole file into one finding would let a single stray "outstanding" anywhere in it
    veto an unrelated planted match (eval_score._matches applies exclude_keywords to the whole
    haystack). Line-level chunks keep that guard LOCAL: the line claiming something is still
    outstanding is vetoed, while the line evidencing the work still matches. That is what the
    mention-guard was always meant to do.
    """
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or set(line) <= {"-", "=", "|", "#", "*", "_", " "}:
            continue
        while line and len(out) < _RAW_MAX_PER_SOURCE:
            out.append(line[:_RAW_CHUNK_CHARS])
            line = line[_RAW_CHUNK_CHARS:]
        if len(out) >= _RAW_MAX_PER_SOURCE:
            break
    return out


def fixture_baseline(sandbox: Path) -> dict[str, str]:
    """Digest every file under sandbox/artifacts/ as seeded, BEFORE the team touches anything.

    A case may seed a realistic drifted pack via `fixtures/`. Those files are the case's own
    INPUT. Scoring them as evidence lets the harness match a planted must-find against text the
    harness itself wrote, so a run that does literally nothing passes.
    """
    out: dict[str, str] = {}
    artifacts = _vsit_paths().engagements_dir(sandbox)
    if not artifacts.is_dir():
        return out
    for path in sorted(artifacts.rglob("*")):
        if path.is_file():
            try:
                out[str(path.relative_to(sandbox))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:  # nosec B112 - fail open, an unreadable file just drops from the hash set
                continue
    return out


def raw_evidence_findings(
    sandbox: Path, transcript: str, baseline: dict[str, str] | None = None
) -> list[dict]:
    """Feed the team's OWN words into the scored evidence: artifact bodies and PM prose.

    Until now the scorer matched against `findings.json` alone, whose titles are the
    NORMALIZER's paraphrase of the run. So a case was judged on someone else's summary of the
    team's work, and any behaviour the paraphrase reworded became invisible.

    Measured on run 20260801T190159Z, three "missed" must-find items were performed with the
    manifest's own keywords VERBATIM in the delivered artifacts: process-close-reconciliation
    REC-3 and REC-4 ("authoritative", "pending human sign-off", "Document control" appear 6, 20
    and 35 times in the event stream), and process-evidence-tagging TAG-2, whose dimension the
    LLM judge independently scored 1.0 while the deterministic layer called it missing. The
    paraphrase had rewritten "🧠 Inferred" as "Declined to answer, refused to guess", and not one
    occurrence of the keyword survived into a title.

    Same shape as the escalation bug fixed earlier the same day: what the team actually did is a
    fact, and facts belong in the evidence deterministically rather than via an LLM round trip.
    """
    findings: list[dict] = []
    baseline = baseline or {}

    def _add(chunks: list[str], location: str, kind: str) -> None:
        for chunk in chunks:
            if len(findings) >= _RAW_MAX_TOTAL:
                return
            findings.append(
                # `location` is deliberately EMPTY on raw findings. eval_score._matches folds
                # location into the keyword haystack, so carrying the path would let a spec
                # match on a FILENAME the harness seeded rather than on content the team wrote.
                # `kind` separates the team TALKING ("prose") from the team having DONE
                # something ("artifact"), so the scorer can refuse to accept a promise as
                # evidence and a manifest can demand artifact-backed proof via `sources:`.
                {"severity": "warning", "location": "", "title": chunk, "kind": kind}
            )

    # The PM's own prose goes in FIRST, with a reserved quota. Chunking it last under a shared
    # cap meant an artifact-heavy run spent the entire budget on files and recorded ZERO
    # transcript chunks, silently reintroducing the very blindness this function exists to fix.
    _add(_chunk_text(transcript)[:_RAW_TRANSCRIPT_QUOTA], "", "prose")

    artifacts = _vsit_paths().engagements_dir(sandbox)
    if artifacts.is_dir():
        for path in sorted(artifacts.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".md", ".txt", ".json"):
                continue
            rel = str(path.relative_to(sandbox))
            try:
                raw = path.read_bytes()
            except Exception:  # nosec B112 - fail open, an unreadable file just drops from scoring
                continue
            # Unchanged since seeding => the case's own INPUT, not the team's work. Skip it.
            if baseline.get(rel) == hashlib.sha256(raw).hexdigest():
                continue
            _add(_chunk_text(raw.decode("utf-8", errors="replace")), rel, "artifact")

    return findings


def read_events(out_dir: Path) -> list[dict]:
    """The run's captured event stream, one JSON object per line (missing file -> empty)."""
    path = out_dir / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def rescore_project_root(out_dir: Path) -> Path:
    """The project a saved run actually worked in, for --rescore to probe.

    Repo-as-project runs keep it at `<case>/sandbox`, which is what this always assumed. A
    plugin-mode run's project is the CLIENT directory inside the layout, so rescoring one
    against `<case>/sandbox` would probe a directory that does not exist and score every
    artifact as missing. run-meta.json records where it really was.
    """
    meta_file = out_dir / "run-meta.json"
    if meta_file.is_file():
        try:
            root = (json.loads(meta_file.read_text(encoding="utf-8")) or {}).get("project_root")
        except (OSError, json.JSONDecodeError):
            root = None
        if root:
            return Path(root)
    return out_dir / "sandbox"


def tripwire_context(
    out_dir: Path, sandbox: Path, transcript: str, manifest: dict
) -> TripwireContext:
    """Assemble what the tripwires scan: the capture plus this run's project/plugin roots.

    Roots come from run-meta.json where the run wrote one, so a `--rescore` of a plugin-mode
    run scans against the cache copy it actually loaded rather than against the client project.
    Pre-2026-09-13 runs have no run-meta.json; for those the sandbox is both roots, which is
    exactly true of repo-as-project mode.
    """
    meta: dict = {}
    meta_file = out_dir / "run-meta.json"
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            meta = {}
    workflow = meta.get("workflow") or manifest.get("workflow") or ""
    return TripwireContext(
        transcript=transcript,
        events=read_events(out_dir),
        project_root=str(meta.get("project_root") or sandbox),
        plugin_root=str(meta.get("plugin_root") or sandbox),
        allowed_roots=[str(r) for r in (manifest.get("tripwire_allowed_roots") or [])],
        expects_engaged_open=str(workflow).startswith("/engage"),
    )


async def score_run(
    case_id: str,
    out_dir: Path,
    sandbox: Path,
    transcript: str,
    manifest: dict,
    rubric: str,
    args: argparse.Namespace,
) -> dict:
    """The scoring layers alone - also reachable via --rescore over a saved run dir."""
    listing = _artifact_listing(sandbox)
    print(f"  [{case_id}] scoring (probe + normalizer + judge)...")
    try:
        baseline = json.loads((out_dir / "fixture-baseline.json").read_text(encoding="utf-8"))
    except Exception:
        baseline = {}
    findings = (
        probe_artifacts(sandbox)
        + gate_findings(out_dir)
        + raw_evidence_findings(sandbox, transcript, baseline)
    )
    # One-shot helpers flake occasionally (observed: an empty findings list on a rich
    # transcript; a spurious max-turns error) - retry once before degrading. A non-trivial
    # transcript never legitimately normalizes to zero findings.
    for attempt in (1, 2):
        try:
            normalized = await normalize(transcript, listing, args.aux_model)
        except Exception as exc:
            print(f"  [{case_id}] normalizer attempt {attempt} failed: {exc}", file=sys.stderr)
            normalized = []
        if normalized or len(transcript) < 2000:
            findings += normalized
            break
        if attempt == 2:
            print(
                f"  [{case_id}] normalizer empty twice - deterministic findings only",
                file=sys.stderr,
            )
    (out_dir / "findings.json").write_text(
        json.dumps({"findings": findings}, indent=2), encoding="utf-8"
    )

    expected = {k: v for k, v in manifest.items() if not k.startswith("_")}
    wires = scan_tripwires(
        tripwire_context(out_dir, sandbox, transcript, manifest),
        tripwires_off(expected),
    )
    if wires:
        for wire in wires:
            print(f"  [{case_id}] TRIPWIRE {wire['id']}: {wire['evidence'][0]}", file=sys.stderr)
    (out_dir / "tripwires.json").write_text(json.dumps(wires, indent=2), encoding="utf-8")
    det = score(expected, findings, wires)

    # `judge: none` in a manifest (2026-09-13): a case whose ground truth is entirely
    # deterministic - the plugin-mode case asserts where files landed and that no tripwire
    # fired, none of which an LLM judge can add anything to. Declaring it in the manifest
    # (rather than relying on whoever runs it remembering --skip-judge) keeps the case cheap
    # by construction. A rubric is still declared and still resolves, so forcing the judge on
    # is a matter of removing one line.
    judge_result: dict = {"skipped": True}
    manifest_judge = str(manifest.get("judge") or "").strip().lower()
    if manifest_judge in ("none", "off", "skip"):
        judge_result = {"skipped": True, "reason": "manifest declares judge: none"}
    elif not args.skip_judge:
        for attempt in (1, 2):
            try:
                judge_result = await judge(transcript, listing, rubric, args.aux_model)
                break
            except Exception as exc:
                # "pass" below is the rubric verdict key, not a password (B105 false positive)
                judge_result = {"error": f"{type(exc).__name__}: {exc}", "pass": False}  # nosec
                print(f"  [{case_id}] judge attempt {attempt} failed: {exc}", file=sys.stderr)

    # Fail CLOSED on the judge. Two holes, both of which passed work that should not have:
    # `.get("pass", True)` meant a parseable reply that simply omitted the key was treated as a
    # pass, and `auto_fail` was requested in the judge prompt but never read anywhere, so a
    # self-contradicting reply ("auto_fail": true, "pass": true) passed. A skipped judge
    # (--skip-judge) is the one legitimate absence and stays neutral.
    judged = judge_result.get("skipped") or (
        bool(judge_result.get("pass", False)) and not judge_result.get("auto_fail")
    )
    return {
        "case": case_id,
        "passed": bool(det.get("passed")) and bool(judged),
        "deterministic": det,
        "judge": judge_result,
    }


# --------------------------------------------------------------------------- the record
# The baseline's machine-readable verdict, emitted here and PARSED by scripts.release_gate
# (format documented in evals/README.md). Before it, a baseline saying "no clean-pass claim
# is made" satisfied the promotion gate, because the gate only checked the file existed.
# The harness can only fill in the RAW column; adjudication is a human act, so the emitted
# block starts at cases_adjudicated_pass: 0 and the human moves cases across as they
# adjudicate them against the transcripts.
VERDICT_FENCE = "eval-verdict"


def verdict_block(results: list[dict], run_id: str) -> str:
    """The draft ```eval-verdict block for a run, ready to paste into a baseline record.

    `results` are per-case score dicts (as written to score.json). Verdict is `pass` only
    when every case passed raw; otherwise `fail`, which the human upgrades to
    `pass-with-adjudication` after evidencing each failure. The counts must satisfy
    cases_passed_raw + cases_adjudicated_pass + unadjudicated_failures == cases_total -
    the release gate enforces that identity, so moving a case is a two-number edit.
    """
    raw_pass = sum(1 for r in results if r.get("passed"))
    total = len(results)
    return "\n".join(
        [
            f"```{VERDICT_FENCE}",
            "# raw harness output - adjudicate each failure against its transcript, then",
            "# move it from unadjudicated_failures to cases_adjudicated_pass (and set",
            "# verdict: pass-with-adjudication). The gate fails while any remain.",
            f"verdict: {'pass' if raw_pass == total and total else 'fail'}",
            f"cases_total: {total}",
            f"cases_passed_raw: {raw_pass}",
            "cases_adjudicated_pass: 0",
            f"unadjudicated_failures: {total - raw_pass}",
            f"runs: {run_id}",
            "```",
        ]
    )


def _plugin_version(root: Path = REPO_ROOT) -> str:
    """Plugin version under `root` ('unknown' if unreadable - a trend row is never fatal)."""
    try:
        return str(
            json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))[
                "version"
            ]
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return "unknown"


def case_timeout(manifest: dict, cli_timeout: int | None) -> int:
    """Resolve the wall clock for one case: CLI override, else manifest, else the default.

    Precedence is deliberate. An explicit --timeout is a human capping the run (a smoke pass, a
    constrained machine) and must win over everything. Otherwise the case's own `timeout_s`
    applies, because how long a case needs is a property of the case, not of the invocation.
    0 means no wall clock at all, and is preserved through both layers.
    """
    if cli_timeout is not None:
        return cli_timeout
    declared = manifest.get("timeout_s")
    if declared is None:
        return DEFAULT_TIMEOUT_S
    try:
        value = int(declared)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return value if value >= 0 else DEFAULT_TIMEOUT_S


def case_budget(manifest: dict, cli_budget: float | None) -> float | None:
    """Resolve the spend cap for one case: CLI override, else the manifest's
    `max_budget_usd`, else none - the same precedence as case_timeout, for the same reason.
    Added 2026-09-13 after process-blocked-not-done, a five-turn case whenever the session
    holds the blocked state, ran the whole build once the simulated user unblocked it and
    died at a $5 cap set for the cheaper path."""
    if cli_budget is not None:
        return cli_budget
    declared = manifest.get("max_budget_usd")
    if declared is None:
        return None
    try:
        value = float(declared)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def describe_session_death(
    exc: BaseException, cap: "SessionCapture", max_budget: float | None
) -> str:
    """The SDK's own message for a dead CLI says only "check stderr"; say what the stderr
    and the spend actually show. A session whose recorded cost sits at the cap died of the
    cap - that is a budget to raise, not a defect to chase."""
    text = f"{type(exc).__name__}: {exc}"
    tail = [line.strip() for line in cap.cli_stderr if line.strip()][-5:]
    at_cap = bool(max_budget) and cap.cost_usd is not None and cap.cost_usd >= 0.95 * max_budget
    said_budget = any("budget" in line.lower() for line in tail)
    if at_cap or said_budget:
        cap.spend_capped = True
        spent = f"${cap.cost_usd:.2f}" if cap.cost_usd is not None else "an unrecorded amount"
        text = (
            f"spend cap reached ({spent} against a ${max_budget} cap) - the session was stopped "
            f"mid-engagement, not by a defect; raise --max-budget or the case's max_budget_usd. "
            f"SDK said: {text}"
        )
    if tail:
        text += " | cli stderr: " + " / ".join(tail)
    return text


def run_outcome(result: dict) -> str:
    """Classify a run as "pass", "fail" or "unscorable".

    A run killed by a timeout or a session error (an API 529, a dropped stream) produced no
    gradeable output, so calling it a FAIL states something the evidence does not support: it
    conflates "the team answered badly" with "the team never got to answer". Folding both into
    one boolean is what made the headline pass rate unreadable - an audit on 2026-08-01 measured
    17/49 (35%) raw passes and found 13 of the 32 failures were runs that died, three of them
    on a confirmed API 529 after exhausting all ten retries. Excluding them the rate is 17/36
    (47%), and the two "most-missed" items turned out to be missed almost only on dead runs
    (NEXT-1: five misses, five of them dead runs, zero on a run that finished).

    Kept separate from `passed`, which stays a strict boolean, so nothing downstream that
    already reads `passed` changes meaning.
    """
    if result.get("timed_out") or result.get("session_error"):
        return "unscorable"
    return "pass" if result.get("passed") else "fail"


def summarise_results(rows: list[dict]) -> dict:
    """Aggregate trend rows the way a reader should read them: over SCORABLE runs only.

    Reporting `passed / total` counts infrastructure deaths as quality failures and makes the
    product look worse than the evidence says. Reporting `passed / scorable` plus an explicit
    unscorable count states both facts without hiding either - the unscorable count is itself a
    harness-health signal worth watching (it was 26% of runs over the 2026-07-25..30 window,
    and those runs cost ~3x a healthy one while producing a median of 4 turns).
    """
    total = len(rows)
    unscorable = [r for r in rows if (r.get("outcome") or run_outcome(r)) == "unscorable"]
    scorable = [r for r in rows if (r.get("outcome") or run_outcome(r)) != "unscorable"]
    passed = [r for r in scorable if r.get("passed")]
    return {
        "total": total,
        "scorable": len(scorable),
        "unscorable": len(unscorable),
        "passed": len(passed),
        "pass_rate_scorable": round(len(passed) / len(scorable), 3) if scorable else None,
        "pass_rate_all": round(len(passed) / total, 3) if total else None,
        "unscorable_rate": round(len(unscorable) / total, 3) if total else None,
    }


def result_record(result: dict, run_id: str, mode: str = "run", version: str | None = None) -> dict:
    """Flatten one case result (score.json shape) into a trend row for evals/results.jsonl.

    `run_id` is the run directory's UTC stamp - it doubles as the row's time axis, so no
    separate clock is invented when backfilling historic runs. `mode` is "run" for a live
    session, "rescore" for a --rescore pass over a kept run. `version` defaults to the
    CURRENT plugin version, which is only true for a live run: a backfill must pass the
    version the run actually exercised (or "unknown"), never let today's number be
    stamped on a month-old row.
    """
    det = result.get("deterministic") or {}
    jd = result.get("judge") or {}
    return {
        "run_id": run_id,
        "case": result.get("case"),
        "mode": mode,
        "version": version or _plugin_version(),
        "passed": bool(result.get("passed")),
        "recall": det.get("recall"),
        "must_find_missed": det.get("must_find_missed") or [],
        "traps_triggered": det.get("false_positive_traps_triggered") or [],
        # 2026-09-13: which tripwires fired, so a trend row records the mechanical channel
        # as well as the keyword one. Empty on every pre-tripwire row, which is accurate.
        "tripwires_triggered": det.get("tripwires_triggered") or [],
        "layout_mode": result.get("mode") or "repo",
        "judge_score": jd.get("weighted_score"),
        "judge_pass": jd.get("pass"),
        "cost_usd": result.get("cost_usd"),
        "num_turns": result.get("num_turns"),
        "duration_s": result.get("duration_s"),
        "timed_out": bool(result.get("timed_out")),
        "session_error": bool(result.get("session_error")),
        # "pass" | "fail" | "unscorable" - see run_outcome(). Derived rather than stored blindly
        # so a backfilled historic row classifies the same way a live one does.
        "outcome": result.get("outcome") or run_outcome(result),
        "recorded_at": _now_utc(),
    }


def _row_key(row: dict) -> tuple:
    return (row.get("run_id"), row.get("case"), row.get("mode"))


def read_results(path: Path = RESULTS_FILE) -> list[dict]:
    """Existing rows in the append-only log (a malformed line is skipped, not fatal)."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_result(record: dict, path: Path = RESULTS_FILE) -> bool:
    """Append one row unless (run_id, case, mode) is already recorded. True if written.

    Append-only by contract: this never rewrites or reorders existing lines, so the file
    stays a chronological record rather than a snapshot.
    """
    if _row_key(record) in {_row_key(r) for r in read_results(path)}:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return True


def record_run_dir(root: Path, path: Path = RESULTS_FILE) -> int:
    """Backfill the log from saved run outputs; returns the number of rows appended.

    Accepts a runs root, a single run dir or a single case dir - anything with
    `score.json` / `score-rescore.json` beneath it. Layout assumed:
    `<runs>/<run_id>/<case>/score*.json`, so the run id comes from the case dir's parent.
    The version stamped is the one in the run's KEPT sandbox (the code actually under
    test); where the sandbox was pruned it is "unknown" rather than today's version.
    """
    files = sorted(root.rglob("score.json")) + sorted(root.rglob("score-rescore.json"))
    written = 0
    for score_file in files:
        try:
            result = json.loads(score_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict):
            continue
        mode = "rescore" if score_file.name == "score-rescore.json" else "run"
        result.setdefault("case", score_file.parent.name)
        written += append_result(
            result_record(
                result,
                score_file.parent.parent.name,
                mode=mode,
                version=_plugin_version(score_file.parent / "sandbox"),
            ),
            path,
        )
    return written


def _write_report(run_root: Path, results: list[dict]) -> Path:
    """Write `<run>/report.md`: the per-case scoreboard plus a draft verdict block.

    `results` are the per-case score dicts; returns the report path.
    """
    lines = [
        f"# Live /engage eval run - {run_root.name}",
        "",
        "| Case | Mode | Verdict | Recall | Must-find missed | Traps | Tripwires | Judge | "
        "Gates | Cost | Turns |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        det = r["deterministic"]
        jd = r.get("judge", {})
        jscore = jd.get("weighted_score", "-")
        lines.append(
            f"| {r['case']} | {r.get('mode', 'repo')} | {'PASS' if r['passed'] else 'FAIL'} "
            f"| {det.get('recall')} "
            f"| {', '.join(det.get('must_find_missed', [])) or '-'} "
            f"| {', '.join(det.get('false_positive_traps_triggered', [])) or '-'} "
            f"| {', '.join(det.get('tripwires_triggered', [])) or '-'} "
            f"| {jscore} | {r.get('gates_answered', '?')} | {r.get('cost_usd') or '?'} "
            f"| {r.get('num_turns') or '?'} |"
        )
    n_pass = sum(bool(r.get("passed")) for r in results)
    lines += [
        "",
        f"**{n_pass}/{len(results)} passed.** Per-case detail: `<case>/transcript.md`, "
        "`findings.json`, `score.json`, `gates.json`.",
        "",
        "## Baseline verdict block (draft)",
        "",
        "Paste into `evals/eval-baseline-<version>.md` and adjudicate the failures - the",
        "release gate parses this block and fails while any failure is unadjudicated.",
        "",
        verdict_block(results, run_root.name),
    ]
    report = run_root / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


# --------------------------------------------------------------------------- main
def _acquire_driver_lock() -> Path | None:
    """Single-driver lock (2026-07-28 incident: two concurrent drivers fight over the shared
    workspace-trust config in ~/.claude.json, so the loser's session runs UNTRUSTED - no
    project settings, no skills, no gates - while still spending tokens). Returns the lock
    path when acquired; raises SystemExit when another live driver holds it."""
    lock = RUNS_ROOT / ".driver.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_file():
        try:
            pid = int(lock.read_text().strip())
            os.kill(pid, 0)  # signal 0: existence check only
        except (ValueError, ProcessLookupError, PermissionError):
            lock.unlink(missing_ok=True)  # stale lock from a dead driver
        else:
            print(
                f"another eval driver is already running (pid {pid}) - concurrent drivers "
                "corrupt each other's workspace trust; wait for it or stop it first",
                file=sys.stderr,
            )
            raise SystemExit(2)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def main() -> int:
    # THIS DRIVER IS NOT THE SESSION IT WAS LAUNCHED FROM (2026-09-12). Started from inside
    # a Claude Code session it inherits that session's id and project directory, and every
    # stamp writer keys on those: building the first sandbox stamped the developer's live
    # session id into the real checkout's artifacts/ and armed the execution gate against
    # the session that launched the run. The driver stands in for a human at a terminal;
    # a human has neither variable.
    for var in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR"):
        os.environ.pop(var, None)
    ap = argparse.ArgumentParser(
        description="Run live /engage eval cases headlessly and score them."
    )
    ap.add_argument("--case", action="append", default=[], help="case id (repeatable)")
    ap.add_argument("--all-engage", action="store_true", help="every case with workflow: /engage")
    ap.add_argument("--list", action="store_true", help="list runnable cases and exit")
    ap.add_argument("--max-turns", type=int, default=100, help="session turn cap (default 100)")
    ap.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="override the per-case wall clock, in seconds, for EVERY case (0 = no wall clock). "
        f"Omit to let each case use its manifest's timeout_s, falling back to "
        f"{DEFAULT_TIMEOUT_S}s",
    )
    ap.add_argument(
        "--max-budget", type=float, default=None, help="per-case USD cap (SDK max_budget_usd)"
    )
    ap.add_argument(
        "--team-model",
        default="opus",
        help="tier for the ORCHESTRATOR under test (default opus, per the operating guide). "
        "Subagents always use their own model: frontmatter via setting_sources=['project']; "
        "this only sets Morgan's own tier",
    )
    ap.add_argument(
        "--sim-model", default="sonnet", help="model playing the stakeholder (default sonnet)"
    )
    ap.add_argument("--aux-model", default="sonnet", help="normalizer/judge model (default sonnet)")
    ap.add_argument("--skip-judge", action="store_true", help="deterministic scoring only")
    ap.add_argument(
        "--plugin-mode",
        action="store_true",
        help="run EVERY selected case the way the plugin is actually installed: a throwaway "
        "HOME (HOME + USERPROFILE + CLAUDE_CONFIG_DIR, so the real ~/.claude is neither read "
        "nor written), a marketplace registry and a CACHE copy of the plugin, and a CLIENT "
        "project as cwd that is empty apart from the case's fixtures. Hooks come from the "
        "plugin's own hooks/hooks.json via CLAUDE_PLUGIN_ROOT, not from this repo's "
        ".claude/settings.json. A case can declare it for itself with `mode: plugin`",
    )
    ap.add_argument(
        "--no-inherit-auth",
        action="store_true",
        help="plugin mode: do NOT copy credential material into the throwaway home. The "
        "session will be unauthenticated, so this is for layout inspection, not for a live "
        "run (see --dry-run)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="build each case's sandbox (or plugin-mode layout) and print the exact command "
        "that would be launched, then stop. No session, no tokens - the cheap way to check a "
        "layout on the Windows VM. The report is also written to <run>/<case>/dry-run.txt",
    )
    ap.add_argument(
        "--keep-sandbox", action="store_true", help="keep each case's sandbox for inspection"
    )
    ap.add_argument(
        "--exclude-subagent-output",
        action="store_true",
        help="capture only the PM's messages in the transcript (the pre-2026-08-01 view); by "
        "default subagent output is retained, tagged and per-block capped, so the judge "
        "scores the work rather than the narration of it",
    )
    ap.add_argument(
        "--record",
        help=f"backfill {RESULTS_FILE.name} from saved run outputs under this path "
        "(score.json / score-rescore.json), then exit - no live session, no tokens",
    )
    ap.add_argument(
        "--summary",
        action="store_true",
        help=f"print the trend summary from {RESULTS_FILE.name} and exit - pass rate over "
        "SCORABLE runs, with timed-out / errored runs counted separately rather than as "
        "quality failures. No live session, no tokens",
    )
    ap.add_argument(
        "--target-path",
        help="diagnostic mode (NOT a golden-case run, no scoring): run a live /engage session "
        "against a DISPOSABLE COPY of this external directory (never the live directory - the "
        "copy is discarded unless --keep-sandbox). Loads this plugin via the SDK's local-plugin "
        "mechanism (works regardless of cwd), pre-seeds large_context_review_split=true + "
        "regulatory_citations=false in the copy's team-preferences.json, and disallows the Bash "
        "tool outright for the session (static-only - no guard hooks are present in this mode "
        "since the target has no .claude/settings.json, so this is the actual enforcement, not "
        "the exec-consent marker). Writes transcript.md/events.jsonl/usage-series.jsonl/"
        "summary.json for human review under evals/runs/ (git-ignored). Override the opening ask "
        "with --target-prompt",
    )
    ap.add_argument(
        "--target-prompt",
        default=None,
        help="the /engage opening message for --target-path mode (default: a generic "
        "'review this codebase' ask)",
    )
    ap.add_argument(
        "--resume-run",
        help="path to a saved run's <case> dir with a KEPT sandbox: launch a fresh session in "
        "that sandbox with an uncoached 'resume and close' ask (cold resume from the artifacts "
        "state of record), then score the resulting combined state against the case manifest",
    )
    ap.add_argument(
        "--rescore",
        help="path to a saved run's <case> dir (transcript.md + sandbox/): re-run the scoring "
        "layers only - no live session, writes score-rescore.json alongside the original",
    )
    args = ap.parse_args()

    available = engage_cases()
    if args.list:
        print("\n".join(available))
        return 0

    if args.summary:
        rows = read_results()
        if not rows:
            print(f"no rows in {RESULTS_FILE.relative_to(REPO_ROOT)} yet")
            return 0
        s = summarise_results(rows)
        pr = s["pass_rate_scorable"]
        print(f"rows: {s['total']}   scorable: {s['scorable']}   unscorable: {s['unscorable']}")
        print(
            f"pass rate (scorable):  {s['passed']}/{s['scorable']}" + (f" = {pr:.0%}" if pr else "")
        )
        print(
            f"pass rate (all rows):  {s['passed']}/{s['total']} = {s['pass_rate_all']:.0%}"
            "   <- counts dead runs as failures; do NOT quote this as a quality number"
        )
        print(
            f"unscorable rate:       {s['unscorable_rate']:.0%} (harness health, not team quality)"
        )
        if s["unscorable"]:
            print("\nunscorable runs (no gradeable output - timeout or session error):")
            for r in rows:
                if (r.get("outcome") or run_outcome(r)) == "unscorable":
                    why = "timeout" if r.get("timed_out") else "session error"
                    print(f"  {r.get('run_id')}  {str(r.get('case'))[:32]:32s}  {why}")
        return 0

    if args.record:
        src = Path(args.record).resolve()
        if not src.is_dir():
            ap.error(f"{src} is not a directory of saved run outputs")
        added = record_run_dir(src)
        print(f"recorded {added} new row(s) into {RESULTS_FILE.relative_to(REPO_ROOT)}")
        return 0

    lock = _acquire_driver_lock()
    import atexit

    atexit.register(lambda: lock.unlink(missing_ok=True))

    if args.rescore:
        out_dir = Path(args.rescore).resolve()
        case_id = out_dir.name
        transcript_file = out_dir / "transcript.md"
        if not transcript_file.is_file():
            ap.error(f"{out_dir} has no transcript.md - not a saved run dir")
        # A --resume-run writes its output to "<case>-resume", which is not a case id. Strip the
        # suffix so rescoring a resumed run loads the right manifest instead of crashing.
        manifest = _load_case(
            case_id[: -len("-resume")] if case_id.endswith("-resume") else case_id
        )
        rubric = (RUBRICS_ROOT / f"{manifest['rubric']}.md").read_text(encoding="utf-8")
        result = asyncio.run(
            score_run(
                case_id,
                out_dir,
                rescore_project_root(out_dir),
                transcript_file.read_text(encoding="utf-8"),
                manifest,
                rubric,
                args,
            )
        )
        # Carry the ORIGINAL run's death flags forward. score_run only re-runs the scoring
        # layers, so it knows nothing about whether the session timed out or died; without this
        # a rescored dead run was recorded as a clean "pass" row in the trend log, quietly
        # converting an unscorable run into evidence of quality (review 2026-08-01).
        try:
            original = json.loads((out_dir / "score.json").read_text(encoding="utf-8"))
        except Exception:
            original = {}
        for flag in ("timed_out", "session_error", "error", "duration_s", "cost_usd", "num_turns"):
            if flag in original and flag not in result:
                result[flag] = original[flag]
        result["passed"] = bool(result.get("passed")) and not (
            result.get("timed_out") or result.get("session_error")
        )
        result["outcome"] = run_outcome(result)
        (out_dir / "score-rescore.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        append_result(result_record(result, out_dir.parent.name, mode="rescore"))
        det = result["deterministic"]
        print(
            f"{'PASS' if result['passed'] else 'FAIL'}  {case_id}  recall={det.get('recall')}  "
            f"traps={len(det.get('false_positive_traps_triggered', []))}  "
            f"judge={result.get('judge', {}).get('weighted_score', '-')}"
        )
        return 0 if result["passed"] else 1

    if args.target_path:
        run_root = RUNS_ROOT / _now_utc()
        run_root.mkdir(parents=True, exist_ok=True)
        print(f"run dir: {run_root}")
        summary = asyncio.run(run_target(Path(args.target_path), args, run_root))
        return 1 if (summary["timed_out"] or summary["session_error"]) else 0

    if args.resume_run:
        src = Path(args.resume_run).resolve()
        sandbox = src / "sandbox"
        if not sandbox.is_dir():
            ap.error(f"{src} has no kept sandbox/ - resume needs the original run's workspace")
        case_id = src.name.removesuffix("-resume")
        run_root = RUNS_ROOT / _now_utc()
        run_root.mkdir(parents=True, exist_ok=True)
        print(f"run dir: {run_root}")
        result = asyncio.run(
            run_case(
                case_id, args, run_root, sandbox_override=sandbox, scenario_override=_RESUME_PROMPT
            )
        )
        det = result["deterministic"]
        print(
            f"{'PASS' if result['passed'] else 'FAIL'}  {case_id} (resumed)  recall={det.get('recall')}  "
            f"traps={len(det.get('false_positive_traps_triggered', []))}  "
            f"judge={result.get('judge', {}).get('weighted_score', '-')}  cost=${result.get('cost_usd') or '?'}"
        )
        return 0 if result["passed"] else 1

    targets = available if args.all_engage else args.case
    if not targets:
        ap.error("give --case <id> (repeatable), --all-engage, or --list")
    unknown = [c for c in targets if c not in available]
    if unknown:
        ap.error(f"not /engage cases (see --list): {unknown}")

    if not args.dry_run:
        # A dry run never launches a session, so it must not need the SDK either - that is
        # what makes it usable on a Windows VM before anything else is set up there.
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            print(
                "claude-agent-sdk not importable - activate the repo venv: . .venv/bin/activate",
                file=sys.stderr,
            )
            return 2

    run_root = RUNS_ROOT / _now_utc()
    run_root.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {run_root}")

    results = []
    for case_id in targets:
        results.append(asyncio.run(run_case(case_id, args, run_root)))
        r = results[-1]
        if r.get("dry_run"):
            continue
        det = r["deterministic"]
        print(
            f"{'PASS' if r['passed'] else 'FAIL'}  {case_id}  recall={det.get('recall')}  "
            f"traps={len(det.get('false_positive_traps_triggered', []))}  "
            f"tripwires={','.join(det.get('tripwires_triggered', [])) or '-'}  "
            f"judge={r.get('judge', {}).get('weighted_score', '-')}  "
            f"gates={r['gates_answered']}  cost=${r.get('cost_usd') or '?'}"
        )

    if args.dry_run:
        print(f"\ndry run only - {len(results)} layout(s) built under {run_root}")
        return 0

    report = _write_report(run_root, results)
    n_pass = sum(r["passed"] for r in results)
    print(f"\n{n_pass}/{len(results)} passed - report: {report}")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
