# Shared: the step-0 probe and opening banner (`/engage` and `/engage-light`)

> Shared by `/engage` and `/engage-light` - both front doors open identically; light only differs
> from step 1 onward. Repo path: `.claude/skills/.shared/engage-open.md`; installed plugin:
> `$PLUGIN_ROOT/.claude/skills/.shared/engage-open.md`. This used to be duplicated in full inside
> `engage-light/SKILL.md` ("read `.claude/skills/engage/SKILL.md` for the shared mechanics") - that
> meant every `/engage-light` invocation paid for the ENTIRE parent skill (BRD/FSD chain,
> artifact-menu machinery, the full delivery flow) just to reach this shared open, making the
> "low-ceremony" front door cost more raw text than plain `/engage`. Extracted so both doors read
> only this, not each other's full file.

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
never appears), use those values directly and skip the Bash heredoc below entirely - same
data, zero tool calls. Otherwise (no block, or anything about it looks wrong) run the heredoc
exactly as documented; it is the fallback, still fully live and tested, not being retired.

The bootstrap below is a tested Python heredoc - a drift-pinned twin of `scripts/find_plugin_root.py`
(`tests/test_engage_open_bootstrap.py` keeps the two from ever diverging). Run it exactly as
written, character for character - history and full rationale in
`.claude/skills/engage/references/probe-contract.md` if something looks wrong:

```
CACHED=$(cat "${CLAUDE_PROJECT_DIR:-.}/.claude/.guard-interpreter" 2>/dev/null); \
_try() { PYTHONIOENCODING=utf-8 "$1" - "$1" <<'PY'
import sys, json, re, subprocess
from pathlib import Path

interp = sys.argv[1]
home = Path.home()
cwd = Path.cwd()

def install_paths(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "installPath" and isinstance(v, str):
                out.append(v)
            else:
                out += install_paths(v)
    elif isinstance(obj, list):
        for item in obj:
            out += install_paths(item)
    return out

def from_registry():
    try:
        data = json.loads((home / ".claude/plugins/installed_plugins.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    for path in install_paths(data):
        manifest = Path(path) / ".claude-plugin/plugin.json"
        try:
            text = manifest.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        if "compliance-surveillance-team" in text:
            return path
    return ""

def from_filesystem():
    hits = []
    for base in (home / ".claude/plugins/cache", home / ".claude/plugins/marketplaces"):
        if base.is_dir():
            for marker in base.rglob("docs/team-operating-guide.md"):
                if "compliance-surveillance-team" in marker.parts:
                    hits.append(marker)
    if not hits:
        return ""
    def key(p):
        return [(int(d), "") if d else (-1, s) for d, s in re.findall(r"(\d+)|(\D+)", str(p))]
    return str(max(hits, key=key).parent.parent)

root = "" if (cwd / "docs/team-operating-guide.md").is_file() else (from_registry() or from_filesystem())
script = Path(root, "scripts", "engage_probe.py") if root else Path("scripts/engage_probe.py")
if not script.is_file():
    sys.exit(1)
proc = subprocess.run(
    [interp, str(script), "--plugin-root", root, "--interpreter-name", interp],
    capture_output=True, text=True, encoding="utf-8",
)
sys.stdout.write(proc.stdout)
if proc.returncode != 0 or not proc.stdout:
    for line in (proc.stderr or "").strip().splitlines()[-3:]:
        sys.stderr.write("PROBE-STDERR: " + line + "\n")
    sys.exit(1)
sys.exit(0)
PY
}; \
OUT=""; \
if [ -n "$CACHED" ] && command -v "$CACHED" >/dev/null 2>&1; then OUT=$(_try "$CACHED"); fi; \
if [ -z "$OUT" ]; then \
  if [ "${OS:-}" = "Windows_NT" ]; then ORDER="python py python3"; else ORDER="python3 python py"; fi; \
  for I in $ORDER; do \
    OUT=$(_try "$I") && break; \
    OUT=""; \
  done; \
fi; \
if [ -n "$OUT" ]; then echo "$OUT"; else \
echo "PROBE_FAILED - retry this exact block once by hand with your working interpreter to see the real error"; fi
```

**Windows path rule, for every Bash call this session:** the Bash tool is Git Bash even on
Windows, so an absolute Windows path is written with FORWARD slashes inside double quotes
(`"C:/Users/x/project"`); backslashes are shell escapes and get eaten (live corp report
2026-08-16: a hand-composed `cd C:\Users\...` arrived as `C:Usersdev...`, failed, and the
open was wrongly judged probe-broken). **Never hand-compose a substitute probe - the block
above IS the probe**; on failure it now prints the inner error itself as `PROBE-STDERR:` lines.

The interpreter order (warm cache first, then Windows-aware) and `PYTHONIOENCODING=utf-8` are
still load-bearing, not decoration - the cache key is `CLAUDE_PROJECT_DIR`-scoped, not
plugin-root-scoped (rationale: `.claude/skills/engage/references/probe-contract.md`). **On `PROBE_FAILED`**, retry the block once by hand
(never guess, never silently give up) and read
`.claude/skills/engage/references/probe-contract.md` (plugin mode:
`$PLUGIN_ROOT/.claude/skills/engage/references/probe-contract.md`) - the probe's contract, the
rationale for each part of the bootstrap, and the known failure modes. That file is for failures
only; a healthy open never reads it.

The script prints, in order: `INTERPRETER=` (python3/python/py, **or a full absolute path** -
the cache can be pre-seeded with one, e.g. `C:\Python313\python.EXE`; live corp-Windows report,
2026-08-14: an unquoted absolute path used directly in a later Bash command lost its backslashes
to the shell, `command not found`. This IS `<python>` for every later script call in this
session: use it verbatim, **always double-quoted** (`"<python>" -m scripts.<name>`, never bare)
since a path can contain spaces or backslashes an unquoted shell word will corrupt - **never
re-probe**), `PLUGIN_ROOT=`, `OS=Windows|POSIX` (the host, computed - **use it instead of
inferring Windows-ness later**; the exec-consent command in
`.claude/skills/engage/references/safety-gates.md` reads this field directly, so a Windows host
always gets the PowerShell form shown alongside the `!` form, not only when something else in the
conversation happens to make Windows obvious), `PYTHON_VERSION=`, `PLUGIN_VERSION=`, `BRANCH=`,
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
map. (Root map only - `docs/codebase-map.d/` area files aren't covered by this open-time check,
only by the full sweep at close.) `INTEGRATIONS=` appears ONLY when the project has opted into
the first-class tracker/PR config (docs/INTEGRATIONS.md; off by default, absent line = all off,
take no outward actions): when present, read
`.claude/skills/engage/references/integrations.md` before your first outward action - issue
creation is named in the plan the go-ahead gate approves, never fired unannounced. Then the
tooling report, the codebase map header + §3, the newest CHANGELOG entry, and any
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
`.claude/team-preferences.json` directly if the user says yes in conversation (no consent gate on
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
**never re-probed just to compose this line**) and states outright that a missing tool degrades
its dependent findings from 📊 measured to 🧠 inferred. That link was previously visible only in
the raw probe output Morgan reads, never surfaced to the user - state it as one line so it's known
before, not discovered after, a review. All seven present: *"✅ full tool-backed coverage this
session."* Any missing: *"🧠 <tool, tool> not installed - dependent findings will be inferred, not
measured (install for 📊 coverage)."* Name only the missing tools, not the best-effort/unsupported
language list (TypeScript/Java/etc.) - that stays in the raw report for when it's actually
relevant. If the user later installs a missing tool, tell them to re-run
`bash scripts/check-review-tools.sh --refresh` (or the plugin-mode path form) rather than waiting
out the cache TTL - stated once, not repeated every engagement.

**Model (banner, one short line, every engagement).** State which model you are actually
running as this session (e.g. *"running as Sonnet 4.6"*) - your own identity, not a file read:
`.claude/settings.json`'s `model` key (if any) is the *configured default*, which can differ from
what's actually running if a session overrode it via `/model` or the setting was only just
applied. Sonnet is the documented default for the orchestrator - testing to date has not yielded
any better results from opus for orchestration; opus remains available for critical/high-stakes
engagements. State this every time, not only when asked - a live report (2026-08-03) found a user
only discovered they were running sonnet from a provenance stamp buried in a signed-off email,
well after the engagement had already run on it. If you don't know how to change it, say so:
*"(change with `python install_helper.py`, menu option 8, or `--model-project . --model opus`)"*.

**What's new (banner, one short line only).** Branch on the printed `VERSION_CHANGED=`; never
re-derive it. The probe also prints the newest CHANGELOG release block - the **plugin's** (or the
repo's own in repo-as-project), **not** the working project's, which is unrelated.
- `yes` **and** `PREV_TEAM_VERSION=` non-empty → *"🆕 Since last time (vX → vY): "* + up to three
  headline changes in plain words from that block, ending *"(full detail: CHANGELOG.md)"*.
- `yes` **and** `PREV_TEAM_VERSION=` empty (first engagement, no prior record) → *"🆕 In the
  current release (vY): ..."* - never guess what the user last saw.
- `no` → show nothing. This must never become a wall of release notes and never delays the first
  question.
- Changelog block empty (broken/partial install) while `yes` → banner and version as normal, omit
  the what's-new line; never surface probe mechanics to the user.

Either populated form is **part of the opening banner itself, not optional**. The comparison is
local files only (the map plus the bundled manifest and CHANGELOG), so it works identically for
manually copied / air-gapped installs with no git or network.

**Then your VERY NEXT output is the opening banner + disclaimers + the batched question that
follows in the calling skill.** Target: the probe call (with the operating-guide `Read` alongside
or immediately after it), then the ask - no other turns in between.
