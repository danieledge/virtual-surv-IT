# Shared: run mode, `<python>`, and chaining to another workflow

> Shared by every team skill (that is why this folder is not a skill of its own). Repo path:
> `.claude/skills/.shared/run-mode.md`; installed plugin:
> `$PLUGIN_ROOT/.claude/skills/.shared/run-mode.md`. Read it only when the answer is not
> already in this session. Full detail: `docs/team-operating-guide.md`, "Run mode & the
> bundled scripts".

## `<python>`: resolved ONCE per session, never re-probed

Every `<python> -m scripts.<name>` in a skill means the interpreter already established for this
session.

- **Arrived via `/engage` or `/engage-light`** (the normal case): the step-0 probe printed
  `INTERPRETER=<word>`. **That literal word is `<python>`. Use it verbatim and never re-probe**,
  including in a skill entered later in the same session, and including after a compaction (a
  resumed engagement's `runtime.interpreter` in `engagement-state.json` holds the same word).
- **Invoked directly, with no probe result in this session**: resolve once, then reuse. Prefer the
  cached word in `VSIT/local/guard-interpreter` (written by the safety-guard hooks) when it exists
  and runs; otherwise try `python`, then `py`, then `python3` on Windows (`OS=Windows_NT`), and
  `python3`, then `python`, then `py` elsewhere. Windows commonly has no `python3` at all, and an
  unconditional `python3` attempt there can hang on the Microsoft Store alias stub.

Record the resolved word (`set-runtime --interpreter <word>`) as soon as an engagement workspace
exists, so a resumed session inherits it instead of guessing.

## Repo-as-project vs installed plugin

The step-0 probe prints `PLUGIN_ROOT=`.

- `repo-as-project`: the working directory is the team repo. Invoke the module form,
  `<python> -m scripts.<name>`, and read team docs/skills from the local paths.
- Any other value: an installed plugin in a foreign project. Invoke the bundled copies **by
  path**, `<python> "$PLUGIN_ROOT/scripts/<name>.py"` (the module form exits 1 outside the repo,
  so go straight to the path form), and resolve `docs/...`, `docs/templates/...` and
  `.claude/skills/...` under `$PLUGIN_ROOT` too. The execution gate allow-lists the team's script
  basenames, so these run consent-free.

Use ONE consistent spelling: forward slashes, double quotes, every time. A missing bundled
template is never a reason to refuse a deliverable: produce it to the documented structure and
flag that the template was unavailable.

## Reading team docs vs. writing the user's own deliverables - never the same root

The rule above is about **reading** the team's own docs/templates/skills (`$PLUGIN_ROOT` in
installed-plugin mode). **Writing `VSIT/engagements/...` is a completely different concern and never
uses `$PLUGIN_ROOT`** - every deliverable (`VSIT/engagements/<slug>/...`, `engagement-state.json`,
`START-HERE.md`, findings packs) is **always relative to the current working directory** - the
user's actual project, whatever that is this session - **regardless of run mode.**

**Live-reproduced failure (2026-08-08, twice, both times with no Bash tool available this
session):** with no `pwd`/shell to confirm the actual working directory, and having just
successfully read team docs from an absolute path under `$PLUGIN_ROOT`, real deliverable files
were written to that SAME absolute path instead of the working directory - landing inside the
team's own plugin source tree rather than the user's project. The fix is mechanical, not
judgement: **use a relative path (`VSIT/engagements/...`) for every deliverable write, always** - never
an absolute path built from `$PLUGIN_ROOT`, and never an absolute path recycled from a team-doc
`Read` call, no matter how confident the session is about its own location. A relative path
resolves correctly against the real working directory by construction; an absolute path
requires knowing what that directory is, which is exactly the thing unconfirmable without a
shell. If a tool ever reports the actual working directory (a probe result, a prior Read's
resolved path shown back), that confirms it - but the default, with or without that
confirmation, is: deliverables are relative paths, full stop.

## Chained skills are dormant

Every team skill carries `disable-model-invocation: true`, so **no skill can invoke another**
(their descriptions do not load into ordinary sessions, and the Skill tool will not reach them).
When a step routes to another workflow (`/deep-review`, `/handover`, `/build-solution`, …), do one
of two things:

- **read its definition and follow it in this session**: `.claude/skills/<name>/SKILL.md`, or
  `$PLUGIN_ROOT/.claude/skills/<name>/SKILL.md` in an installed plugin; or
- offer the user the slash command to type.

Never announce that you are "invoking" it via the Skill tool, and never treat its being
unavailable as a blocker.
