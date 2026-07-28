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
Each full lifecycle run spends real tokens (it is a live engagement) - run at
milestones, not per commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from scripts.eval_score import score

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = REPO_ROOT / "evals" / "cases"
RUNS_ROOT = REPO_ROOT / "evals" / "runs"
RUBRICS_ROOT = REPO_ROOT / "evals" / "rubrics"
DEFAULT_PERSONA = REPO_ROOT / "evals" / "driver-default.md"

# Never copied into the sandbox. `evals/` is the load-bearing one: it holds the ground
# truth, and excluding it makes blindness structural rather than willpower.
SANDBOX_EXCLUDES = (
    ".git",
    ".venv",
    "artifacts",
    "evals",
    "__pycache__",
    ".pytest_cache",
    ".claude/.exec-consent",
    "node_modules",
)

# The sandbox session must stay hermetic: nothing it does may leave the box.
_NET_BASH_RE = re.compile(
    r"\b(git\s+push|git\s+fetch|git\s+pull|curl|wget|ssh|scp|gh\s|pip\s+install|npm\s+install)\b"
)
_NET_TOOLS = {"WebFetch", "WebSearch"}

_TRANSCRIPT_CAP = 80_000  # chars of transcript handed to the normalizer / judge

# A healthy headless session emits its first (System) message within seconds of spawn;
# two minutes of total silence means it will never speak (see the watchdog in run_case).
STARTUP_TIMEOUT_S = 120


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


def ensure_workspace_trust(path: Path) -> None:
    """Pre-accept the trust dialog for a sandbox path (headless runs cannot click it).

    Without trust, project settings are IGNORED - .claude skills would not load (no
    /engage) and, worse, the guard hooks under test would be silently disarmed. This is
    the remedy the CLI itself prints. Reverted by drop_workspace_trust() after the run.
    """
    cfg = _claude_cfg_path()
    data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.is_file() else {}
    data.setdefault("projects", {}).setdefault(str(path), {})["hasTrustDialogAccepted"] = True
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def drop_workspace_trust(path: Path) -> None:
    cfg = _claude_cfg_path()
    if not cfg.is_file():
        return
    data = json.loads(cfg.read_text(encoding="utf-8"))
    if data.get("projects", {}).pop(str(path), None) is not None:
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_sandbox(dest: Path) -> None:
    """Throwaway repo copy: guard hooks live, ground truth absent, git baseline committed."""
    args = ["rsync", "-a", "--delete"]
    for ex in SANDBOX_EXCLUDES:
        args += ["--exclude", ex]
    args += [f"{REPO_ROOT}/", f"{dest}/"]
    subprocess.run(args, check=True, capture_output=True)
    (dest / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (dest / "artifacts").mkdir(exist_ok=True)
    env_git = ["git", "-C", str(dest), "-c", "user.email=eval@local", "-c", "user.name=eval-harness"]
    subprocess.run([*env_git[:3], "init", "-q"], check=True, capture_output=True)
    subprocess.run([*env_git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*env_git, "commit", "-qm", "eval sandbox baseline"], check=True, capture_output=True)


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
        # Per-case env (expected.yaml `session_env:`) lets a golden case exercise
        # human-side environment mechanisms (e.g. CST_COMPANY_ALLOW) - the harness is the
        # human here, same standing as the consent-marker creation (ADR-002).
        env={**_session_env(), **(extra_env or {})},
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
        if q_text not in answers or not answers[q_text]:
            opts = q.get("options") or []
            answers[q_text] = opts[0]["label"] if opts else "Proceed"
        sim_log.exchanges.append({"question": q_text, "header": q.get("header"), "answer": answers[q_text]})
        _maybe_grant_consent(q, answers[q_text], sandbox, sim_log)
    return answers


def _flatten_answer(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _maybe_grant_consent(question: dict, answer: str, sandbox: Path, sim_log: SimTranscript) -> None:
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
    extra_env: dict[str, str] | None = None,
) -> SessionCapture:
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
            return PermissionResultAllow(
                updated_input={"questions": questions, "answers": answers}
            )
        return PermissionResultAllow(updated_input=input_data)

    options = ClaudeAgentOptions(
        cwd=str(sandbox),
        setting_sources=["project"],
        # "default", not "acceptEdits": every tool call must route through can_use_tool -
        # acceptEdits short-circuits some calls past the callback, and AskUserQuestion then
        # dies with no interactive user attached (observed in the first smoke run).
        permission_mode="default",
        can_use_tool=can_use_tool,
        max_turns=max_turns,
        max_budget_usd=max_budget,
        env=_session_env(),
        # Headless runs otherwise bash-sandbox with no network and no user-site packages
        # (observed: `import markdown` failed inside the session while fine outside, so
        # render_html "could not" run). Interactive engagements are not sandboxed like
        # that; matching them keeps the eval faithful. Network hygiene stays enforced by
        # the _NET_BASH_RE deny in can_use_tool.
        sandbox={"enabled": False},
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
        cap.events.append({"type": msg_type, "repr": repr(message)[:4000]})
        if isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
            for block in message.content:
                if isinstance(block, TextBlock):
                    cap.transcript.append(block.text)
                elif isinstance(block, ToolUseBlock) and block.name != "AskUserQuestion":
                    hint = str(block.input.get("description") or block.input.get("subagent_type") or "")[:120]
                    cap.transcript.append(f"\n[tool] {block.name} {hint}\n")
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
            result_pending = True
        if result_pending and not inflight:
            grace = asyncio.create_task(_grace_close())
    if grace is not None:
        grace.cancel()
    session_done.set()
    return cap


# --------------------------------------------------------------------------- scoring
def probe_artifacts(sandbox: Path) -> list[dict]:
    """Deterministic, code-level findings from what the run actually left on disk."""
    findings: list[dict] = []
    art = sandbox / "artifacts"
    if not art.is_dir():
        return findings

    # 0.31 workspaces: an engagement's pack may live at artifacts/<slug>/ instead of the
    # flat root - probe every pack (flat root first for pre-0.31 runs).
    packs = [art] + sorted(
        p for p in art.iterdir()
        if p.is_dir() and (p / "engagement-state.json").is_file()
    )

    for txt in sorted(art.rglob("*.txt")):
        body = txt.read_text(encoding="utf-8", errors="ignore")
        if "morgan" in body.lower():
            title = 'engagement-summary email written as .txt, signed as Morgan'
            if '"hi,"' in body.lower() or body.lstrip().lower().startswith("hi,") or "\nhi," in body.lower():
                title += ", opens 'Hi,'"
            findings.append(
                {"severity": "warning", "location": f"artifacts/{txt.name}", "title": title, "kind": "artifact"}
            )

    for pack in packs:
        where = f"artifacts/{pack.name}/" if pack != art else "artifacts/"
        start_here = pack / "START-HERE.md"
        if start_here.is_file():
            text = start_here.read_text(encoding="utf-8", errors="ignore")
            status = next(
                (ln.strip() for ln in text.splitlines() if "status" in ln.lower()), ""
            )
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


def _artifact_listing(sandbox: Path) -> str:
    art = sandbox / "artifacts"
    if not art.is_dir():
        return "(no artifacts/ directory)"
    return "\n".join(str(p.relative_to(sandbox)) for p in sorted(art.rglob("*")) if p.is_file()) or "(empty)"


async def normalize(transcript: str, listing: str, model: str) -> list[dict]:
    reply = await _one_shot(
        f"{_NORMALIZER_PROMPT}\n## Artifact files\n{listing}\n\n## Transcript\n{transcript[-_TRANSCRIPT_CAP:]}",
        model,
    )
    findings = [
        f for f in _extract_json(reply).get("findings", []) if isinstance(f, dict) and f.get("title")
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
        f"## Transcript\n{transcript[-_TRANSCRIPT_CAP:]}",
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
    persona = (persona_file if persona_file.is_file() else DEFAULT_PERSONA).read_text(encoding="utf-8")
    rubric = (RUBRICS_ROOT / f"{manifest['rubric']}.md").read_text(encoding="utf-8")

    out_dir = run_root / (f"{case_id}-resume" if sandbox_override else case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    if sandbox_override is not None:
        sandbox = sandbox_override  # shared, pre-existing state - never rebuilt, never deleted
        print(f"  [{case_id}] resuming in kept sandbox {sandbox}")
        args.keep_sandbox = True
    else:
        sandbox = out_dir / "sandbox"
        print(f"  [{case_id}] building sandbox...")
        build_sandbox(sandbox)
        # Optional case fixtures: a `fixtures/` tree is overlaid sandbox-relative (e.g.
        # fixtures/artifacts/x.md -> sandbox/artifacts/x.md), so a case can seed a REAL
        # drifted/partial engagement state for the session to act on. A described-only state
        # invites a plan instead of actions (first live run of process-close-reconciliation:
        # Morgan correctly refused to "fix" files that did not exist). Never overlaid on a
        # resume - the kept sandbox IS the state.
        fixtures = case_dir / "fixtures"
        if fixtures.is_dir():
            subprocess.run(
                ["rsync", "-a", f"{fixtures}/", f"{sandbox}/"], check=True, capture_output=True
            )
    ensure_workspace_trust(sandbox)

    sim_log = SimTranscript()
    cap = SessionCapture()
    started = time.monotonic()
    print(f"  [{case_id}] running live /engage session (cap {args.max_turns} turns"
          f"{f', ${args.max_budget}' if args.max_budget else ''})...")
    try:
        await asyncio.wait_for(
            run_engage_session(
                cap, scenario, sandbox, persona, args.sim_model, args.max_turns, args.max_budget, sim_log,
                workflow_cmd=workflow_cmd,
                extra_env={str(k): str(v) for k, v in (manifest.get("session_env") or {}).items()},
            ),
            timeout=args.timeout if args.timeout > 0 else None,  # 0 = no wall clock; budget is the stop
        )
    except asyncio.TimeoutError:
        cap.timed_out = True
        print(f"  [{case_id}] TIMED OUT after {args.timeout}s - scoring what exists", file=sys.stderr)
    except Exception as exc:  # session died - score whatever it left behind, report the error
        cap.is_error = True
        cap.error = f"{type(exc).__name__}: {exc}"
        print(f"  [{case_id}] SESSION ERROR: {cap.error}", file=sys.stderr)
    finally:
        drop_workspace_trust(sandbox)
    duration = time.monotonic() - started

    transcript = "".join(cap.transcript)
    (out_dir / "transcript.md").write_text(transcript, encoding="utf-8")
    (out_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in cap.events), encoding="utf-8"
    )
    (out_dir / "gates.json").write_text(
        json.dumps({"consent_granted": sim_log.consent_granted, "exchanges": sim_log.exchanges}, indent=2),
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
            "error": cap.error,
            "duration_s": round(duration, 1),
        }
    )
    result["passed"] = result["passed"] and not cap.timed_out and not cap.is_error
    (out_dir / "score.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    if not args.keep_sandbox:
        shutil.rmtree(sandbox, ignore_errors=True)
    return result


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
    findings = probe_artifacts(sandbox)
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
            print(f"  [{case_id}] normalizer empty twice - deterministic findings only", file=sys.stderr)
    (out_dir / "findings.json").write_text(json.dumps({"findings": findings}, indent=2), encoding="utf-8")

    expected = {k: v for k, v in manifest.items() if not k.startswith("_")}
    det = score(expected, findings)

    judge_result: dict = {"skipped": True}
    if not args.skip_judge:
        for attempt in (1, 2):
            try:
                judge_result = await judge(transcript, listing, rubric, args.aux_model)
                break
            except Exception as exc:
                judge_result = {"error": f"{type(exc).__name__}: {exc}", "pass": False}
                print(f"  [{case_id}] judge attempt {attempt} failed: {exc}", file=sys.stderr)

    return {
        "case": case_id,
        "passed": bool(det.get("passed")) and bool(judge_result.get("pass", True)),
        "deterministic": det,
        "judge": judge_result,
    }


def _write_report(run_root: Path, results: list[dict]) -> Path:
    lines = [
        f"# Live /engage eval run - {run_root.name}",
        "",
        "| Case | Verdict | Recall | Must-find missed | Traps | Judge | Gates | Cost | Turns |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        det = r["deterministic"]
        jd = r.get("judge", {})
        jscore = jd.get("weighted_score", "-")
        lines.append(
            f"| {r['case']} | {'PASS' if r['passed'] else 'FAIL'} | {det.get('recall')} "
            f"| {', '.join(det.get('must_find_missed', [])) or '-'} "
            f"| {', '.join(det.get('false_positive_traps_triggered', [])) or '-'} "
            f"| {jscore} | {r['gates_answered']} | {r.get('cost_usd') or '?'} | {r.get('num_turns') or '?'} |"
        )
    n_pass = sum(r["passed"] for r in results)
    lines += ["", f"**{n_pass}/{len(results)} passed.** Per-case detail: `<case>/transcript.md`, "
              "`findings.json`, `score.json`, `gates.json`."]
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
    ap = argparse.ArgumentParser(description="Run live /engage eval cases headlessly and score them.")
    ap.add_argument("--case", action="append", default=[], help="case id (repeatable)")
    ap.add_argument("--all-engage", action="store_true", help="every case with workflow: /engage")
    ap.add_argument("--list", action="store_true", help="list runnable cases and exit")
    ap.add_argument("--max-turns", type=int, default=100, help="session turn cap (default 100)")
    ap.add_argument("--timeout", type=int, default=2400, help="per-case wall clock seconds (default 2400)")
    ap.add_argument("--max-budget", type=float, default=None, help="per-case USD cap (SDK max_budget_usd)")
    ap.add_argument("--sim-model", default="sonnet", help="model playing the stakeholder (default sonnet)")
    ap.add_argument("--aux-model", default="sonnet", help="normalizer/judge model (default sonnet)")
    ap.add_argument("--skip-judge", action="store_true", help="deterministic scoring only")
    ap.add_argument("--keep-sandbox", action="store_true", help="keep each case's sandbox for inspection")
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

    lock = _acquire_driver_lock()
    import atexit

    atexit.register(lambda: lock.unlink(missing_ok=True))

    if args.rescore:
        out_dir = Path(args.rescore).resolve()
        case_id = out_dir.name
        transcript_file = out_dir / "transcript.md"
        if not transcript_file.is_file():
            ap.error(f"{out_dir} has no transcript.md - not a saved run dir")
        manifest = _load_case(case_id)
        rubric = (RUBRICS_ROOT / f"{manifest['rubric']}.md").read_text(encoding="utf-8")
        result = asyncio.run(
            score_run(
                case_id,
                out_dir,
                out_dir / "sandbox",
                transcript_file.read_text(encoding="utf-8"),
                manifest,
                rubric,
                args,
            )
        )
        (out_dir / "score-rescore.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        det = result["deterministic"]
        print(
            f"{'PASS' if result['passed'] else 'FAIL'}  {case_id}  recall={det.get('recall')}  "
            f"traps={len(det.get('false_positive_traps_triggered', []))}  "
            f"judge={result.get('judge', {}).get('weighted_score', '-')}"
        )
        return 0 if result["passed"] else 1

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
            run_case(case_id, args, run_root, sandbox_override=sandbox, scenario_override=_RESUME_PROMPT)
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

    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        print("claude-agent-sdk not importable - activate the repo venv: . .venv/bin/activate", file=sys.stderr)
        return 2

    run_root = RUNS_ROOT / _now_utc()
    run_root.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {run_root}")

    results = []
    for case_id in targets:
        results.append(asyncio.run(run_case(case_id, args, run_root)))
        r = results[-1]
        det = r["deterministic"]
        print(
            f"{'PASS' if r['passed'] else 'FAIL'}  {case_id}  recall={det.get('recall')}  "
            f"traps={len(det.get('false_positive_traps_triggered', []))}  "
            f"judge={r.get('judge', {}).get('weighted_score', '-')}  "
            f"gates={r['gates_answered']}  cost=${r.get('cost_usd') or '?'}"
        )

    report = _write_report(run_root, results)
    n_pass = sum(r["passed"] for r in results)
    print(f"\n{n_pass}/{len(results)} passed - report: {report}")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
