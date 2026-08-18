# Incident log - live failures and their wasted-work loops

One dated entry per documented live incident, harvested 2026-08-18 by the runtime economics
audit (Track E, `docs/internal/ai-runtime-economics-audit-2026-08.md`). Purpose (token plan
Phase 3): runtime prompts keep an invariant plus a one-line dated tag; the story lives here.
When Phase 3 strips a narrative from a skill or agent file, link it to its entry below.

Format: date · failure shape · the wasted-work loop · fix now in place (mechanical vs prose)
· sources.

## Catalogue

1. **2026-07-30/31 · Windows Store `python3` alias-stub hang.** Every guard hook
   version-probed `python3` per fire; the stub triggers a multi-second Store redirect each
   time - one `/engage` hung for minutes as the stub fired dozens of times. Fix (mechanical):
   interpreter cache `.claude/.guard-interpreter`, OS-aware probe order, installer pre-warm.
   Sources: `docs/internal/dev-briefing-2026-08-10-plugin-engineering-challenges.md`,
   CHANGELOG ~1683, `.claude/skills/engage/references/probe-contract.md`.
2. **2026-07-31 · five hook processes per Bash call × endpoint-security scans.** Measured:
   51s for the step-0 probe alone, 1m31s for the next Bash call, ~2 minutes to open an
   engagement. Fix (mechanical): `scripts/bash_hook_dispatcher.py` runs all five checks in
   one process. Sources: dev-briefing, ADR-014.
3. **2026-08-11/12 · per-call guard cold start under Workflow fan-out.** 87 slow PreToolUse
   events, 2-9s normal, 25-90s under fan-out; guard path 1372-3808ms (median 1404ms) vs
   82-106ms bare interpreter; 8-way concurrent worst 21017ms. Fix (mechanical): run-guard.sh
   lock/wait fixes, then the ADR-014 guard daemon (12.6ms daemon vs 307ms cold-start median).
   Sources: CHANGELOG 0.33.54-0.33.60, ADR-014.
4. **2026-08-10 · `_raw_data_present()` full `os.walk` on nearly every Grep/Glob.** Fix
   (mechanical, human-applied): short-TTL file cache. Source: dev-briefing.
5. **2026-08-10 · eight chained `python.exe` cold starts for eight state changes in one
   intake** (one call 3816ms, one errored). Fix (mechanical): `set-decisions --json` batch
   subcommand. Source: dev-briefing.
6. **2026-08-10 · review-scorer explored via Bash `ls`/`cat` chains** (one chain 3555ms;
   Read/Glob spawn nothing). Fix: prose only (agent instruction). Sources: dev-briefing,
   `review-scorer.md`.
7. **2026-08-07/08 · sequential dispatch despite "concurrent" instruction - three prose
   fixes failed identically.** A 4-pass review went out as 4 lone calls across 4 turns;
   Morgan narrated "Dispatching both now, concurrently" then dispatched sequentially (proven
   via events.jsonl). Fix (mechanical): Workflow-tool `parallel()` (0.33.50), itself needing
   two live patches (args-as-string 0.33.51; never-invoked until named in the right-sizing
   statement 0.33.52). Context run: Flask core, 25 min, $12.66. Sources: CHANGELOG
   0.33.47-0.33.52, `deep-review/SKILL.md`, dev-briefing.
8. **2026-08-07 and 2026-08-10 · review-scorer delegation skipped** (audit-depth review with
   zero Pip calls, reviewers self-scored; later recurrence in a new shape: context step done
   inline by Morgan). Fixes: roll-call prose + mechanical PACK-UNSCORED gate in
   `check_artifacts` (scoring half only) + golden eval case ($14.80 first run). Sources:
   `deep-review/SKILL.md`, CHANGELOG 0.33.44/0.33.49.
9. **2026-08-05 · 13-finding consolidation Write hit the proxy timeout twice identically** -
   "retrying the identical giant write is not a retry that can succeed." Fix chain: prose
   chunking (0.33.24) → same timeout recurred → mechanical opt-in Write cap in
   `guard-findings-pack-write.py` (0.33.25) → JSONL append-safe format (0.33.46). Sources:
   CHANGELOG, `large-context-review-splitting-plan.md`.
10. **2026-08-07 · ~3-hour deep review of a small codebase** (30-min request timeout ×
    ~300-retry watchdog "can retry silently for hours", plus JSON-array patching on append).
    Fixes: JSONL (mechanical); env-tuning trade-off surfaced. Source: CHANGELOG 0.33.45.
11. **2026-08-10 · 71 findings extracted one `grep -o` at a time from a ~32k-token
    `journal.jsonl`** - "extracting the results took longer than the 11.8 minutes the three
    passes spent producing them." Fix (mechanical): each pass writes its own
    component-qualified pack directly. Sources: `.claude/skills/.shared/workflow-dispatch.md`,
    `large-context-review-splitting-plan.md`.
12. **2026-08-07 → 2026-08-16 · the PROBE_FAILED improvisation loop, five live reports:**
    improvised `python -c` (guard-blocked); re-verifying a version the probe printed; citing
    "per the contract I retry once" then running a different hand-assembled invocation (root
    cause: shell-snapshot SIGTERM cwd loss from a slow `.bashrc`); unquoted
    `C:\Python313\python.EXE` losing its backslashes (exit 127); hand-composed `cd C:\...`
    arriving as `C:Usersdev...` and the open wrongly judged probe-broken. Fixes: guard
    message names the recurring shapes, `PROBE-STDERR:` surfacing, forward-slash quoting
    rule, and ultimately the prefetch hook + probe cache (entry 13). Sources:
    `.claude/skills/engage/references/probe-contract.md`, `.claude/skills/.shared/engage-open.md`, CHANGELOG.
13. **2026-08-18 · live probe "can take minutes on corporate boxes"; Git Bash calls carried
    ~6s shell-snapshot overhead.** Fix (mechanical): `engage_probe_prefetch` hook injects a
    pre-computed probe; go writes the probe cache; completion-unload fix measured ~15x
    (snapshot ~6,196ms → ~261ms). Sources: `.claude/skills/.shared/engage-open.md`, commit 7c6968a.
14. **2026-08-17 (twice) · `/engage --new` engagement archaeology** - the session re-surveyed
    open packs the go menu had just shown the human. Fix (mechanical): prefetch injects
    `ENGAGE_FLAG=--new`, omits the resume menu; zero-discovery rule. Sources:
    `engage/SKILL.md`, CHANGELOG.
15. **2026-08-17 · sizing `find` dumped 217 paths into the transcript**, count inflated by
    caches/artifacts, mispricing the review. Fix (mechanical): map-first enforcement - Bash
    rule denies bare full-tree enumeration in engaged sessions. Sources: `.claude/skills/engage/references/review-menu.md`,
    CHANGELOG 0.34.0.
16. **2026-08-17 · three dispatched reviewers each re-crawled a repo whose codebase map
    existed** (per-pass cold repo reads). Fix: briefs carry file list + map path ("point,
    never paste") + the mechanical enumeration deny. Sources: `deep-review/SKILL.md`,
    `code-reviewer.md`.
17. **2026-08-16/17 · deep + security + perf went out as 6 subagent passes where the
    topology prices 3, "roughly doubling the engagement's cost"** (related: improvised
    recommend-security question; 5 agents staffed for a report-only review). Fix: consolidated
    review topology - one code-reviewer pass runs all lenses, security is a lens; locked
    review menu. Sources: `deep-review/SKILL.md`, `.claude/skills/engage/references/review-menu.md`.
18. **2026-08-17 · CHANGELOG body dumped into the transcript on every post-update open.**
    Fix (mechanical): probe prints `WHATS_NEW=` heading line only. Source: `.claude/skills/.shared/engage-open.md`.
19. **2026-08-17 · a `cd` into the plugin repo silently flipped plugin-mode into
    repo-as-project**, pointing engagement state at the wrong project. Fix: PROSE ONLY
    ("never prepend cd"). Source: `.claude/skills/.shared/engage-open.md`.
20. **2026-08-08 (twice) · deliverables written into the plugin's own source tree** instead
    of the working project; recurred on the very next run after being documented. Fix: PROSE
    ONLY (relative-path rule); Bash-less diagnostic mode explicitly "flagged, not addressed".
    Sources: CHANGELOG 0.33.52-53, `.claude/skills/.shared/run-mode.md`.
21. **2026-08-16 · `.shared` sibling-path stumble** - Read the `skills/engage` directory,
    guessed `skills/engage/.shared`, "burned two failed calls on a corp box where every call
    is seconds". Fix: PROSE ONLY. Source: `engage/SKILL.md`.
22. **2026-08-12 · STALE-INDEX fired on a session's first turn** (artifact row registered
    before the brief was written). Fix: detection mechanical (DoD backstop), prevention
    prose. Sources: `engage/SKILL.md`, `engage-light/SKILL.md`.
23. **2026-08-16 · consent-write guard denied a legitimate `set-decision` mid-intake**
    (lexical match on the marker path; related 2026-08-05 false positive on a read-only
    heredoc mentioning settings.json). Fix (mechanical): `engagement_state` refuses
    consent-shaped keys; prose keeps the marker path out of Bash text. Sources:
    `.claude/skills/engage/references/safety-gates.md`, `whole-plugin-review-2026-08-05.md`.
24. **2026-07-27 → 2026-08-01 · consent prompts for the team's OWN tooling (allow-list
    drift, recurring class).** Quoted paths with spaces never matched; live guard drifted
    from staged, missing `engage_probe` et al., so `/engage` consent-prompted on its own
    probe. Root aggravator: sync tests `pytest.skip()`ed on mismatch - "the regression net
    went quiet at precisely the moment it had something to report". Fix (mechanical):
    `tests/test_hooks_in_sync.py` FAILS on drift, whole hooks object compared. Sources:
    CHANGELOG 0.29.1/0.33.3/0.33.6, dev-briefing, CLAUDE.md §7.
25. **2026-07-31 / 2026-08-04 · cp1252 Unicode family** - probe silently failed on cp1252
    consoles (all three interpreters crashed on `print()`, hidden by `2>/dev/null`);
    check_artifacts crashed on emoji; shell-capture decode error after the first fix. Fix
    (mechanical): `PYTHONIOENCODING=utf-8` everywhere + ASCII-safe report. Sources:
    CHANGELOG, `.claude/skills/engage/references/probe-contract.md`.
26. **2026-07-31 · REGISTRY-HTML-STALE re-fired on every mutation with no way to clear it**
    (plugin-mode `render_html` import failure silently skipped every render). Fix
    (mechanical): package-import-first/`__file__`-fallback import pattern. Source: CHANGELOG.
27. **2026-08-11 → 2026-08-17 · DoD Stop gate pulled sessions into other engagements' work**,
    then kept "reasoning about other engagements' DoD tasks at every stop". Fixes
    (mechanical): auto-fix scoped to active engagement (0.33.54); sibling-quiet gate
    (commits c88375b, 8ea0fd5). Sources: CHANGELOG, commit messages.
28. **2026-08-18 · single-deliverable close invented wrapper documents** (a `/why-no-alert`
    close demanded an "engagement report" over a complete diagnosis). Fix (mechanical half):
    deterministic naming, `delivery-report.md` reserved close-only in `check_artifacts`,
    test-pinned. Sources: `.claude/skills/.shared/engagement-bookends.md`, commits c88375b/b359994.
29. **2026-07-23/24 · persona and soft-discipline fade after compaction; index trailing
    reality after a compaction failure.** Fixes (mechanical): per-turn re-anchor hook
    (`scripts/persona_anchor.py`, ADR-005; measured ~0.07% of run cost), index-first
    START-HERE + Stop-hook backstop, ~1,500-token subagent return budget
    (`scripts/subagent_return_budget.py`, advisory). Sources: `resolved-issues.md`,
    CHANGELOG, `agent-design.md`.
30. **2026-07-21 · `/engage` open was 7-10 sequential tool calls; later the probe inlined
    ~32KB of operating guide through stdout** (tripping the harness output limit). Fixes
    (mechanical): one compound probe (0.16.0); guide inlining removed, test-pinned. Sources:
    CHANGELOG, `.claude/skills/engage/references/probe-contract.md`.
31. **2026-07-21 · code shipped from `/analyse-data` with no QA and no tests** (rework
    loop). Fix (mechanical): CODE-NO-QA / CODE-NO-TESTS gates. Sources: CHANGELOG,
    `analyse-data/SKILL.md`.
32. **2026-08-03 · four specialists ran while the engagement state file still said what
    `init` had never set** (work invisible on disk, resume impossible). Fix: bookends prose +
    mechanical DoD stop-gate backstop. Source: `remediate/SKILL.md`.
33. **2026-08-03/07 → 2026-08-17 · locked-menu drift family**: a session carried
    `Execution` into the review-menu call (guard caught it, friction real); the go-ahead
    gate re-asked scope on a post-gate screen. Fixes (mechanical): locked menus +
    `locked_menu_guard.py`; Origin joined the locked set; fine-scope axes derived, not
    asked. Sources: CHANGELOG, `.claude/skills/engage/references/review-menu.md`, token plan.
34. **2026-08-13 · 7 of 12 concurrent writes lost** (state file read-modify-write with no
    locking under parallel dispatch, reproduced live). Fix (mechanical): cross-process lock
    with stale-lock reclamation - which itself caused a fingerprint bug caught by the full
    suite (0.33.62). Source: CHANGELOG.
35. **2026-07-29 · PDF hand-parsed via PowerShell binary bytes** (converter unknown to the
    session). Fix (mechanical): `document_input_redirect.py` PreToolUse hook +
    `convert_file --layout`. Source: CHANGELOG.
36. **2026-07-27 · plugin-mode specialists could not reach the DoD criteria** (repo-relative
    path in a foreign project) - the verifier reported "cannot verify". Fix: PROSE ONLY
    (briefs carry resolved absolute paths). Source: CHANGELOG.
37. **2026-07-02 · Windows permission-rule churn** (invalid auto-saved rules accumulating
    per approval). Fix: prose/config convention. Source: CHANGELOG.
38. **2026-07-05 · multi-`.py` guard false positive blocked read-only git commands live
    during an audit.** Fix (mechanical, human-applied): lookbehind. Sources: CHANGELOG,
    ADR-002.
39. **2026-08-07 · haiku subagent 400 error on a beta field** (gateway rejecting
    `eager_input_streaming`). Fix: opt-in env config. Source: CHANGELOG.
40. **2026-08-17 · version-lag misdiagnosis family**: a corp box one pull behind caused
    misdiagnosis of already-fixed behaviour; stale aliases stacked; dead install-registry
    entries. Fixes (mechanical): version-lag detection, alias self-heal, registry repair.
    Sources: `backlog-map-first-review-scoping-2026-08-17.md`, commits ab6d6e9..af2420d.
41. **2026-08-01 · eval pass rate unreadable** - infrastructure deaths folded into the same
    boolean as content failures (35% "pass rate" was really 47% over scorable runs). Fix
    (mechanical): pass/fail/unscorable classification. Source: CHANGELOG 0.33.6.

## Loops with NO mechanical fix yet (prose-only)

`cd` wrong-mode flip (19) · plugin-root deliverable-write leak (20, explicitly "flagged, not
addressed" for Bash-less mode) · Pip's Bash `ls`/`cat` habit (6) · `.shared` sibling-path
stumble (21) · STALE-INDEX prevention ordering (22) · sequential dispatch on the Task-batch
FALLBACK path (0.33.49 investigated and declined a mechanical check: "no reliable mechanical
check today") · Pip context-step delegation (8's 2026-08-10 half; PACK-UNSCORED covers
scoring only) · chunked consolidation above ~8 findings (Write cap is opt-in) · subagent
return budget (advisory, fires after the cost lands) · probe-block retry compliance (12; the
exec guard blocks `python -c` but "retry the exact block" is prose) · slow-`.bashrc`
snapshot SIGTERM (host-side) · DoD-criteria absolute paths in briefs (36) · model-identity
banner · Windows permission-rule spelling (37).

## Classes that recurred AFTER a prose fix (prose alone demonstrably failed)

1. Concurrent dispatch - three prompt-only rewrites failed identically, once while the model
   narrated the opposite; even the mechanical fix needed two live patches.
2. Consolidation-write timeout - prose chunking, "the same timeout recurring, prose guidance
   under pressure isn't reliable enough on its own" (CHANGELOG verbatim) → guard cap → JSONL.
3. review-scorer delegation - documented twice, still skipped; recurred in a new shape.
4. Probe improvisation - five live reports over nine days, each after docs were
   strengthened; one cited the contract while violating it.
5. Guard allow-list omissions - three occurrences until the sync test switched from skip to
   FAIL.
6. Stop-gate scope - auto-fix scoping was not enough; sibling reasoning cost persisted until
   the sibling-quiet gate.
7. Reviewer repo enumeration - "never enumerate" prose existed; the 2026-08-17 run
   re-crawled anyway → Bash deny rule.
8. `--target-path` artifact leak - "happened again on this run" immediately after
   documentation; STILL prose-only.

## Documented cost numbers (verbatim, with sources)

- 51s step-0 probe / 1m31s next Bash call / ~2 min to open (dev-briefing, 2026-07-31).
- 87 slow PreToolUse events; guard 1372-3808ms vs 82-106ms bare; 8-way worst 21017ms;
  daemon 12.6ms vs 307ms cold (ADR-014).
- 3816ms chained state call; 3555ms `ls`/`cat` chain (dev-briefing, review-scorer.md).
- ~32k-token journal; extraction took longer than the 11.8-minute passes
  (workflow-dispatch.md).
- ~3-hour deep review stall (CHANGELOG 0.33.45).
- Snapshot ~6,196ms → ~261ms, ~15x (commit 7c6968a).
- ~500k tokens / $4-8 full 9-agent delivery (docs/demos/build-artifacts/delivery-report.md);
  ~182k 8-agent delivery; ~51k / ~$2 one code review (README).
- $12.66 Flask review run; $14.80 eval case; $2.3-$102 per-engagement spread at 0.29.0.
- Persona anchor ~$0.04 of a $62.48 run (0.07%, ADR-012).
- Multi-agent ~15× tokens (large-context-review-splitting-plan.md); 6-passes-vs-3 "roughly
  doubling" (deep-review); direct-answer path cut one case 86%; opus 57% of one split
  review's cost.
- **Correction to the 2026-08-18 external review: no "775k-token review" exists in this repo
  or its git history** (grep + pickaxe over all history). The largest documented run is the
  ~500k delivery above.
