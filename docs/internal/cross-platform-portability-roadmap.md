# Cross-platform portability - running this team under Copilot as well as Claude Code (2026-08-04)

> Status: **not started, not committed to.** This is a research-and-plan doc written to survive a
> context clear, not a decision record. Read this fresh, verify the "open questions" before
> building anything, and update this file as those get answered.

## The ask

Let people run this team (skills, subagents, the mechanical safety hooks) under **GitHub Copilot
CLI** as well as the Claude Code CLI/plugin, without forking the project or weakening the safety
model that took real hardening work to get right (see tonight's session: the quote-aware
segment-splitting fix in `guard-code-execution.py`/`guard-raw-data.py`, the scoped-Write guard for
the four reviewers, the compliance-reviewer routing fix). **Whatever we build must not create a
SECOND copy of the safety logic that can independently drift from the first** - that is exactly the
failure mode `docs/DEFINITION-OF-DONE.md` vs `build-solution/SKILL.md` fell into tonight, just at
repo-doc scale instead of platform scale.

## What's actually portable - verified 2026-08-04, not assumed

Researched live (WebSearch + a direct WebFetch of GitHub's hooks reference) rather than taken from
training-data memory, because this space moves fast and memory here would likely be stale.

| Layer | Claude Code | Copilot CLI (GA Feb 2026) | Portability verdict |
|---|---|---|---|
| **Skills** (`SKILL.md`) | `.claude/skills/<name>/SKILL.md` | **Confirmed via direct doc fetch (2026-08-04): Copilot CLI reads project skills from `.github/skills`, `.claude/skills`, OR `.agents/skills` natively** - no mirroring, no build step. Personal (cross-project) skills live in `~/.copilot/skills` or `~/.agents/skills`. | **High, and now verified, not just likely.** This repo's existing `.claude/skills/*/SKILL.md` files should work on Copilot CLI **as-is, zero path changes** - this was the biggest open question and it resolved in the best possible direction. |
| **Hooks** (safety guards) | `.claude/hooks/*.py` + `hooks/hooks.json`; `PreToolUse` fires before a tool call, stdout `{"decision":"block","reason":...}` blocks it; crash = fail-closed by this repo's own convention | `.github/hooks/*.json`; `preToolUse` fires before a tool call, stdout `{"permissionDecision":"deny"|"allow"|"ask"}` blocks it; **a hook crash or non-zero exit also fails closed (denies), verified via direct doc fetch** - the one exception is a timeout, which fails open | **Medium.** The *shape* is the same (JSON stdin in, JSON stdout out, can veto, fails closed on crash) - genuinely good news, this was not a safe assumption going in. The *contract* differs (`tool_name`/`tool_input` vs `toolName`/`toolArgs`; `decision:"block"` vs `permissionDecision:"deny"`). Buildable as: refactor each guard's actual decision logic into one platform-agnostic function, write a thin adapter per platform that translates the JSON shape. Do NOT hand-port the guard files and let two copies of the regex/segment-splitting logic exist. **Caveat found 2026-08-04: the documented `preToolUse` payload has no agent-identity field at all** (see open question 4 - now answered, not just asked). |
| **Subagents** (16-agent roster, per-agent tool/model scoping) | `.claude/agents/*.md`, `tools:`/`model:` frontmatter, mechanically enforced (e.g. `guard-findings-pack-write.py` scoping four reviewers' Write to their own JSON) | Copilot "custom agents": `name`, `prompt`, `tools` (string[] or null - null means all tools), `model`, `mcpServers`, `infer`, `skills`, `reasoningEffort`. Coarse allow-list confirmed via direct doc fetch, e.g. a read-only agent declares `tools: ["grep","glob","view"]` and simply has no `edit`/`write`/`bash` in the list. | **Medium - upgraded from "unknown," and the answer is split.** The coarse grant (advisory agent never gets `write` at all) **is portable** - straightforward equivalent of this repo's `tools:` frontmatter. The FINE grant is not: `guard-findings-pack-write.py` doesn't just deny Write, it scopes ALLOWED Write to one specific path (`artifacts/<slug>/data/findings-*.json`) for four specific agents while every other agent gets none - a per-agent, per-path predicate. Copilot's `tools` array has no path predicate, and (per open question 4 below) the hook layer that could backstop it has no agent-identity field either. **This specific mechanism has no confirmed Copilot equivalent yet.** |
| **MCP** | Supported | Universally supported across major agents per 2026 sources | Not currently used by this repo's own architecture (no custom MCP servers here), so not a live migration concern, but worth knowing it's there if a future integration needs it. |

## Non-negotiables (whatever gets built)

- **One source of truth for guard logic, not one per platform.** A guard's actual decision
  function (what counts as a raw-data path, what counts as a code-execution verb, the quote-aware
  segment splitter) lives once, in platform-agnostic Python; each platform gets a thin adapter that
  only translates the JSON contract in/out. Never a second hand-written copy of the regex/logic -
  see tonight's `guard-code-execution.py`/`guard-raw-data.py` split for why duplication drifts.
- **Never claim a platform enforces something it only prompts.** If Copilot's subagent model turns
  out not to support the same tool-scoping granularity, the compliance-critical grants (advisory
  agents holding no Write/Edit, the four reviewers' scoped findings-pack Write) either get a real
  enforcement mechanism on that platform too, or the docs say plainly "prompted, not enforced, on
  Copilot" - never silently downgraded and left looking equivalent.
- **Follow the pattern this repo already has, don't extend the wrong file.** `install_helper.py`
  already handles "repo mode vs. plugin mode" for Claude Code, but it's Claude-Code-specific
  end to end - it shells out to the `claude plugin` CLI and writes Claude-Code-only settings, so
  Copilot support does NOT belong inside it. What's worth reusing is the *shape*: detect the
  platform, keep one platform-agnostic core, add a thin adapter per target. A Copilot build needs
  its own new adapter next to (not inside) `install_helper.py`, following that same shape.
- **The safety hooks stay the hard non-negotiable.** Everything else in this doc is a nice-to-have
  by comparison; do not ship "runs on Copilot" with the raw-data block, the execution-consent gate,
  or the findings-pack Write scope silently absent or degraded.

## Open questions - status as of 2026-08-04 research pass

1. **✅ ANSWERED. `SKILL.md` location**: Copilot CLI reads `.claude/skills/` directly (also accepts
   `.github/skills/` or `.agents/skills/`). No mirror, no build step. Best-case outcome.
2. **◐ PARTIALLY ANSWERED. Custom-agent tool-scoping granularity**: coarse allow/deny by tool name
   is confirmed and portable (an advisory agent's `tools` list just omits `write`/`edit`). The
   FINER grant this repo actually relies on for the four reviewers - Write allowed, but only to one
   specific path - has no confirmed Copilot equivalent. Still open: is there a per-agent path-scoped
   write primitive anywhere in Copilot's model, or does this need a hook-level backstop instead (see
   Q4, which closes that door too, at least on the documented payload)?

   **Candidate design (2026-08-04, not yet built or tried): sidestep the gap instead of closing it.**
   On Copilot, give the four reviewer agents the SAME `tools` list as every other advisory agent -
   no `write`/`edit` at all, using only the coarse mechanism already confirmed portable above. Each
   reviewer returns its findings as its normal text output instead of writing the file itself; the
   orchestrator (Morgan) is the one that saves that output to
   `artifacts/<slug>/data/findings-*.json`. This needs no path-scoped write primitive and no
   agent-identity field, because the agent that's actually allowed to write is the orchestrator, and
   the orchestrator was always trusted with full Write. Trade-off: findings now pass through the
   orchestrator's context on the way to disk (more tokens than today's direct-write pattern on
   Claude Code) and the four-agent direct-write design stays Claude-Code-only, not something to
   port. This is the leading option unless a Copilot-native path-scoped write primitive turns up;
   record it here before it's built so the reasoning survives a context clear either way.
3. **◐ ANSWERED, WITH A MATURITY CAVEAT.** Copilot does have a question/elicitation primitive - an
   `ask_user` tool taking a question, optional multiple-choice list, and a freeform-allowed flag,
   plus an SDK-level `onUserInputRequest`/`OnElicitationRequest` handler - functionally close to
   `AskUserQuestion`. But two open GitHub issues found in the same research pass suggest it's not
   uniformly solid yet: elicitation blocking execution even in "autopilot" mode instead of
   auto-selecting (copilot-cli#2029), and a request to add first-class `ask_user`/`ask_question`
   support to the ACP protocol that doesn't have it yet (copilot-cli#2109) - implying the primitive
   may not be available identically across every Copilot surface (CLI vs. cloud/ACP agents). Treat
   as "exists on Copilot CLI today," not "uniformly available everywhere Copilot runs."
4. **✅ ANSWERED - and it's a real gap, not a formality.** Direct fetch of GitHub's own
   `preToolUse` hook reference shows the documented payload is `sessionId`, `timestamp`, `cwd`,
   `toolName`, `toolArgs` - **no agent-identity field of any kind.** This means
   `guard-findings-pack-write.py`'s core mechanism (distinguish "compliance-reviewer's Write to its
   own findings pack" from "any other agent's Write anywhere") **cannot be replicated at the hook
   layer on Copilot as currently documented.** Combined with Q2, this is the load-bearing finding of
   this research pass: the scoped-Write pattern that makes four advisory agents safely
   Write-capable has no confirmed portable mechanism on Copilot yet, at either the agent-definition
   layer or the hook layer. Whatever gets built for Copilot will need either (a) a different
   enforcement primitive not yet found, or (b) an honest "prompted, not enforced" downgrade
   documented per the non-negotiables above - never silently equivalent.

## Suggested phasing (once the open questions above are answered)

1. **Skills first** - lowest verified risk, highest content coverage. Confirm the file-location
   question, then check whether the existing `.claude/skills/*/SKILL.md` files work on Copilot
   as-is or need a thin frontmatter/path adapter (likely much smaller than a rewrite, given they're
   already fairly platform-neutral prose plus YAML frontmatter).
2. **Guard logic refactor** - extract each guard's decision function into a platform-agnostic
   module (pure functions: given normalized tool-call facts, return allow/deny + reason), covered
   by the SAME test suite that already exists (`tests/test_guard_*.py`), then write the Claude Code
   adapter (thin, should be near-zero behavior change to what's live today) and a new Copilot
   adapter reading `.github/hooks/*.json`'s contract.
3. **Subagents last**, and only once question 2 above is answered - this is where the two
   platforms' models diverge most, per the research done tonight, and rushing it risks silently
   losing the mechanical enforcement this repo worked hard for tonight.

## Sources (2026-08-04 research, cited so this survives a context clear)

- [About hooks for GitHub Copilot - GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/hooks)
- [GitHub Copilot hooks reference - GitHub Docs](https://docs.github.com/en/copilot/reference/hooks-reference) (direct WebFetch verified the block/deny + fail-closed-on-crash behavior)
- [GitHub Copilot CLI Custom Agents and Skills](https://www.devleader.ca/2026/07/23/github-copilot-cli-custom-agents-and-skills)
- [AI Coding Agents 2026: Claude Code vs Antigravity 2.0 vs Codex vs Cursor vs Kiro vs Copilot vs Windsurf](https://lushbinary.com/blog/ai-coding-agents-comparison-cursor-windsurf-claude-copilot-kiro-2026/)
- [Adding agent skills for GitHub Copilot CLI - GitHub Docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) (direct WebFetch verified `.claude/skills`/`.github/skills`/`.agents/skills` all work, project and personal locations)
- [Custom agents and sub-agent orchestration - GitHub Docs](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents) (direct WebFetch verified the `tools`/`model`/etc. field list and the coarse allow-list behavior)
- [Allowing and denying tool use - GitHub Docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools) (`--allow-tool`/`--deny-tool`, deny-wins precedence)
- [Pre-tool use hook - GitHub Docs](https://docs.github.com/en/copilot/how-tos/copilot-sdk/hooks/pre-tool-use) (direct WebFetch verified the exact payload field list - no agent-identity field)
- [ACP: support an ask_user / ask_question style extension method - copilot-cli#2109](https://github.com/github/copilot-cli/issues/2109)
- [Elicitation in autopilot mode should auto-select best option instead of blocking - copilot-cli#2029](https://github.com/github/copilot-cli/issues/2029)
