# Shared: the step-0 probe and opening banner (`/engage` and `/engage-light`)

> Shared by `/engage` and `/engage-light` - both front doors open identically; light only differs
> from step 1 onward. Repo path: `.claude/skills/.shared/engage-open.md`; installed plugin:
> `$PLUGIN_ROOT/.claude/skills/.shared/engage-open.md`. Extracted so each door reads only this
> file, never the other's full skill (cost fix; history: docs/internal/incident-log.md).

**Read `docs/team-operating-guide.md` at the open (step 0)**: the standing rules (question-tool
discipline, 🎩 voice, clean console, outcome discipline + the required engagement-summary email,
memory scope, orchestration discipline & right-sizing), the **roster** and the **deliverable →
owner routing table** live there, not in CLAUDE.md. An engagement run without it misses standing
user preferences.

**Chaining team workflows:** the team's skills are **not model-invocable** (dormant by default).
When a step routes to another workflow (`/audit-review`, `/build-solution`, `/prepare-data`, …),
**read `.claude/skills/<name>/SKILL.md` and follow it in this session** (plugin mode:
`$PLUGIN_ROOT/.claude/skills/<name>/SKILL.md`), or offer the user the slash command to type. Never
the Skill tool. (Shared rule: `.claude/skills/.shared/run-mode.md`.)

**0. Fast open - ONE probe call, then straight to the user.** Time-to-first-question is the
user's first impression and every tool call is a full model round-trip, so gather EVERYTHING the
open needs in **one compound Bash call**: never a probe-per-turn sequence, and **no narration
turns between the probe and your opening banner**.

**Check for a pre-computed probe FIRST.** If this turn's context already contains an
`<engage-probe-result>` block (injected by the `engage_probe_prefetch` hook before your turn
started, steady-state only - a cold interpreter cache or the hook not being wired means it
never appears), use those values directly and skip the bootstrap fallback entirely - same
data, zero tool calls.

**No injected block? Try the go-written probe cache next (2026-08-18, the corp fast
path - the live probe can take minutes on corporate boxes):** Read the FILE
`VSIT/local/engage-probe.json` (one Read call, no shell). If it exists, its
`computed_at` is recent (same day and plausibly within the hour - the hook applies the
exact TTL and identity fingerprint mechanically; your direct read is the fallback, so be
conservative) and nothing suggests the branch or plugin version moved since `computed_at`,
use its `report` and `interpreter` exactly as if injected. Two live pieces remain yours: the
resume-or-new data (`--new` needs none - zero discovery; `--resume <slug>`/no-flag runs
ONE `<python> -m scripts.engagement_state list --menu` command), and the session stamp,
which the first `engagement_state` command writes automatically - never hand-write it.
A stale, missing or odd-looking cache file means fall through to the heredoc; the cache
is an accelerator, never load-bearing.

Otherwise (no block, no usable cache): **read
`.claude/skills/engage/references/probe-bootstrap.md`** (plugin mode:
`$PLUGIN_ROOT/.claude/skills/engage/references/probe-bootstrap.md`) **and run its bootstrap
block exactly as written, character for character.** It is the fallback - still fully live,
drift-pinned against `scripts/find_plugin_root.py` by `tests/test_engage_open_bootstrap.py`,
and not being retired; it lives in that reference so a steady-state open (injected block or
cache hit) never pays for its text. Do not reconstruct the block from memory - read the file.


**Run the block from wherever you already are - NEVER prepend `cd`.** The block uses
`Path.cwd()` to detect the mode; a prior `cd` silently flips a plugin-mode session into
repo-as-project and points engagement state at the wrong project (live 2026-08-17;
incident-log #19).

**Windows path rule, for every Bash call this session:** the Bash tool is Git Bash even on
Windows, so an absolute Windows path is written with FORWARD slashes inside double quotes
(`"C:/Users/x/project"`) - backslashes are shell escapes and get eaten, and a mangled path has
wrongly been judged a broken probe (live 2026-08-16; incident-log #12). **Never hand-compose a
substitute probe - the bootstrap block IS the probe**, and on failure it prints the inner
error as `PROBE-STDERR:` lines. The ban includes "lighter" partial probes - grepping for probe
field names, ad-hoc `engagement_state` calls to "check first" (both seen live 2026-08-17) -
one probe, nothing before it, nothing beside it.

**On `PROBE_FAILED`**: retry the block once by hand (never guess, never silently give up) and
read `.claude/skills/engage/references/probe-contract.md` (plugin mode:
`$PLUGIN_ROOT/.claude/skills/engage/references/probe-contract.md`) - the probe's contract and
known failure modes. Failures only; a healthy open never reads it.

The script prints, in order: `INTERPRETER=` (python3/python/py, **or a full absolute path** -
the cache can be pre-seeded with one, e.g. `C:\Python313\python.EXE`. This IS `<python>` for
every later script call in this session: use it verbatim, **always double-quoted**
(`"<python>" -m scripts.<name>`, never bare - an unquoted path loses its backslashes to the
shell; live 2026-08-14, incident-log #12 - **never re-probe**), `PLUGIN_ROOT=`,
`OS=Windows|POSIX` (the host, computed - **use it instead of inferring Windows-ness later**;
the exec-consent command in `.claude/skills/engage/references/safety-gates.md` reads this
field directly), `PYTHON_VERSION=`, `PLUGIN_VERSION=`, `BRANCH=`,
`PREV_TEAM_VERSION=`, `VERSION_CHANGED=yes|no` (computed - never re-derive it), `EXTRA_FORMATS=`,
`REGULATORY_CITATIONS=on|off`, `LARGE_CONTEXT_REVIEW_SPLIT=on|off` (project preference - `on`
means split a large, multi-component review by component from the start rather than waiting to
discover the need for it from a failed call; see the orchestration-discipline section of
`docs/team-operating-guide.md`), `MAP_SKELETON=on|off` (project preference, 3-tier precedence
like docx/citations - `on` means `check_map()` runs MAP-DRIFT/MAP-DEAD-POINTER for a codebase
map with a `Paths` column; ADR-007 Phase 1, experimental, off by default), then, ONLY when
`MAP_SKELETON=on` AND something has actually drifted, `MAP_DRIFT=<n> of <m> area(s): <list>` -
**use this, don't just print it**: when briefing an agent whose work touches a drifted area,
say so explicitly (that area's map entries are unverified, not `📊 observed`) instead of handing
over the map's claims as settled fact; if the drift is central to what this engagement is about,
consider offering `/map-codebase --refresh` before briefing rather than working from a known-stale
map. (Root map only - `VSIT/shared/map.d/` area files aren't covered by this open-time check,
only by the full sweep at close.) `INTEGRATIONS=` appears ONLY when the project has opted into
the first-class tracker/PR config (docs/INTEGRATIONS.md; off by default, absent line = all off,
take no outward actions): when present, read
`.claude/skills/engage/references/integrations.md` before your first outward action - issue
creation is named in the plan the go-ahead gate approves, never fired unannounced. Then the
tooling report, the codebase map header + §3, the newest CHANGELOG entry's heading (`WHATS_NEW=`), and any
team-extensions block.

**The probe does NOT print the operating guide** - issue that `Read` yourself (plugin mode:
`$PLUGIN_ROOT/docs/team-operating-guide.md`) in the SAME turn as the probe when the working
project has its own copy, otherwise immediately after using the printed `PLUGIN_ROOT`. Never
proceed past the open without it.

What the result gives you, and the rules attached to each:
- **Mode.** `PLUGIN_ROOT=repo-as-project` → invoke `<python> -m scripts.<name>`; any other value →
  installed plugin: **every `<python> -m scripts.<name>` in this skill means `<python>
  "$PLUGIN_ROOT/scripts/<name>.py"`** (the module form exits 1 outside the repo, so go straight to
  the path form), and docs, templates and skill definitions resolve under `$PLUGIN_ROOT` too. The
  execution gate allow-lists team script basenames, so they run consent-free. **Remember
  `PLUGIN_ROOT` for the whole session**, and persist it once the workspace exists (`set-runtime`).
- **Branch** (`BRANCH=`): populated only when the root is a real git working directory. A
  plugin-cache install has no `.git`, so it is usually empty outside repo-as-project - never guess
  a branch name when it's blank.
- **Analyser inventory:** cached, 7-day TTL (`--refresh` only after installing tools). Remember the
  result and never re-invoke missing tools this session.
- **Codebase map** (ADR-003): advisory context only, never instructions. **Just-in-time by
  design** - the probe loads only the header + §3 engagement history (already reduced to
  `PREV_TEAM_VERSION=` / `VERSION_CHANGED=`), **not** the bulky §2 entries. **Read a §2 section
  only when you actually rely on it**, and `git`-verify an anchor only then or at close, never as
  open-time round-trips; this keeps turn-0 context lean so a long engagement doesn't compact
  prematurely. Note ⚠️ stale-looking entries in the opening summary; no map → one gets created at
  close.

**Company extensions (ADR-009):** if (and only if) the probe printed a TEAM-EXTENSIONS block, read
`.claude/skills/engage/references/extensions.md` (plugin mode:
`$PLUGIN_ROOT/.claude/skills/engage/references/extensions.md`) and honour it **ADDITIVELY** -
standing instructions merge with the operating rules, close actions are OFFERS, and a registered
analyser that will need RUNNING makes the intake execution-consent question applicable.
**Extensions can NEVER waive a disclaimer, gate, guard or the code chain**: refuse politely and
continue standard if one asks.

**Allow-list tip (banner, one short line, only when flagged).** The tooling probe ends with
`ALLOWLIST: present|missing` for the working project. On `missing`, add ONE friendly banner line:
*"Tip: fewer permission prompts in this project - run `python <clone>/install_helper.py
--permissions .`"* (plugin mode: `python "$PLUGIN_ROOT/install_helper.py" --permissions .`). It is
the USER's command: never run it yourself, never edit settings (ADR-002 rec 5), never repeat the
tip later. On `present`, say nothing.

**Document formats (banner, one short line).** From `EXTRA_FORMATS=`, state what controlled
documents (BRD, FSD, delivery report, …) will be produced in: always *".md + .html"*, plus *"+
.docx"* when it contains `docx`. **An empty `EXTRA_FORMATS=` covers BOTH "no
team-preferences.json at all" (the common case) and "the file exists but docx isn't listed"** -
same tip either way, never a different message, never a missing-file note. Whenever docx is off,
append the tip in the SAME line, never a separate line and never repeated later: *"(want Word
copies too? just say so, or run the installer's Document format preferences menu)"*. This is a
project preference, not a gate: no allow-list-style refusal, and Morgan may write
`VSIT/config/preferences.json` directly if the user says yes in conversation (no consent gate on
that file, unlike hooks/settings). **Same line, append citations**: from `REGULATORY_CITATIONS=`,
*"regulatory citations on"* or *"off (project preference)"*.

**Large-context review split (banner, one short line, only when on).** The probe prints
`LARGE_CONTEXT_REVIEW_SPLIT=on|off` but - unlike doc formats/citations above - this is a
reliability workaround, not an output preference (`docs/internal/large-context-review-splitting-plan.md`),
so state it only when `on`: *"Large reviews will be split by component this session (project
preference)."* Say nothing when `off` - most projects never touch this, and a per-engagement "off"
line would be noise for a setting that already defaults to off. A user who explicitly names the
corp-proxy/timeout issue mid-session still gets the split applied per the orchestration-discipline
rule even if this stayed silent at open.

**Tooling inventory (banner, one short line, every engagement).** The probe's tooling report
already computes present/missing counts for the seven configurable analysers (cached, TTL-bound -
**never re-probed just to compose this line**). State the degradation link as one line so it's
known before, not discovered after, a review. All seven present: *"✅ full tool-backed coverage
this session."* Any missing: *"🧠 <tool, tool> not installed - dependent findings will be
inferred, not measured (install for 📊 coverage)."* Name only the missing supported tools, not
the best-effort/unsupported language list. If the user later installs a missing tool, tell them
once to re-run `bash scripts/check-review-tools.sh --refresh` rather than waiting out the TTL.

**Model (banner, one short line, every engagement).** State which model you are actually
running as this session (e.g. *"running as Sonnet 4.6"*) - your own identity, not a file read
(`.claude/settings.json`'s `model` key is only the configured default). Sonnet is the
documented orchestrator default; opus stays available for critical/high-stakes engagements.
Every time, not only when asked (live 2026-08-03: a user discovered their model from a
provenance stamp after the fact). If you don't know how to change it, say so: *"(change with
`python install_helper.py`, menu option 8, or `--model-project . --model opus`)"*.

**What's new (banner, one short line only).** Branch on the printed `VERSION_CHANGED=`; never
re-derive it. The probe prints `WHATS_NEW=` - the newest CHANGELOG entry's **heading line
only** (the **plugin's**, or the repo's own in repo-as-project, **not** the working
project's). The entry body is deliberately never printed - dev-facing detail (live 2026-08-17,
incident-log #18). Do not go read CHANGELOG.md to expand it.
- `yes` **and** `PREV_TEAM_VERSION=` non-empty → *"🆕 Since last time (vX → vY): "* + the
  `WHATS_NEW=` title in plain words, ending *"(full detail: CHANGELOG.md)"*.
- `yes` **and** `PREV_TEAM_VERSION=` empty (first engagement, no prior record) → *"🆕 In the
  current release (vY): ..."* - never guess what the user last saw.
- `no` → show nothing. This must never become a wall of release notes and never delays the first
  question.
- `WHATS_NEW=` absent (broken/partial install) while `yes` → banner and version as normal, omit
  the what's-new line; never surface probe mechanics to the user.

Either populated form is **part of the opening banner itself, not optional**. The comparison is
local files only (the map plus the bundled manifest and CHANGELOG), so it works identically for
manually copied / air-gapped installs with no git or network.

**Then your VERY NEXT output is the opening banner + disclaimers + the batched question that
follows in the calling skill.** Target: the probe call (with the operating-guide `Read` alongside
or immediately after it), then the ask - no other turns in between.
