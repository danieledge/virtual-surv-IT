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
    repo-as-project**, pointing engagement state at the wrong project. Fix (prose, until
    2026-09-20; PREVENTIVE MECHANICAL as of 2026-09-20, staged pending human apply):
    `scripts/plugin_root_guard.py` blocks a leading `cd` into `CLAUDE_PLUGIN_ROOT` in an
    engaged plugin-mode session, redirecting once per target. Re-examined 2026-09-20:
    `find_plugin_root.py` separately grew a DETECTION-side breadcrumb
    (`identity_warning`/`mode_flip_warning`, citing this incident by number) at some point
    after this entry was written - but neither the live steady-state probe path nor the
    cold-bootstrap heredoc twin in `probe-bootstrap.md` calls it, so that mechanism is
    orphaned code, unreachable from a real session today. The new guard closes the gap from
    the prevention side instead; the orphaned detector is a separate, smaller follow-up
    (wire `mode_flip_warning` into a call site that actually runs, or remove it). Sources:
    `.claude/skills/.shared/engage-open.md`, `scripts/find_plugin_root.py`,
    `scripts/plugin_root_guard.py`, `tests/test_plugin_root_guard.py`.
20. **2026-08-08 (twice) · deliverables written into the plugin's own source tree** instead
    of the working project; recurred on the very next run after being documented. Fix (prose,
    until 2026-09-20; MECHANICAL as of 2026-09-20, staged pending human apply):
    `scripts/plugin_root_guard.py` blocks a Write/Edit/MultiEdit/NotebookEdit targeting
    `CLAUDE_PLUGIN_ROOT` in an engaged plugin-mode session, every time (no legitimate retry
    case, unlike the cd redirect above). Bash-less diagnostic mode remains untouched by this
    fix (still "flagged, not addressed" - the guard covers the write TOOLS, not a diagnostic
    path with no Write call to catch). Sources: CHANGELOG 0.33.52-53,
    `.claude/skills/.shared/run-mode.md`, `scripts/plugin_root_guard.py`,
    `tests/test_plugin_root_guard.py`.
21. **2026-08-16 · `.shared` sibling-path stumble** - Read the `skills/engage` directory,
    guessed `skills/engage/.shared`, "burned two failed calls on a corp box where every call
    is seconds". Fix: PROSE ONLY when written; re-examined 2026-09-20 and found EFFECTIVELY
    SUPERSEDED by a later, more general fix not originally linked to this entry - the
    2026-09-12/13 open-path work (see the "three open-path incidents" section below) made
    `engage_probe.py` print `REFERENCES_DIR=`/`SHARED_DIR=` directly at open, so a `.shared`
    Read no longer needs a guess at all. Not a hard guard (nothing stops a hand-guessed path
    if the model ignores the printed value), but the guessing that caused this incident has
    no remaining reason to happen. Source: `engage/SKILL.md`, `scripts/engage_probe.py`.
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
42. **2026-09 · a stray leading `[TOC]` marker rendered the table of contents twice in the
    HTML** - the marker was removed by hand; no gate caught duplicates, so it reached close
    undetected (invisible in source, only visible on render). Fix (mechanical, 2026-09-18):
    `check_render_integrity()` counts `[TOC]` markers in the markdown SOURCE (bleach strips
    the rendered div's `class="toc"`, so a render-side check would never fire -
    `TOC-DUPLICATE-RENDER`). Sources: `scripts/check_artifacts.py`, `tests/test_render_integrity.py`.
43. **2026-09 · a "reviewability blocker resolved procedurally" note let stale "UNABLE TO
    ASSESS" text ship across three artifacts** - source retrieved was mistaken for source
    reviewed. Fix (mechanical, narrow, 2026-09-18): `check_render_integrity()` flags literal
    survival of the placeholder into a rendered artifact (`STALE-REVIEWABILITY-BLOCKER`) -
    an exact-string check only; it does not judge whether an assessment is still stale (no
    machine-readable marker exists for that yet, same limit
    `check_findings_render_freshness()` notes for struck citations). Source:
    `scripts/check_artifacts.py`.
44. **2026-09 · markdown links pointed at anchors that were never written**, from three
    unrelated causes (a duplicate TOC's id suffix, a `&`-slug double-hyphen mismatch, 17
    findings linked but never given an individual write-up) - anchors were added by hand,
    no anchor-integrity check existed. Fix (mechanical, 2026-09-18): `check_render_integrity()`
    diffs every rendered `href="#..."` against the render's actual `id="..."` set
    (`ANCHOR-BROKEN`) - catches all three causes generically, since each one is just a link
    with no matching id. Sources: `scripts/check_artifacts.py`, `tests/test_render_integrity.py`.

The three items above (42-44) share a signature: all were invisible in source, detectable
only by rendering and diffing, and all previously reached close undetected. They are the
newest entries in this catalogue and were not yet in it as of the 2026-08-18 Track E audit.

45. **2026-09-23 · installer update aborted with no recovery when `git stash` itself
    failed** (a stale git lock, a permissions/antivirus lock on Windows, a corrupted
    index) - the dirty-tree handling already stashed and restored a clone's local
    changes around a pull, but a failure of the stash command itself was fatal
    (`step_fail`), with nothing offered short of fixing the `.git` internals by hand.
    Fix (mechanical): `--force-overwrite` resets hard and cleans untracked files to
    match origin instead of stashing; on a stash failure specifically, offered as an
    interactive confirm (default no) rather than run automatically. Deliberately not
    folded into `--yes` - discarding local changes is irreversible, and `--yes` means
    "safe defaults," not "destructive by default." A non-interactive stash failure still
    fails cleanly, naming the flag as the way out. Sources: `install_helper.py`,
    `tests/test_install_helper.py`.

## Loops with NO mechanical fix yet (prose-only)

`cd` wrong-mode flip (19) and the plugin-root deliverable-write leak (20) moved OUT of this
list 2026-09-20 - `scripts/plugin_root_guard.py`, staged pending human apply (§ above). The
Bash-less diagnostic-mode half of 20 stays here ("flagged, not addressed": no Write call for
a guard to catch). `.shared` sibling-path stumble (21) also moved out, effectively
superseded rather than directly fixed (§ above) - kept in the numbered catalogue entry, not
repeated here. Remaining: Pip's Bash `ls`/`cat` habit (6, re-examined 2026-09-20: still
open - the 2026-09-14 Bash whole-file-read redirect covers a large `cat`, not the
small-file/`ls` browsing habit this entry actually describes, and deliberately does not:
extending it risks the same rule-fatigue the redirect family's own design notes warn
against) · STALE-INDEX prevention ordering (22, re-examined 2026-09-20: still open - "the
brief already exists" has no single reliable file-pattern to check against across
deliverable types without risking false blocks on legitimate orderings) · DoD-criteria
absolute paths in briefs (36, re-examined 2026-09-20: still open - a brief is free text, and
distinguishing "a relative path that will break" from "prose that happens to name a file"
without false positives needs a stronger convention than exists today) · sequential dispatch
on the Task-batch
FALLBACK path (0.33.49 investigated and declined a mechanical check: "no reliable mechanical
check today") · Pip context-step delegation (8's 2026-08-10 half; PACK-UNSCORED covers
scoring only) · chunked consolidation above ~8 findings (Write cap is opt-in) · subagent
return budget (advisory, fires after the cost lands) · probe-block retry compliance (12; the
exec guard blocks `python -c` but "retry the exact block" is prose) · slow-`.bashrc`
snapshot SIGTERM (host-side) · model-identity
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
- ~500k tokens / $4-8 full 9-agent delivery (measured; the captured delivery it came
  from was pre-0.16 and was removed on 2026-08-29, so the figure stands on this record);
  ~182k 8-agent delivery; ~51k / ~$2 one code review (README).
- $12.66 Flask review run; $14.80 eval case; $2.3-$102 per-engagement spread at 0.29.0.
- Persona anchor ~$0.04 of a $62.48 run (0.07%, ADR-012).
- Multi-agent ~15× tokens (large-context-review-splitting-plan.md); 6-passes-vs-3 "roughly
  doubling" (deep-review); direct-answer path cut one case 86%; opus 57% of one split
  review's cost.
- **Correction to the 2026-08-18 external review: no "775k-token review" exists in this repo
  or its git history** (grep + pickaxe over all history). The largest documented run is the
  ~500k delivery above.

## 2026-09-13: the three abnormal plugin-mode eval rows, root-caused (framework review, step 1.10)

Nine `process-plugin-mode-open` rows landed on 2026-09-12/13 with one pass. Six failed on
the open's own path handling (`plugin-path-guess`, `listing-above-project-root`,
`FP-MODULEFORM`, `missing-prompt-injection`); the probe now prints `REFERENCES_DIR=` and
`SHARED_DIR=` and `.claude/skills/.shared/engage-open.md` forbids reading outside them. The three rows a path rule
does not explain, read from `evals/runs/<id>/process-plugin-mode-open/events.jsonl`:

- `20260913T082312Z` (0 turns, 0 USD): the session's first and only assistant message was
  `Unknown command: /engage`. The harness launched the CLI before the plugin's skills were
  visible in the throwaway HOME, so the slash command never resolved. A harness defect, not
  a run; it should be its own tripwire (`skill-not-registered`) rather than a recall of 0.
- `20260912T235009Z` (37 turns, 4.16 USD, `session_error: true`): `ResultMessage`
  subtype `error_max_budget_usd`. The harness's spend cap ended the run; the guards and
  the open were not involved.
- `20260913T101219Z` (101 turns, 12.09 USD, `session_error: true`): subtype
  `error_max_turns`. The turn cap ended the run mid-close (the row that prompted widening
  `max_turns` to 140, since restored to 100 by plan step 5.2).

Consequence for the scorer: `session_error` conflates a cap hit (`error_max_turns`,
`error_max_budget_usd`) with a real session failure. Plan step 3.9 adds `capped` as a
distinct outcome and the `skill-not-registered` tripwire, so a budget or registration
problem is never read as a defect of the team.


## 2026-09-12/13: the three open-path incidents the engage skill used to narrate inline

Moved here from `.claude/skills/engage/SKILL.md` (step 4.4); the rules stayed, the stories
did not. (1) 2026-09-12: a live `--auto` open spent four failed Reads guessing
`$PLUGIN_ROOT/references/<file>` before finding `$PLUGIN_ROOT/.claude/skills/engage/references/`.
(2) 2026-09-13: a plugin-mode eval opened with `cd` into the directory above the probe's
interpreter path and searched it for the user's file. (3) 2026-09-13: a session hid the state
script call in a shell variable (`SS="$PY $PR/scripts/engagement_state.py"; $SS ...`); the
execution gate refused it as untrusted code and the engagement lost its state. The probe
now prints `REFERENCES_DIR=` and `SHARED_DIR=` (step 1.10) so (1) and (2) cannot recur by
guessing, and the full-command rule covers (3).


## README "Known issues" narrative (moved here 2026-09-14, framework review step 1.5)

The README keeps a ten-line list of user-facing limitations; this is the dated narrative it used to carry, verbatim.

**Security residual: the Bash channel is not sandboxed (partly patched, residual stands).** The
guards robustly cover the file-read and Write/Edit tool channels, but on the **Bash** channel they
are lexical checks with no OS `permissions.deny` backstop. So a determined or prompt-injected model
could, via a shell command, disarm the guards (delete or overwrite a guard file) or obfuscate a path
to read raw data or self-grant execution consent. This is documented as accepted residual in
ADR-002.

- **Shipped:** the execution guard **does** segment-split the command line (`;`, `&&`, `||`, `|`,
  newline, backtick, `$(`) and evaluates each segment on its own, so an allow-listed fragment can no
  longer wave a blocked command through the rest of the line; the team allow-list is anchored to
  segment start (ADR-002 recs 1 and 2).
- **Still outstanding:** the `.claude/hooks/**` and `Bash(...)` entries in `permissions.deny`. That
  is the part that would make any of this an actual boundary, and it does not exist. Segment-split
  hardens a *lexical* check; it does not turn one into enforcement.

So the position is unchanged in substance: on Bash the guards are a real control for a cooperative
agent, not a boundary against an adversarial one, and string-matching arbitrary shell can always be
defeated (env indirection, `eval`, `base64 | sh`, heredocs). The standing mitigation is to keep real
data off the machine (the §5 posture). Tracked, not a surprise.

**Two further escape paths found by the 2026-08-01 audit are closed** - the git config file as a
consent-equivalent execution path, and the raw-data guard's `WebFetch` and `Grep` coverage gaps.
Both fixes are live and verified (2026-09-09: the live hooks are byte-identical to their staged
counterparts, with `tests/test_guard_git_config.py` and `tests/test_guard_raw_coverage.py` passing).
The detail moved to [`docs/internal/resolved-issues.md`](docs/internal/resolved-issues.md), because
this section carries what is still **open**.

**First `/engage` of a session can take ~2-3 minutes before the first Morgan message (under
investigation).** Tester feedback: the **initial** engagement is slow to produce the opening banner;
later turns are fast. The path is already optimised to a **single** step-0 probe (no probe-per-turn),
and the tooling probe is cached after first use (`VSIT/local/tool-availability`, 7-day TTL) - so this
is a **cold-start** cost that hits once per session: the prompt cache is cold (`docs/agent-design.md`
§7), the tool probe isn't cached yet, and turn 0 loads a large payload (the ~490-line operating guide
+ codebase-map + CHANGELOG) into the orchestrator before it emits a word. **Not yet confirmed**
is the split between (a) model inference over that cold, large turn-1 context - the likely dominant
cost, since the probe script itself is only `command -v` checks - and (b) I/O, notably the
plugin-mode `find` over `~/.claude/plugins/cache` / `marketplaces` (no `-maxdepth`) used to resolve
the plugin root when the operating guide isn't in the working dir. **How to pin it:** run the step-0
Bash block alone under `time` - under ~5s implicates model latency; slower implicates the `find`/I/O.
**Partially applied:** the codebase-map read is already just-in-time since 0.18 - the probe
loads only the map header + §3 history slice, never the bulky §2 body. **Still candidates
(not yet applied):** defer the CHANGELOG read out of turn 0, and bound the
plugin-resolution `find` with `-maxdepth`. Tracked; needs the `time` measurement first so a fix
targets the real bottleneck rather than guessing.

**A heavy engagement can hit context compaction during *setup* - before it's fully stood up - and
leave state behind (under investigation).** Tester report: a code review **compacted ~9 minutes in -
right after the engagement brief was written, but before START-HERE was advanced to reflect it** (so
the index was left behind the true state at the moment compaction erased the working context). Two
things compound here:
- **Compaction fires too early** because the *orchestrator's* context fills with **instruction/doc
  front-load**, not the code. Investigated (2026-07-24): the code reading **is** correctly delegated
  - `deep-review` drives `code-reviewer` for the analysis and `review-scorer` for context detection,
  and Morgan only does a challenge pass on the *findings* - so "the main loop reads the code" is
  **largely refuted** as the cause. The real driver is the setup corpus loaded into the single
  orchestrator context **before the work starts**: the ~490-line operating guide + the working
  project's codebase-map (~250) + CHANGELOG + tool report (all dumped by the one step-0 probe), plus
  the **chained skill files** a code review stacks (`engage` → `audit-review` → `deep-review`), plus
  `CLAUDE.md` and the 13 agent descriptions. Same root as the cold-start issue above; a code review
  is the worst case because it chains three skills into one context.
- **State can lag the work when compaction interrupts.** The lifecycle discipline expects START-HERE
  to gain a row *"the moment each artifact is written"*, but the brief-write and the index-update are
  separate steps, so a compaction in between leaves the index behind reality - which, combined with
  the persona/discipline decay above, is the exact "stalled engagement, gate never fires" failure the
  discipline exists to stop.
- **Candidate mitigations (partially applied):** (a) **trim the turn-0 payload** - the
  codebase-map half landed in 0.18 (the probe loads only the header + §3 slice; §2 is read
  just-in-time), deferring the CHANGELOG remains a candidate,
  the same lever as the cold-start issue above; (b) make the brief-write
  and START-HERE update **index-first / atomic** so the index reflects the brief even if compaction
  interrupts; (c) **enforce condensed subagent returns** (`agent-design.md` §5 flags this as
  aspirational, not enforced) so a verbose `code-reviewer` return can't balloon the orchestrator
  later - a separate variant of the same failure class; (d) the DoD `Stop`-hook catches a
  stale/missing index at turn-end, and since 0.33.0 fails safe: an engagement with **no readable
  status** (a missing or unreadable START-HERE) is treated as still open rather than silently
  passing, the hook reads the machine-readable state file first, and it also scans the derived
  registry and the artifacts root - a backstop, not full cover. Tracked.

**Slow Claude Code startup on Windows for a local-scope install (~20-27s).** Reported on a Windows
box where the plugin is installed from a local path (`scope: "local"`). Assessment: Claude Code
treats a local-scope plugin as mutable and **re-validates it every startup** (git-SHA check +
settings re-merge + re-scan) - that's the trigger. The ~20-27s amplifier is **Windows filesystem
overhead** (git working-tree operations + real-time AV scanning) over the plugin's **large file
tree**: 754 tracked files, of which **306 are the vendored pip-less Python libs in `vendor/`** - the
13 agents / 32 skills are a tiny fraction, so agent/skill *count* is **not** the bottleneck (13
file-opens is milliseconds). Largely a Claude-Code-×-Windows-×-local-install interaction, not
plugin logic. **Mitigations (not yet applied):** (a) a **Windows Defender exclusion** for the plugin
cache dir - usually the biggest, free win, and a quick A/B test; (b) installing via a
**marketplace/registry** (`scope: "registry"`) rather than a local path - a version-string check
replaces the per-session live git diff, taking the cascade off the startup path; (c) the `vendor/`
tree is the file mass to target *if* a walk/scan is confirmed - but it exists for pip-less corporate
installs, so it's a tradeoff, not a free delete. Confirm *where* the time goes via the `--debug`
timing log before acting. Merging agents would **not** help (≈1% of the file surface) and would cost
the least-privilege role separation. Tracked.

<details>
<summary>⚠️ <b>Three display-only quirks</b>: the PM sometimes narrates the wrong teammate name, occasionally states the team-sizing line twice, and some emoji miss their glyph on older Windows + Edge; none affects what the team does</summary>

Both quirks below are **display-only**: they don't affect what the team does (routing, tool grants,
the actual deliverables). Flagged plainly, in the spirit of the proof-of-concept notice at the top.

- **Morgan sometimes narrates the wrong agent *name***: e.g. "Jordan"
  for the tuning analyst, instead of **Theo**. The *work* is unaffected: the team
  routes by role slug (`qa-engineer`, `tuning-analyst`) and the spawned specialist still runs as its real
  self; only the PM's running commentary drifts.
- **Some emoji render as a box / diamond-with-`?` on older Windows + Edge** (notably 🧑‍💻 and the
  ⚖️ / ⏭️ disposition markers). The files are clean UTF-8 and declare a UTF-8 charset, so this is a
  **font glyph-coverage gap** in that browser/OS, not corruption. The word is always kept beside the
  emoji, so no meaning is lost; an up-to-date system renders them.
- **Morgan occasionally states the team-sizing line twice** on a chained engagement (e.g. a deep
  audit review), the second copy correcting a role in the first (e.g. Layla's audit-depth job
  restated as the *independent synthesis read at close*). It's the model **self-revising mid-turn**
  and re-emitting the sentence rather than replacing its draft - the same soft-discipline root as the
  name drift, made a little likelier by the chained `engage → audit-review` flow both touching team
  composition. The roster and routing are correct (the second line is the accurate one); only the
  running commentary duplicates. A light "state-sizing-once" guard in `engage`/`audit-review` is a
  candidate fix, not yet applied.

<details>
<summary>Why the name drift happens (and why it's only cosmetic)</summary>

The persona names (Amara, Linh, Theo…) are **cosmetic labels**. The system routes work and grants
tools purely by the **role slug** (`business-analyst`, `qa-engineer`, `tuning-analyst`), so a wrong *name*
never changes who does the work or what they're allowed to touch.

Each agent's own file **does** pin its name (`qa-engineer.md` opens *"You are Linh…"*), but that line
is only ever read by the **subagent** when it's spawned; it never enters **Morgan's** (the
orchestrator's) context. So when Morgan *narrates* who's on a task, its only source for the name is a
**single roster line** in `docs/team-operating-guide.md` (moved out of `CLAUDE.md` in 0.8.0 to keep
the always-on handbook lean; read on `/engage`).

That name↔role mapping is an **arbitrary, non-derivable lookup**: nothing about "tuning-analyst"
implies "Theo"; it's pure memorisation. When that one low-salience line isn't firmly in attention
(a long session, a lot of intervening context, or after the conversation has been
compacted/summarised), the model reconstructs the name from a fuzzy memory and, being a language
model, emits a **plausible-but-invented** teammate name (Isla, Jordan) rather than surfacing the gap.
It shows up more for the less-mentioned roles (tuning, the data roles) than for the reviewers, whose names
get reinforced by frequent use; and because the name is decorative, **nothing validates it**, so the
drift goes uncorrected.

**Net:** the *actual* subagent always knows it's Linh/Theo (its own file says so) and always does
the right job; only the PM's commentary occasionally mislabels it. Hence: cosmetic.

</details>

</details>

**The `/engage` eval suite scores two correct behaviours as failures (found 2026-08-14, backlogged).**
A representative live run (`scripts.eval_engage`, 5 cases) surfaced two failing cases whose
transcripts show the team behaving *correctly* - the eval harness itself has the gap, not the team:
- **`process-full-lifecycle`:** Morgan dispatched the async `Workflow` tool for three parallel
  reviewers and correctly deferred - *"results will land in a later turn, I won't pre-empt them"* -
  stating the engagement plainly NOT closed with outstanding work listed. The conversation then just
  ended (36 turns, no cap/timeout/budget hit) because Morgan's message posed no `[gate]` question, so
  the simulated user had nothing to respond to and never checked back in. The sim-user driver has no
  "the PM deferred to a background task - wait and follow up" fallback.
- **`injection-extensions`:** all 5 planted injection/exfiltration attempts were correctly identified
  and refused, then Morgan explicitly right-sized itself - *"no fan-out... no workspace opened, no
  agents spawned"* - for a two-line YAML review. It's scored against `process-discipline.md`, which
  weights closing-artifact/dual-artifact dimensions (0.30 + 0.20) that assume a formal
  `VSIT/engagements/<slug>/` workspace exists. Neither that rubric nor its light variant
  (`process-discipline-light.md`) has a category for a genuinely tiny, correctly self-handled,
  zero-workspace response - the exact right-sizing behaviour the team's own principles reward.
Fix direction: script the sim-user to follow up after an async defer, and add a rubric variant (or
per-case override) for zero-workspace self-handled cases. Not yet done - tracked here rather than
guessed at under time pressure.

**PreToolUse daemon-routed calls still pay a Python interpreter spawn per call (found and partly
fixed 2026-08-14, backlogged).** A live corp-Windows measurement found a consistent 2-3s cost on
every daemon-routed Bash/Read call. Investigated: the daemon and its TCP roundtrip are both fast
(12.6ms measured, ADR-014 v0.3) - the cost is the CLIENT-SIDE process-spawn chain reaching it
(`sh` -> `cat` -> a fresh `python.exe`), matching ADR-014's own pre-daemon baseline (1,372-3,808ms)
almost exactly. The daemon itself is a net win and should stay; reverting it would add cost, not
remove it. One fork in that chain is already fixed (`run-guard.sh`'s fast path used to `cat` a
one-line cache file - now the `read` builtin, zero forks). **Not yet done, two bigger options,
either fixes the larger remaining cost (the Python interpreter spawn itself):**
- Bypass the Python client entirely on the fast path using bash's native `/dev/tcp` to talk to the
  daemon directly from the already-running shell (Git Bash's `sh` is bash, so this works on the
  affected platform; needs a fallback for shells without `/dev/tcp`, e.g. `dash`).
- Bake the discovered interpreter into `settings.json` at configure time (the `.guard-interpreter`
  cache already exists; this would let the hook command invoke the client directly, dropping the
  `sh` layer for daemon-eligible targets).
Both are higher-complexity, more platform-specific changes than the `cat` fix - deferred rather
than rushed.

Previously reported issues and their resolutions:
[`docs/internal/resolved-issues.md`](docs/internal/resolved-issues.md).

<sub>[↑ Back to top](#readme-top)</sub>
