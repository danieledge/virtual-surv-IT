# Research: building a virtual engineering team (2026-06-20)

Deep-research synthesis (27 sources, 24/25 claims verified against primary sources) on how to
design an AI "virtual engineering team", used to refine this repo. Sources cited inline.

## Headline

Our **orchestrator-worker shape (Morgan + specialists)** is the *validated* pattern - it's
exactly Anthropic's architecture, which beat single-agent Opus 4 by **90.2%** on their
research eval ([multi-agent-research-system](https://www.anthropic.com/engineering/multi-agent-research-system),
[subagents docs](https://docs.anthropic.com/en/docs/claude-code/subagents)). The frameworks
(MetaGPT, ChatDev, AgentMesh) converge on the same lessons we've partly implemented:
SOP/role decomposition, artifact-centric coordination, independent critics.

**But two caveats apply directly to us:**
1. **Cost & fit.** Multi-agent uses **~15× more tokens**, and token use alone explains ~80%
   of performance variance; it's only worth it for **high-value** work and is a **poor fit
   for tightly-coupled coding** where context must be shared. Anthropic and Cognition both say
   *start simple, add agents only when they demonstrably help*
   ([building-effective-agents](https://www.anthropic.com/research/building-effective-agents),
   [Cognition: don't build multi-agents](https://cognition.ai/blog/dont-build-multi-agents)).
2. **Right-sizing.** No source benchmarks team size for software delivery; a lean 4-6 role
   pipeline (AgentMesh) may match or beat a 13-agent team for a single coding task. Our
   breadth is justified for *broad* compliance deliverables, not for a one-file edit.

## Evidence-backed refinements (mapped to our setup)

| # | Refinement | Why (source) | Maps to |
|---|---|---|---|
| 1 | **Harden orchestrator delegation** - Morgan must emit explicit, **non-overlapping task briefs** per subagent (objective, scope boundaries, output format) and not over-spawn | The #1 failure mode: weak delegation → agents duplicate work, leave gaps, spawn 50 subagents for trivial queries ([Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)) | CLAUDE.md §6, `/engage`, `/build-solution` |
| 2 | **Right-size / start-simple rule** - use the leanest agent set that fits; reserve full fan-out for high-value/broad work; for tightly-coupled coding use one builder + one reviewer | ~15× cost; poor fit for shared-context coding; start simple ([Anthropic](https://www.anthropic.com/research/building-effective-agents), [Cognition](https://cognition.ai/blog/dont-build-multi-agents)) | CLAUDE.md §6 (already dormant/flexible - make explicit) |
| 3 | **Model tiering** - cheap models (haiku/sonnet) for narrow reviewers & mechanical steps (detect/score/filter), opus only for judgement | Token use drives cost; best practice to set per-agent model ([subagents docs](https://docs.anthropic.com/en/docs/claude-code/subagents)) | all reviewer agents |
| 4 | **Verification as hooks, not prompts** - encode the Definition of Done (run tests, data-safety checks) as `PostToolUse`/`Stop` hooks so it's automatic | Hooks run tests after edits / lint before commits ([autonomy post](https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously)) | DoD, `.claude/hooks/` |
| 5 | **Artifact "blackboard" discipline** - agents read/write the shared artifact set (delivery-report, RTM) rather than rely on conversational context | Artifact-centric coordination beats chatty agent-to-agent messaging ([AgentMesh](https://arxiv.org/pdf/2507.19902)) | delivery-report.md, RTM |
| 6 | **commands → skills migration** ✅ done - Anthropic recommends `skills/` over the legacy `commands/`; workflows moved to `.claude/skills/<name>/SKILL.md`, plugin manifest updated, validated | [plugins docs](https://platform.claude.com/docs/en/agent-sdk/plugins) | `.claude/skills/` |
| 7 | **Diff-style fixes + least-privilege audit** (also a turingmind finding) | best practice: detailed descriptions, least-privilege tools ([subagents docs](https://docs.anthropic.com/en/docs/claude-code/subagents)) | code-reviewer, all agents |

## Concrete examples worth studying / borrowing

- **wshobson/agents** - large production-grade subagent collection - <https://github.com/wshobson/agents>
- **VoltAgent/awesome-claude-code-subagents** - curated subagent library - <https://github.com/VoltAgent/awesome-claude-code-subagents>
- **0ldh/claude-code-agents-orchestra** - an orchestrated multi-agent team - <https://github.com/0ldh/claude-code-agents-orchestra>
- **hesreallyhim/awesome-claude-code** - index of Claude Code resources - <https://github.com/hesreallyhim/awesome-claude-code>
- **anthropics/claude-code - code-review plugin** - official reference - <https://github.com/anthropics/claude-code/blob/main/plugins/code-review/README.md>
- **OpenBMB/ChatDev**, **MetaGPT (deepwisdom)** - academic role maps

## What was refuted / uncertain

- **Refuted (1-2):** the tidy "five Building-Effective-Agents patterns map 1:1 to our slash
  commands" framing - don't assume the mapping; our commands are our own composition.
- The 90.2% lift is a **self-reported** eval on a *research* (not coding) task - directional,
  not proof a 13-agent coding team wins.
- AgentMesh's coverage advantage is **anecdotal**, not benchmarked.
- Claude Code primitives evolve fast - re-verify skills/commands/hooks schema before migrating.

## Open questions
- Does the full team beat a lean 4-6 role pipeline for *our* domain? (unbenchmarked)
- What eval harness/rubric should gate the DoD beyond confidence-scored review?
