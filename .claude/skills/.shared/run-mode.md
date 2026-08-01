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
  cached word in `.claude/.guard-interpreter` (written by the safety-guard hooks) when it exists
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
