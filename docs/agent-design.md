# Agent design & best-practice conformance

> This team is meant to be a **worked example of how to build a good Claude Code agent set-up**.
> This doc states the design principles, the model-tiering rationale, and a conformance matrix
> against current Claude Code / Anthropic "Building Effective Agents" guidance — so the choices
> are deliberate and auditable, not accidental.

## 1. Design principles

1. **Single, clear responsibility per agent.** Each subagent owns one focused role with stated
   scope boundaries (what *another* agent owns). Overlaps are removed, not tolerated (e.g.
   `data-analyst` does exploratory/FP/MI work and **cedes threshold calibration to
   `tuning-analyst`**).
2. **Least privilege, enforced by `tools:`.** Every agent declares its tools explicitly. **All
   advisory/reviewer agents are read-only** (no `Write`/`Edit`) — that independence is a *tool
   grant*, not a polite request. Build agents get exactly what they need (analysts hold `Write`
   for their own scripts but **not** `Edit`, so they never alter live detection source).
3. **Match the model to the work (see §2).** Cheap tier for mechanical, top tier only where it
   changes outcomes.
4. **Right-size every engagement.** Multi-agent costs ~15× the tokens; the PM uses the *leanest*
   set that fits (a narrow change → one builder + one reviewer, not the whole team) and states the
   intended agent count out loud at the gate (CLAUDE.md §6).
5. **Coordinate through artifacts, not chatter (the "blackboard").** Subagents can't talk to each
   other — only to the orchestrator. Shared state lives in the Delivery Report / RTM / specs; each
   step's output is the next step's input.
6. **Safety in hooks, not prose.** True guardrails (raw-data block, code-execution gate) are
   **PreToolUse hooks** — hard enforcement the model can't override. Prose rules (CLAUDE.md) carry
   *quality* guidance only.
7. **Independent verification.** `model-validator` is independent of `ml-engineer`; `qa-engineer`
   doesn't mark its own homework; the PM (opus) re-challenges every agent's findings.

## 2. Model-tiering rationale

**Principle.** The orchestrator (**Morgan**) runs on **opus** and independently re-scrutinises every
agent's *findings* — so there's already a top-tier backstop at the synthesis layer. Therefore reserve
opus for judgment that is **(a) the final, independent word with no downstream re-check**, **(b) deep/
subtle enough that a miss is costly and hard to catch**, or **(c) genuinely novel design**. Everything
evidenced and re-checkable → **sonnet**. Purely mechanical → **haiku**.

| Agent | Tier | Why this tier |
|---|---|---|
| `model-validator` | **opus** | The *last word* on model soundness; adversarial; nobody re-checks it. |
| `compliance-reviewer` | **opus** | Final audit/DoD gate before handover; a missed audit-trail/secret/PII is high-consequence and unchecked downstream. |
| `code-reviewer` | **opus** | Subtle cross-language **security** judgement analysers miss; high blast radius. |
| `ml-engineer` | **opus** | Novel ML/NLP **design**; subtle failure modes (leakage, overfitting) are cheaper to avoid than to catch and re-do. |
| `business-analyst` | sonnet | Structured elicitation/spec work; re-checked by SMEs, reviewers and the PM. |
| `rules-developer` | sonnet | Detection code + tests; independently reviewed (code + compliance) before merge. |
| `data-analyst` | sonnet | Evidenced exploratory analysis/MI; figures are checkable. |
| `tuning-analyst` | sonnet | Threshold calibration backed by **evidence** (ATL/BTL, dry-run) and re-checked by `model-validator`/PM. |
| `platform-engineer` | sonnet | Well-trodden pipeline/ETL/infra patterns. |
| `qa-engineer` | sonnet | Methodical, structured test design + evidence. |
| `tm-sme` · `trade-surveillance-sme` · `comms-surveillance-sme` | sonnet | Knowledge-heavy **advice**, re-challenged by the PM, builders and reviewers — not deep unchecked reasoning. |
| `performance-reviewer` | sonnet | **Static-only** (profilers removed): bounded Big-O / query-shape / memory reasoning sonnet handles well. |
| `data-quality-reviewer` | sonnet | Structured coverage mapping + reconciliation; checklist-driven. |
| `review-scorer` | **haiku** | Purely mechanical — context detection, lens selection, scoring, tallies. |

**Net: 4 opus · 11 sonnet · 1 haiku.** The two next-cheapest swing choices are `code-reviewer` and
`ml-engineer` (both have a backstop — analysers + PM, and `model-validator` respectively); drop them
to sonnet if cost must be pushed harder, accepting a small risk on deep security/model-design quality.

## 3. Deliberate deviations from the generic guidance

- **No "use proactively" in descriptions — on purpose.** The generic advice is to add "use
  proactively" so Claude auto-delegates. This team is **dormant-by-default / opt-in** (it must behave
  as standard Claude Code until invoked), so descriptions say *"When the team is engaged, use for…"*
  — a *when-to-use* trigger **without** inviting auto-activation outside team context.
- **Explicit `model:` on every agent (not `inherit`).** Inheriting the session model is the generic
  default, but a *team* wants deterministic cost control, so each agent pins its tier per §2.

## 4. Why 16 agents (and not fewer / more)

16 is at the upper end of "manageable", justified by the **breadth of deliverables** (detection
rules, pipelines, ETL, ML, reviews across 7 languages, three surveillance domains, independent
validation/QA/DQ). The over-fragmentation risk is controlled by: removing real overlaps (the
`data-analyst`/`tuning-analyst` boundary), distinct non-colliding descriptions, and the right-sizing
rule so a given task fires 2–3 agents, never all 16. We did **not** add agents for thin slices (no
separate SecOps agent — folded into `code-reviewer` + `platform-engineer`).

## 5. Conformance matrix (vs Claude Code subagent guidance)

| Best-practice item | Status | How |
|---|---|---|
| Frontmatter complete (name·description·tools·model) | ✅ | All 16. |
| `tools:` least-privilege; advisors read-only | ✅ | Verified — zero advisors hold Write/Edit. |
| Description = clear when-to-use trigger | ✅ | Standardised "When the team is engaged, use for…"; overlaps removed. |
| Model tiering (not all-one-tier; documented) | ✅ | §2 above; 4/11/1 split. |
| Reasonable agent count / no routing collisions | ✅ | §4; one historical overlap fixed. |
| Orchestration: simplest pattern that fits | ✅ | Routing + orchestrator-workers via `/engage`; right-sizing doctrine. |
| Non-overlapping delegation briefs | ✅ | PM gives objective · scope · inputs · output format (engage §5). |
| Coordinate via artifacts, not peer chatter | ✅ | Blackboard: Delivery Report / RTM. |
| Safety via hooks, not prompt-only | ✅ | `guard-raw-data.py` + `guard-code-execution.py` (PreToolUse). |
| Observability | ✅ | PM marks every turn 🎩; states agent count at the gate. |
| Avoid anti-patterns (monolith, over-planning, weak delegation, exec-without-consent) | ✅ | Specialised roles; lean intake; explicit briefs; execution gated by §7. |

*Maintenance: when you add/retier an agent, update §2 and the per-agent `model:` together; the
`tests/` and this matrix are the guard against drift.*

## 6. Anthropic multi-agent standards — conformance

> Audited against Anthropic's published guidance (links in §7). We arrived at most of these
> independently. Honest status: ✅ conform · 🟡 partial or a deliberate fit to our *interactive,
> human-gated* model · ➖ not applicable at our scale.

| Anthropic multi-agent standard | Status | How we meet it (or why it differs) |
|---|---|---|
| Simplest thing that works; multi-agent only when it improves outcomes | ✅ | Right-sizing doctrine (CLAUDE.md §6); a narrow change uses 1 builder + 1 reviewer, not the team. |
| **Orchestrator-worker** (lead plans, workers act as filters) | ✅ | `/engage` — the PM decomposes, delegates, and synthesises. |
| Delegate with **objective · output format · tools/sources · boundaries** | ✅ | CLAUDE.md §6 + `engage` §5 require exactly those four. |
| Subagents **inherit no parent history** — put every input in the brief | ✅ | Stated in CLAUDE.md §6 delegation. |
| Never vague briefs (they cause duplicated work / gaps) | ✅ | "the #1 failure is weak delegation" (CLAUDE.md §6). |
| **Scale effort to complexity**; state the number of agents | ✅ | PM states intended agent count + why at the gate (`engage` §5). |
| Budget **~15× tokens**; reserve multi-agent for high value | ✅ | "~15× the tokens" cited verbatim (CLAUDE.md §6). |
| **Tier models per role** (cheap routine, strong high-stakes) | ✅ | §2 — 4 opus / 11 sonnet / 1 haiku. |
| Return **condensed results**; persist big outputs as **artifacts**, not via the orchestrator's context | ✅ | Blackboard: agents write the Delivery Report / RTM; the PM synthesises. |
| **Restrict tools per subagent** (limit blast radius) | ✅ | Least privilege; all advisors read-only. |
| Guard the failure modes (over-spawn · duplicate · runaway · premature stop) | ✅ | Right-size + state-count (over-spawn); non-overlapping briefs (duplicate); fix-loop stop conditions (runaway); never-dead-end (premature stop). |
| Don't multi-agent when agents **share context / are tightly dependent** | 🟡 | We do multi-agent *coding* but via **chaining** (build → review), not parallel fan-out on interdependent code — the safe form of it. |
| Humans in the loop; evals **early & small** | ✅ | Human sign-off (Definition of Done); PM returns at every gate; `tests/` is the small eval set. |
| **External memory** for long horizons | ✅ | `docs/house-rules.md` — committed, compounding team memory; subagent context isolation. |
| **LLM-as-judge** rubric for output quality | 🟡 | We use a **reviewer + Definition-of-Done** model (code/compliance/QA + the PM re-challenging findings) rather than a 0–1 judge prompt — a valid equivalent for build/review work; the rubric form suits open-ended research. *Candidate enhancement: an explicit eval harness.* |
| Subagent **self-assessment** (plan → evaluate → refine) | ✅ | Team-wide convention (CLAUDE.md §6): every agent self-verifies against its brief and **flags gaps** before returning, rather than implying completeness it doesn't have. |
| **Production tracing** / end-state checkpoints | 🟡 | Interactive model: PM 🎩 attribution + a short status log + user gates, rather than autonomous tracing (which matters most for long-running headless agents). |
| **Dozens–hundreds** of agents → orchestrate via a **script/Workflow** | ➖ | Not applicable — right-sizing keeps us at 2–5 agents per engagement; we never reach that scale. |

**Net:** strong conformance on the high-value lessons. The remaining 🟡s are deliberate fits to our
*interactive, human-gated* delivery model (vs Anthropic's long-running autonomous research agent).
The one open enhancement is an **LLM-judge eval harness** (see the README roadmap) — self-assessment
is now a team convention (CLAUDE.md §6).

## 7. References (Anthropic agent guidance)

- **Building Effective Agents** — https://www.anthropic.com/engineering/building-effective-agents
- **How we built our multi-agent research system** — https://www.anthropic.com/engineering/multi-agent-research-system
- **Effective context engineering for AI agents** — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- **Subagents (Claude Agent SDK)** — https://code.claude.com/docs/en/agent-sdk/subagents
- **Claude Code subagents** — https://code.claude.com/docs/en/subagents

*Evidence note: the "~15×-token" and "90.2% better" figures come from Anthropic's internal research
eval — directional, not independently reproduced; the effort-scaling numbers are research-domain
rules of thumb. We cite them as calibration, not law.*
