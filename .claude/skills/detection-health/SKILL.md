---
description: Detection health - surveillance coverage assessment, threshold calibration, or a periodic TM model validation pack
argument-hint: "[--coverage|--tune|--validate] <the area, scenario or TM system, and where the data is>"
disable-model-invocation: true
---

# /detection-health

One front door for the health of what is already deployed.

**Pick the mode from `$ARGUMENTS` (first token), then hand over to the engine.** The engines are the
skills that existed before 2026-09-13; they still work under their own names for one release, so
nothing about how the work runs has changed, only the front door:

- `--coverage` - are all in-scope risks detected, and are the feeds live?. Read `.claude/skills/assess-coverage/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/assess-coverage/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--tune` - calibrate thresholds with ATL/BTL evidence. Read `.claude/skills/tune-thresholds/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/tune-thresholds/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--validate` - periodic TM model validation pack. Read `.claude/skills/validate-tm-model/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/validate-tm-model/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.

No flag: ask; the three are different engagements with different owners.

Never guess a mode from prose when the flag is absent and the request is ambiguous: ask via the
question tool (single-select, the modes above as options) and wait.
