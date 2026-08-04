# Step-0 probe: contract, rationale and failure modes

> Loaded just-in-time: read this **only** when the step-0 probe misbehaves (`PROBE_FAILED`, an
> empty result, a field you did not expect), or when you are changing the bootstrap. A healthy
> open never needs it. Repo path: `.claude/skills/engage/references/probe-contract.md`;
> installed plugin: `$PLUGIN_ROOT/.claude/skills/engage/references/probe-contract.md`.

## What the probe is

`scripts/engage_probe.py` collapses the whole open-time gather into one tested script, so the
model generates one short invocation instead of ~18 lines of bash it has to reproduce verbatim
(audit findings #5/#6/#8). The `VERSION_CHANGED` decision is **computed there**, not derived by
the model from prose logic, and `PLUGIN_ROOT` is printed in a form `set-runtime` can persist.

Only the plugin-root bootstrap stays in raw shell: locating the script itself in an installed
plugin is the bootstrapping problem the probe exists to solve.

## What it prints

`INTERPRETER=` (only when `--interpreter-name` was passed, which the bootstrap always does),
`PLUGIN_ROOT=`, `PYTHON_VERSION=`, `PLUGIN_VERSION=`, `BRANCH=`, `PREV_TEAM_VERSION=`,
`VERSION_CHANGED=yes|no`, `EXTRA_FORMATS=`, `REGULATORY_CITATIONS=on|off`, then (each only when
non-empty) the tooling report, the codebase map header + §3, the newest CHANGELOG entry, and the
team-extensions block.

**It does not print `docs/team-operating-guide.md`.** Inlining the guide was removed: it pushed
~32KB of duplicate content through the probe's stdout, large enough to trip the harness's
"output too large" path, while the skill already carries its own explicit instruction to read the
guide (`tests/test_engage_probe.py::test_build_report_never_embeds_the_operating_guide` pins
this). Read the guide as a separate `Read`, alongside the probe call or immediately after it.

## Why the interpreter order is what it is

The bootstrap reads the cached interpreter word from `.claude/.guard-interpreter`, warmed by the
safety-guard hooks that run for this very Bash call (or by the installer's pre-warm), before
trying anything. A corporate report traced multi-minute opens to the previous behaviour: an
unconditional `python3` attempt first, hitting the Microsoft Store execution-alias stub on every
open. On a cache miss the order is Windows-aware (`python py python3` when `OS=Windows_NT`,
`python3 python py` otherwise), never a hardcoded python3-first list.

The word that worked is echoed back as `INTERPRETER=` and **is** `<python>` for the rest of the
session. Never re-probe it: the printed word is the answer, in this skill and in every skill or
agent that runs afterwards in this session.

## Why `PYTHONIOENCODING=utf-8` is mandatory

Historically the report could contain emoji pulled in verbatim from project files
(codebase-map.md, CHANGELOG.md, team-extensions.md). On a cp1252 console (the Windows
default) a bare `print()` of it raised `UnicodeEncodeError`, which exits non-zero for every
one of python3/python/py, and the bootstrap's `2>/dev/null` then hid the traceback: the probe
looked like it silently did nothing.

2026-08-04: `engage_probe.py`'s `_ascii_safe()` now guarantees the report is pure ASCII before
it ever reaches `print()` - known repo glyphs (📊/🧠 tags, the 🎩 marker, arrows) get a
readable substitute, anything else falls back to a generic ascii-encode. This closes the
`UnicodeEncodeError` above at the source, AND a second, separate failure the same corp report
surfaced: even with the encoding fixed, capturing the probe's stdout through Claude Code's own
Bash tool on a Windows cp1252 console could raise `UnicodeDecodeError` downstream, because
`PYTHONIOENCODING` only controls how THIS process encodes its OWN stdout - it says nothing
about how that separate shell-capture pipe decodes the bytes back into text. Ascii-only output
sidesteps that decode step entirely, since ASCII round-trips correctly through any encoding.

Keep the `PYTHONIOENCODING=utf-8` assignment in every invocation regardless - it's still a
correct, harmless default and other paths in this bootstrap may still emit non-ASCII text
(interpreter names, paths) that this belt-and-suspenders setting protects.

## Why the plugin root is found, not assumed

Env vars such as `$CLAUDE_SKILL_DIR` / `$CLAUDE_PLUGIN_ROOT` are not reliably expanded in the
Bash tool's subshell (a live plugin-mode run paid recovery turns for assuming they were).
Resolution order:

1. the install registry (`~/.claude/plugins/installed_plugins.json`, each `installPath` verified
   by the manifest name): authoritative for every install source, GitHub marketplace, git URL, or
   a locally cloned directory added as a marketplace;
2. a `find` over the cache/marketplace directories, `sort -V` picking the newest versioned copy,
   for registries predating the current schema.

`PLUGIN_ROOT=repo-as-project` means the working directory **is** the team repo: use the local
`scripts/` and `.claude/skills/` paths. Any other value is the base for every bundled-script
invocation and skill-definition read (`$PLUGIN_ROOT/scripts/...`,
`$PLUGIN_ROOT/.claude/skills/<name>/SKILL.md`, `$PLUGIN_ROOT/docs/...`). Persist it with
`set-runtime` the moment the workspace exists; it must not live only in conversational memory.

## On `PROBE_FAILED`

Run the printed command directly and read the real error rather than retrying the compound
blindly. The usual causes, in order of likelihood: no interpreter on PATH under any of the three
names; the encoding failure above (only when `PYTHONIOENCODING` was dropped); a plugin root that
resolved to a partial or half-updated install (the manifest or `scripts/` missing). A branch of
`BRANCH=` coming back empty is **not** a failure: a plugin install is usually a plain file copy
with no `.git` at all, and a detached HEAD is reported as unknown rather than as a branch name
that does not exist.
