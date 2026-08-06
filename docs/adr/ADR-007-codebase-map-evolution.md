# ADR-007: Codebase map evolution - regenerate the mechanical, curate the durable (Phase 1+2 implemented)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-007` · Version `0.3` · Status `Phase 1+2 implemented`
> · Classification `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-08-06`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-27 | deep-research synthesis (3 parallel researchers: tooling landscape, agent-memory evidence, internal audit) | Proposed design |
> | 0.2 | 2026-07-29 | workflow-robustness remediation phase 4 (user ruling D3) | Re-scoped: staleness subset implemented in `check_map`; the generative layer (repo_skeleton / map.d / /map-codebase / fingerprint drift stamps) is parked, revisit on demand |
> | 0.3 | 2026-08-06 | user request: "the need has materialised, build it" | The parked generative layer, built: `scripts/repo_skeleton.py` (inventory, tiered symbols, PageRank, Mermaid, churn), drift stamps + `MAP-DRIFT`/`MAP-DEAD-POINTER`, `/map-codebase` skill + `docs/codebase-map.d/` area files + root Index section. Gated behind `map_skeleton` (project/machine preference, off by default) - a project that hasn't opted in sees zero behaviour change. Phase 3 (blast-radius-refresh automation, a rendered map browser) stays deferred, unchanged. |

| | |
|---|---|
| **Status** | **Phase 1+2 implemented** (2026-08-06) - built in full, gated behind the `map_skeleton` toggle (off by default) so it can be tested per-environment without affecting a project that hasn't opted in. Phase 3 (demand-driven blast-radius refresh automation, a human-facing rendered map browser) remains explicitly deferred - revisit if a concrete need materialises, per the same standard this Phase applied. |
| **Date** | 2026-07-27 (proposed) · 2026-07-29 (re-scoped) |
| **Deciders** | Morgan (orchestrator), human approver (remediation plan D3) |
| **Traceability** | ADR-003 (engagement memory - this evolves, does not replace, its §2 discipline); `check_map` in `scripts/check_artifacts.py`; 2026-07-29 robustness register M2/M3/M6/M7 |

## Re-scope (2026-07-29 - what stands, what is parked)

**Implemented** (remediation phase 4, in `check_map` / the template - a reduced, git-based
form of §Decision item 4's drift-stamp goal):

- per-entry **As-of and Anchor validation** (`MAP-ENTRY-NO-ASOF` / `MAP-ENTRY-NO-ANCHOR`)
  and entry-SHA resolution (`MAP-STALE-ENTRY-ANCHOR`) - entry provenance is no longer
  decorative (register M2);
- a **staleness bound**: the header anchor is compared against HEAD and `MAP-STALE` fires
  past the map's `Staleness-budget` (default 50 commits, override with rationale) -
  register M3;
- the **strict no-vcs anchor value** (the template placeholder can no longer pass - M1),
  column-driven entry detection (section renames no longer disable the scan - M7) and a
  line cap that excludes the Deprecated section ADR-003 mandates keeping (M7).

**Parked** (revisit when a first-contact-on-large-codebase need actually materialises;
nothing else in the product depends on them): `scripts.repo_skeleton`, the `map.d/` area
files, `/map-codebase`, and content-fingerprint drift stamps (`MAP-DRIFT` /
`MAP-DEAD-POINTER`). The git-based bound implemented above covers the silent-rot gap for
anchored repos; no-vcs projects remain human-judged - an accepted residual.

## Context

Today's map (ADR-003) is a single ≤250-line PM-curated file, created only as an engagement
close side-effect. The internal audit confirmed four gaps: no first-contact survey (coverage
is accidental), a flat file that cannot index a large codebase, staleness detection that
verifies only the header SHA resolves (per-entry anchors are decorative; ADR-003 itself
concedes rot is caught only by humans), and no mechanical referenceability (no entry IDs, no
routing, JIT reading of §2 means re-reading the whole file).

External research (2026) splits the problem in a way the original design did not:

1. **The comprehensive-wiki approach exists and works for HUMANS** (Google Code Wiki,
   DeepWiki): hierarchical wiki, regenerated on change, every claim linked to source. All
   are hosted services - unusable for client code that cannot leave the machine - but the
   architecture (routing root, per-area pages, change-triggered refresh, source-linked
   claims) is reimplementable locally.
2. **The evidence says comprehensive maps barely help AGENTS.** The strongest published
   eval (AGENTbench, arXiv 2602.11988) found human-written repo context files gave ~+4%
   agent success at +19% inference cost; LLM-generated ones HURT (~-3%); repository
   overviews and directory enumerations did not reduce steps-to-relevant-file. What
   measurably helped: exact commands, tooling directives, invariants, gotchas. Generated
   overviews became net-positive only when the repo had no other documentation. Anthropic's
   own guidance concurs: thin pointer-style roots, just-in-time agentic search (no stale
   index), durable memory only for what "continues to constrain future reasoning".
3. **The mechanical layer is cheap and solved.** aider's repo map (tree-sitter def/ref
   tags, personalization-weighted PageRank, binary-search to a token budget, mtime-cached)
   is ~500 lines of pure pip-installable Python, zero LLM. universal-ctags (single binary,
   JSON) is the low-footprint fallback; stdlib `ast` covers Python with zero installs.
4. **Staleness detection needs no LLM.** The drift-linter pattern (Fiberplane): stamp
   generated/curated content with per-source content hashes + provenance commit; a checker
   re-hashes and fails CI on mismatch; AST-normalised hashing avoids reformatting false
   positives. Incremental repair follows the blast-radius pattern (RepoAgent/RepoDoc):
   diff → affected symbols → one hop along reference edges → refresh only that scope
   (80-90% reported reduction in LLM calls).
5. **The dominant memory failure is confidently remembering wrong**: stale notes are
   treated as ground truth; "add-all" memory measurably degrades task success. Mitigations
   with a track record: provenance + date on every note (our 📊/🧠 tags are exactly this),
   regenerate rather than store anything derivable from code, evict/revalidate rather than
   accumulate, ship memory changes in reviewed commits.

## Decision (proposed)

Split the capability into a REGENERABLE mechanical layer and a small CURATED durable layer,
and never confuse the two.

1. **`scripts.repo_skeleton` - the mechanical map, generated on demand, never stored as
   truth.** Deterministic pipeline: inventory (git ls-files, else os.walk with vendor/data
   exclusions), symbols (tiered: tree-sitter wheels if available → universal-ctags if on
   PATH → stdlib `ast` for Python → filename/heading scan floor), def/ref graph with
   PageRank ranking, dependency edges rendered to Mermaid deterministically, churn from git
   log (else mtime, tagged 🧠, else omitted). Output: a ranked, token-budgeted skeleton
   (aider-style) written to `artifacts/` per engagement or streamed to the console. Zero
   LLM. Because it is regenerated, it is never stale - the "no stale index" property of
   agentic search, at a fraction of the read cost on first contact.
2. **The curated map stays small and follows the evidence.** `docs/codebase-map.md` keeps
   its exact current contract (probe head-20 + §3 slice, Team-ver column, check_map rules,
   ≤250 lines) and §2 entries are re-scoped to what the eval evidence says earns tokens:
   invariants, gotchas, risk areas, commands, decisions, corrections - explicitly NOT
   architecture prose or symbol inventories (those are the skeleton's job, regenerated).
   PM-only writes, deprecate-don't-delete, 📊/🧠 + anchors: unchanged (they are precisely
   the published mitigation for confident-wrong memory).
3. **Area detail files only where the code lacks its own docs.** `docs/codebase-map.d/
   <area>.md`, each with an explicit load-trigger line in the root's new index section
   ("read this when: ..."), entry IDs for citation, same hygiene rules per file. The root
   file's index section lists them within the existing line budget. For well-documented
   repos this directory may legitimately stay empty - the research is unambiguous that
   duplicating existing docs is negative-value.
4. **Drift stamps close the staleness hole.** Every §2 entry and every area file gains a
   `paths:` glob + content fingerprint (sha256 over the covered files, computed by
   `repo_skeleton`; git-independent by design, `git ls-tree` as the fast path). New checks:
   `MAP-DRIFT` (fingerprint mismatch: "area X changed since mapped - re-verify"), and
   `MAP-DEAD-POINTER` (a file:line an entry cites no longer exists). Both surfaced at open
   (one line: "3 of 14 areas drifted") and in the close fix-list. Detection is stdlib-only;
   the LLM is used only to re-verify flagged entries, blast-radius scoped.
5. **First contact becomes `/map-codebase`** - an explicit (light-profile) engagement:
   mechanical skeleton first, then 1-3 synthesis agents reading only top-ranked files per
   area to produce the CURATED layer (gotchas, invariants, risks - not prose summaries),
   sized and priced out loud at the gate. `--refresh` mode re-verifies only drifted areas.
   Offer (never assume) `git init` on non-VCS dumps for forward history.

## What we deliberately do NOT build

A comprehensive generated wiki (evidence: negative value for agents; a hosted-service-shaped
cost for humans we can revisit if a human-documentation need emerges); embedding/vector
indexes (stale-index problem, ADR-003 already rejected); graph databases or per-language
SCIP toolchains (service/install sprawl); any always-loaded context (dormancy invariant).

## Consequences

- First contact on a large repo: one cheap deterministic pass orients the team in minutes;
  LLM spend goes only to judgement on ranked hotspots. No-git dumps degrade gracefully.
- Staleness becomes a detected, targeted, cheap-to-repair defect. The audit's "silent rot"
  gap closes with ~zero ongoing LLM cost.
- The curated map gets SMALLER and more valuable per line, aligned with what the evidence
  says agents actually use. Humans reading the map get pointers into live code, not prose
  that drifts.
- New moving parts: repo_skeleton (needs a `_TEAM_SCRIPT_NAMES` entry via the staged-guard
  flow), two new MAP-* checks, the map.d/ discovery path added to check_map/dashboard/probe
  consumers, one new skill. All additive against the pinned contracts.
- Risks: fingerprint glob scoping needs care (over-broad globs = permanent drift noise;
  start per-directory); tree-sitter wheels are a new optional dependency (tiered fallbacks
  keep the floor at stdlib); the light-profile survey must respect the ~15x fan-out rule.

## Build plan

**Phase 1 - done (0.33.x, 2026-08-06):** `repo_skeleton.py` with tiered extractors + tests;
drift stamps + `MAP-DRIFT`/`MAP-DEAD-POINTER` in `check_map`; guard allow-list staging.
**Phase 2 - done (0.33.x, 2026-08-06):** `/map-codebase` skill + root Index section +
`docs/codebase-map.d/` discovery; `docs/templates/codebase-map-area.md`. Golden eval case
(`process-first-contact-map`) not yet written - tracked separately, not blocking the toggle
staying off by default in the meantime. **Phase 3 (optional, demand-driven, still parked):**
blast-radius refresh automation; a human-facing rendered map browser via the existing
dashboard.
