# Claude Code setup review (2026-06-19)

A comprehensive review of this repo *as a Claude Code configuration* — are we using the
right features, the right way? Feature behaviour below was **verified against the current
Claude Code docs** (code.claude.com/docs), not assumed.

## Verdict

The core design is sound and idiomatic: project-scoped **subagents** with least-privilege
`tools`, **slash commands** as workflows, a **PreToolUse hook** for the data guard, a shared
**CLAUDE.md**, and committed **settings.json**. One real correctness bug was found and fixed;
a few enhancements are recommended.

## Fixed in this change

| Issue | Severity | Fix |
|---|---|---|
| **`memory: project` is not a real subagent field**, and `.claude/agent-memory/` was invented. Used on 7 agents + README + .gitignore. Silently ignored by Claude Code, so it created a false expectation of persistence. | High | Removed the field from all agents; replaced with a **committed [`docs/house-rules.md`](house-rules.md)** that advisory agents recommend into and the PM commits — a real, auditable mechanism. |
| No `deny` permissions — the raw-data block relied only on the hook. | Medium | Added `permissions.deny` for `data/raw/**`, `.env*`, `secrets/**`, `*.pem`, `*.key` as defense-in-depth. |
| Diagrams were rules-developer-centric. | Low | Reworked to PM → spec → right builder → QA → review → handover. |

## What's correct (verified)

- **Subagent frontmatter** uses only valid keys (`name`, `description`, `tools`, `model`);
  advisory agents are read-only (`Read, Grep, Glob` [+`Bash`]) — least privilege.
- **`description`** uses "MUST BE USED" / "Use proactively" phrasing → good auto-delegation.
- **Hook** schema is correct: `PreToolUse` matcher + `hooks[].type/command`, exit code 2
  blocks and feeds stderr back, and `$CLAUDE_PROJECT_DIR` is the supported path variable.
- **settings.json** is the right place for shared/committed team config; `Bash(cmd:*)`
  permission patterns are valid.
- **Commands** use `description` + `argument-hint` + `$ARGUMENTS` correctly.

## Recommended next (not yet done)

1. **Package as a plugin** (highest value for distribution). Add `.claude-plugin/plugin.json`
   + a `marketplace.json` so the team installs with `/plugin install …` — the same way
   turingmind ships. Lets others adopt it without cloning into their repo.
2. **Migrate commands → Agent Skills** (`.claude/skills/<name>/SKILL.md`). Slash commands
   still work but skills are the current model and load lazily; `disable-model-invocation`
   can keep destructive ones user-only.
3. **CLAUDE.md `@imports`.** As the handbook grows past ~200 lines, move detail into imported
   files (`@docs/WAYS-OF-WORKING.md`) and consider `.claude/rules/` for path-scoped rules.
4. **More hooks** (optional): a `PostToolUse` hook to auto-render artifacts to HTML, or a
   `Stop`/`SessionStart` hook — Claude Code exposes many events.

None of the recommended items are blockers; the setup is usable today.
