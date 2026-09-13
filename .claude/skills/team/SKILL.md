---
description: The team itself - meet the roster, view or change project preferences, or regenerate the cross-project dashboard
argument-hint: [--meet|--preferences|--dashboard]
disable-model-invocation: true
allowed-tools: Read, Write, Edit, AskUserQuestion, Bash(python -m scripts.dashboard:*), Bash(python3 -m scripts.dashboard:*)
---

# /team

Utilities about the team, none of which opens an engagement.

**Pick the mode from `$ARGUMENTS` (first token), then hand over to the engine.** The engines are the
skills that existed before 2026-09-13; they still work under their own names for one release, so
nothing about how the work runs has changed, only the front door:

- `--meet (default)` - Morgan introduces the specialists. Read `.claude/skills/meet-the-team/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/meet-the-team/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--preferences` - view or change this project's team preferences. Read `.claude/skills/preferences/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/preferences/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--dashboard` - the local, static cross-project dashboard. Read `.claude/skills/dashboard/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/dashboard/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.

No flag: `--meet`.

Never guess a mode from prose when the flag is absent and the request is ambiguous: ask via the
question tool (single-select, the modes above as options) and wait.
