---
description: Build from requirements - an end-to-end solution from a requirements pack, or a single detection scenario spec to sign-off
argument-hint: [--scenario] <path to requirements pack / BRD+FSD, or the scenario name / obligation>
disable-model-invocation: true
---

# /build

One front door for building. Detection logic keeps its own regulated chain.

**Pick the mode from `$ARGUMENTS` (first token), then hand over to the engine.** The engines are the
skills that existed before 2026-09-13; they still work under their own names for one release, so
nothing about how the work runs has changed, only the front door:

- `(no flag)` - end-to-end build from a requirements pack, orchestrator-workers. Read `.claude/skills/build-solution/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/build-solution/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--scenario` - a detection scenario end to end: spec, SME-pack review, implement, compliance review. Read `.claude/skills/new-scenario/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/new-scenario/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.

No flag: a requirements-pack build. A request that names a detection scenario or an obligation is `--scenario`; say so before dispatching.

Never guess a mode from prose when the flag is absent and the request is ambiguous: ask via the
question tool (single-select, the modes above as options) and wait.
