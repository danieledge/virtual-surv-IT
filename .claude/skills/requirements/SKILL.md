---
description: Requirements work - elicit them, write a BRD, turn a BRD into an FSD, or assess a regulatory change's impact
argument-hint: "[--elicit|--brd|--fsd|--impact] <the need, the BRD path, or the regulatory change>"
disable-model-invocation: true
---

# /requirements

One front door for requirements and analysis work (BABOK, EARS, ISO/IEC/IEEE 29148, Gherkin).

**Pick the mode from `$ARGUMENTS` (first token), then hand over to the engine.** The engines are the
skills that existed before 2026-09-13; they still work under their own names for one release, so
nothing about how the work runs has changed, only the front door:

- `--elicit` - stakeholder analysis and requirements gathering. Read `.claude/skills/elicit-requirements/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/elicit-requirements/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--brd` - idea to Business Requirements Document. Read `.claude/skills/write-brd/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/write-brd/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--fsd` - BRD to Functional Specification. Read `.claude/skills/brd-to-fsd/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/brd-to-fsd/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--impact` - a changed obligation: affected scenarios, controls, data and specs. Read `.claude/skills/reg-change-impact/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/reg-change-impact/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.

No flag and a BRD path given: `--fsd`. No flag and an idea in prose: `--brd`. Otherwise ask.

Never guess a mode from prose when the flag is absent and the request is ambiguous: ask via the
question tool (single-select, the modes above as options) and wait.
