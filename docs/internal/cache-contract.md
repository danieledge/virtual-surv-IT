# Cache contract - the shared facts, in one table

**Date:** 2026-08-18 · **Origin:** token plan Phase 6 item 2
(`docs/internal/token-optimisation-plan-2026-08-18.md`): the cache/TTL logic grew across
several mechanisms; this is the single owner/lifetime/invalidation record so nobody pays
twice for a fact that hasn't changed, and nobody trusts a fact past its invalidation
condition. Descriptive, not aspirational - each row states what the code does today.

| Shared fact | Store | Owner (writer) | Lifetime / TTL | Invalidation | Consumers |
|---|---|---|---|---|---|
| Engage probe result (report + interpreter) | `VSIT/local/engage-probe.json` | `go` launcher (pre-computes); `engage_probe_prefetch` hook injects | 1 hour (`_PROBE_CACHE_TTL_S`), plus identity fingerprint | TTL expiry; team-preferences mtime change; **git branch/HEAD moved; plugin version changed** (fingerprint, 2026-08-18); missing/odd file → live heredoc fallback | session open (banner, session rules) |
| Guard interpreter word | `VSIT/local/guard-interpreter` | guard hooks / installer pre-warm | until the interpreter changes | manual; installer self-heal; probe bootstrap tries it first and falls through on failure | every hook fire; probe bootstrap; `<python>` for the session |
| Analyser inventory (tooling report) | `VSIT/local/tool-availability` (compact form since 2026-08-18) | `check-review-tools.sh` | 7 days (`CST_TOOLCHECK_TTL_DAYS`) | `--refresh` after installing/removing tools; TTL expiry | probe/banner; reviewer briefs; reviewers' skip-missing rule; dashboard regexes |
| Codebase map | `VSIT/shared/map.md` (+ `codebase-map.d/`) | PM at engagement close (`/map-codebase` for full passes) | until the code moves | open-time staleness look (map date vs `git log -1`); `MAP_DRIFT=` when `MAP_SKELETON=on`; `/map-codebase --refresh` re-verifies drifted areas only | open (header + §3 only); reviewer/builder briefs by PATH |
| Changed-file context (Pip's detection) | dispatch briefs, `Context from review-scorer:` label | `review-scorer` step 1 | one review pass | HEAD/diff moved; post-fix re-review re-runs Pip's context step (audit-review rule) - never re-forwarded stale | code-reviewer + compliance-reviewer step 1/2 |
| Session runtime facts (mode, `<python>`, `$PLUGIN_ROOT`) | `engagement-state.json` via `set-runtime` | orchestrator at workspace creation | engagement lifetime | re-probe only on a fresh session with no state to resume; resume re-reads, never re-asks | resumed sessions; delegation briefs (Track B fix 2026-08-18) |
| Engagement lifecycle state | `engagement-state.json` (+ rendered START-HERE) | `engagement_state` mutators only | engagement lifetime | every mutator re-validates + re-renders; hand-edits flagged mechanically | stop-gates, resume, dashboard, DoD |
| Scan fingerprint (closed packs) | per-pack, written at close | `engagement_state` close path | until pack contents change | content change re-scans; `.archive` marker excludes entirely | DoD/registry scanners |

Rules of the table:
- **A fact is derived once by its owner and travels by reference or forward** - a consumer
  re-deriving it is a defect (Track B audit), except where the row names a deliberate
  fallback.
- **An expired or missing cache falls through to the live derivation, never to a guess** -
  every row's consumer keeps working with an empty cache; caches are accelerators, not
  load-bearing (engage-open's stated rule for the probe cache, generalised).
- New shared facts get a row here before they get a second derivation site.
