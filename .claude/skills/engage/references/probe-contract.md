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

The plugin-root bootstrap - locating the script itself in an installed plugin, the one part of
this that can't simply call a bundled script by path, since locating it IS the problem - is a
Python heredoc, not hand-assembled bash. `scripts/find_plugin_root.py` is the canonical, tested
implementation of the same discovery algorithm (`tests/test_find_plugin_root.py`); the heredoc
embedded in `.claude/skills/engage/references/probe-bootstrap.md` (read on the miss path from `.claude/skills/.shared/engage-open.md` step 0) is a condensed twin of it that CANNOT `import` the real module for
the same bootstrapping reason, so `tests/test_engage_open_bootstrap.py` mechanically checks the
two never drift apart (same role `test_hooks_in_sync.py` plays for staged-vs-live guard files).

## What it prints

`INTERPRETER=` (only when `--interpreter-name` was passed, which the bootstrap always does),
`PLUGIN_ROOT=`, `PYTHON_VERSION=`, `PLUGIN_VERSION=`, `BRANCH=`, `PREV_TEAM_VERSION=`,
`VERSION_CHANGED=yes|no`, `EXTRA_FORMATS=`, `REGULATORY_CITATIONS=on|off`, then (each only when
non-empty) the tooling report, the codebase map header + §3, the newest CHANGELOG entry's heading (`WHATS_NEW=`), and the
team-extensions block.

**It does not print `docs/team-operating-guide.md`.** Inlining the guide was removed: it pushed
~32KB of duplicate content through the probe's stdout, large enough to trip the harness's
"output too large" path, while the skill already carries its own explicit instruction to read the
guide (`tests/test_engage_probe.py::test_build_report_never_embeds_the_operating_guide` pins
this). Read the guide as a separate `Read`, alongside the probe call or immediately after it.

## Why the interpreter order is what it is

The bootstrap reads the cached interpreter word from `${CLAUDE_PROJECT_DIR:-.}/.claude/.guard-
interpreter`, warmed by the safety-guard hooks that run for this very Bash call (or by the
installer's pre-warm), before trying anything. `CLAUDE_PROJECT_DIR`-scoped rather than
plugin-root-scoped deliberately (2026-08-04 redesign) - the plugin root isn't known yet at this
point, and this matches what the guard hooks' own cache falls back to anyway in plugin mode, since
`CLAUDE_PLUGIN_ROOT` is the same unreliable env var described below. Worst case on a mismatch is
one extra interpreter probe, never a correctness issue. A corporate report traced multi-minute
opens to the previous behaviour: an unconditional `python3` attempt first, hitting the Microsoft
Store execution-alias stub on every open. On a cache miss the order is Windows-aware (`python py
python3` when `OS=Windows_NT`, `python3 python py` otherwise), never a hardcoded python3-first
list.

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
Resolution order (same two methods as before the 2026-08-04 redesign, now Python instead of
hand-typed bash - see `scripts/find_plugin_root.py`'s own docstring for the full rationale):

1. the install registry (`~/.claude/plugins/installed_plugins.json`): authoritative for every
   install source, GitHub marketplace, git URL, or a locally cloned directory added as a
   marketplace - `install_helper.py`'s own default clone dir, `~/virtual-surv-IT`, has no
   "compliance-surveillance-team" path segment, so method 2 alone can never find it. Schema-
   agnostic: recursively scans the parsed JSON for any `installPath` key at any nesting depth
   rather than assuming today's shape (`plugins.<key>[].installPath`) is a stable contract, then
   confirms the match by checking the candidate's `plugin.json` contains the team's name
   (substring match, not a parsed field - same crude-but-proven check the old `grep -q` did);
2. a filesystem search under the cache/marketplace directories for this plugin's own marker file,
   version-sorted to the newest-looking match, for registries predating the current schema. Only
   a fallback: it requires a literal `compliance-surveillance-team` path segment, which method 1's
   own motivating case (a locally cloned directory) does not have.

`PLUGIN_ROOT=repo-as-project` means the working directory **is** the team repo: use the local
`scripts/` and `.claude/skills/` paths. Any other value is the base for every bundled-script
invocation and skill-definition read (`$PLUGIN_ROOT/scripts/...`,
`$PLUGIN_ROOT/.claude/skills/<name>/SKILL.md`, `$PLUGIN_ROOT/docs/...`). Persist it with
`set-runtime` the moment the workspace exists; it must not live only in conversational memory.

## On `PROBE_FAILED`

Retry the exact same compound block once by hand with your working interpreter, and read the real
error rather than retrying blindly again. The usual causes, in order of likelihood: no interpreter
on PATH under any of the three names; a plugin root that resolved to a partial or half-updated
install (the manifest or `scripts/engage_probe.py` missing - the heredoc exits non-zero and moves
to the next interpreter in that case, so a total failure across all three usually means this); a
genuine Python syntax/runtime error inside the heredoc itself, which - unlike the old bash - fails
as an ordinary Python traceback on stderr, not a hung or garbled shell parse. A branch of `BRANCH=`
coming back empty is **not** a failure: a plugin install is usually a plain file copy with no
`.git` at all, and a detached HEAD is reported as unknown rather than as a branch name that does
not exist.

**Do not improvise a replacement diagnostic command - re-run the exact block above, character for
character, nothing else.** Live report (2026-08-07): after a hiccup, a session constructed its own
ad hoc check instead - `python -c "import sys; print(sys.executable)"` - reaching for the common
"let me just check X directly" instinct rather than following this section's own instruction to
retry the exact block. **Second live report, same shape, different field (2026-08-12):** a session
that had reason to doubt whether its `PLUGIN_VERSION=` was current (a resumed session, or general
uncertainty about install freshness) reached for `python -c "import importlib.metadata;
print('PLUGIN_VERSION=' + importlib.metadata.version('compliance-surveillance-team'))"` instead of
either trusting the value the probe already printed this open, or - if a fresh read is genuinely
warranted - just reading `.claude-plugin/plugin.json`'s own `"version"` field directly (a plain
file read, no execution at all; this is exactly what `read_plugin_version()` in
`scripts/engage_probe.py` itself does). **The pattern generalises: whatever field you're tempted to
re-verify - interpreter path, plugin version, branch, anything else the probe already printed -
reuse that value or re-read the underlying file directly. Never reach for `python -c`/stdin code
execution to re-derive it**, in any language, regardless of what you're trying to inspect or how
harmless it looks. `python -c` is **always** blocked by the execution guard, unconditionally -
CLAUDE.md §7 - and it will fire on a hand-typed diagnostic exactly as readily as on anything else.
It is not a false positive to work around; it is the same gate `/engage`'s own probe block is
deliberately written to never trigger (the heredoc form above exists *specifically* so this class
of command never has to run). If you genuinely need the interpreter's own path or version outside
what `INTERPRETER=`/`PYTHON_VERSION=` already gave you, `python --version` or `python -V` are not
`-c` and are not blocked - use one of those, never a `-c` one-liner, however small.

**Third live report, same underlying rule, a sharper variant (2026-08-14, corporate Windows
box):** a session hit `PROBE_FAILED` after the shell's cwd was silently reset mid-open (a
`Bash` tool call landed back in an unrelated project directory rather than where a prior `cd`
had left it - itself worth watching for independently, since it can misdirect more than just
the probe). The session's own narration read "Per the contract I retry once, and since I know
the plugin root I'll call the probe script directly" - correctly citing the contract by name,
then not actually following it: it ran a *different* invocation (`python
scripts/engage_probe.py --plugin-root <root>`, hand-assembled from what it already knew) instead
of the exact compound block above, character for character. The two prior incidents at least
didn't claim compliance while deviating; this one is more insidious precisely because the
citation reads as if the rule were being honoured. Constructing a plausible-looking equivalent
is still the improvisation this section exists to rule out - it throws away the one thing a
verbatim retry is for (seeing whether the SAME failure recurs, which is the actual diagnostic
signal), and on a machine where the cwd is already misbehaving, a hand-assembled relative path
is exactly the kind of command that silently resolves somewhere unintended. Saying "per the
contract" is not a substitute for reading what the contract actually says immediately above
this line - if a plausible-looking alternative command occurs to you at all on `PROBE_FAILED`,
that impulse is the signal to stop and re-run the exact block instead, not evidence that you've
found a smarter path through it.

*Root cause of the cwd reset itself, diagnosed the same session via a separate debug-log read:*
Claude Code's shell-snapshot mechanism (which captures/restores shell state - cwd included -
between `Bash` tool calls) timed out and was `SIGTERM`-killed because this machine's `.bashrc`
took over 10 seconds to source non-interactively. This is a host shell-profile problem, not a
plugin bug: nothing in this repo can compensate for the snapshot mechanism losing shell state
between calls. The concrete fix lives in the user's own `~/.bashrc` - guard slow steps (network
calls, nvm/pyenv/mise/conda init, cloud-auth checks) behind `[[ $- == *i* ]] || return` at the
top so they're skipped in a non-interactive shell, or profile with `time source ~/.bashrc` to
find the actual culprit first. Worth knowing precisely because it explains why the retry-exact-
block instruction matters even more than usual here: on a machine where shell state is already
dropping between calls, an improvised command is *more* likely to silently resolve against the
wrong directory, not less.

**Fourth live report, a different field, same root cause class (2026-08-14, separate corporate
Windows box):** a session had already learned `INTERPRETER=C:\Python313\python.EXE` from an
earlier successful probe this session, then typed it directly, unquoted, into a later ad hoc
`Bash` call (`C:\Python313\python.EXE -m scripts.engagement_state ...`). Git Bash/MSYS consumes
an unquoted backslash as its own escape character, so the shell received `C:Python313python.EXE`
and failed with `command not found` (exit 127) - the interpreter word was never wrong, it was
just used bare. The retry (correctly, per this section) re-ran the exact probe block by hand, but
the probe itself then also returned `PROBE_FAILED` on that box - a separate, unresolved failure,
not a repeat of the quoting mistake. `.claude/skills/.shared/engage-open.md`'s own definition of
`INTERPRETER=` used to
describe it as "the literal word - python3/python/py", undersizing the actual value space: the
cache can be pre-seeded with a full absolute path (`write_guard_interpreter_cache` in
`install_helper.py` does exactly this), which is exactly what this box had. Fixed at the source:
that section now says explicitly the value can be a full path and to **always double-quote it**
(`"<python>" -m scripts.<name>`), not just "use it verbatim" - the old wording was true but
incomplete, and incomplete in the direction that made this exact mistake look safe.

**Fifth live report (2026-08-16, same corporate Windows box) - the scrollback that resolved
the "separate, unresolved failure" above.** The session's FIRST probe attempt was not the
canonical block at all: the model hand-composed `cd C:\Users\<user>\virtual-surv-IT && python
-m scripts.engagement_state list --menu; ...` - the same backslash-eating class as the fourth
report, this time inside a `cd`, so bash saw `C:Usersdevvirtual-surv-IT`, the cd failed,
and the open was judged probe-broken before the canonical block ever ran. The by-hand retry
(direct `python "C:/Users/.../scripts/engage_probe.py"`, forward slashes) succeeded
immediately, proving the probe itself was healthy. Two fixes at the source in engage-open.md:
the Windows path rule is now stated for every Bash call this session (forward slashes inside
double quotes, never a backslash path, never a hand-composed substitute probe), and the
canonical block now surfaces the inner engage_probe stderr as `PROBE-STDERR:` lines on
failure, so a genuine future failure arrives with its reason instead of a bare
`PROBE_FAILED`.
