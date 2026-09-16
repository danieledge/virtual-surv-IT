---
description: Review code at a chosen depth and focus - quick, deep or audit; security, performance or a Quantexa estate; with or without a fix loop (the one review front door)
argument-hint: "[--depth quick|deep|audit] [--focus security|performance|quantexa] [--fix] <path/glob, commit range, or nothing for the working diff>"
disable-model-invocation: true
---

# /review

One front door for every review. Depth and focus are axes, not separate commands.

**Pick the mode from `$ARGUMENTS` (first token), then hand over to the engine.** The engines are the
skills that existed before 2026-09-13; they still work under their own names for one release, so
nothing about how the work runs has changed, only the front door:

- `--depth deep (default)` - detailed multi-dimension review with confidence scoring. Read `.claude/skills/deep-review/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/deep-review/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--depth quick` - the consolidated in-session pass; pass `--depth quick` through as the engine's Quick mode. Read `.claude/skills/deep-review/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/deep-review/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--depth audit` - audit and regulatory-defensibility review, evaluator-optimizer loop. Read `.claude/skills/audit-review/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/audit-review/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--focus security` - OWASP ASVS / CWE, threat model, secrets and data safety. Read `.claude/skills/security-audit/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/security-audit/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--focus performance` - static performance and scalability review against target volumes. Read `.claude/skills/performance-review/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/performance-review/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--focus quantexa` - BETA: a Quantexa TM estate against BRDs/TSDs with the platform knowledge base. Read `.claude/skills/beta-assess-quantexa/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/beta-assess-quantexa/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.
- `--fix` - assess, prioritise, fix, re-review and hand over legacy or poorly built code (a build activity: the fix loop edits code). Read `.claude/skills/remediate/SKILL.md` (plugin mode: `$PLUGIN_ROOT/.claude/skills/remediate/SKILL.md`; never the Skill tool, per `.claude/skills/.shared/run-mode.md`) and follow it exactly, with everything after the flag as its `$ARGUMENTS`.

No flag: `--depth deep`. `--focus` and `--depth audit` combine as the engines already allow (a security audit inherits the audit loop).

Never guess a mode from prose when the flag is absent and the request is ambiguous: ask via the
question tool (single-select, the modes above as options) and wait.
