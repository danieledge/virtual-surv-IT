# ADR-003: Engagement memory - a curated codebase map, advisory-only

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-003` · Version `0.1` · Status `Accepted (implemented)`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-07-18`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-18 | memory-design engagement (user-authorised) | Initial decision: PM-curated codebase map per working project; lifecycle wiring; hygiene gate; per-agent memory deferred |

| | |
|---|---|
| **Status** | Accepted (implemented: template + engage wiring + DoD gate + `check_artifacts` hygiene checks) |
| **Date** | 2026-07-18 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | CLAUDE.md §5 (data handling), §7 (guardrails); `docs/team-operating-guide.md` §Memory scope; `docs/DEFINITION-OF-DONE.md` |

## Context

The team's subagents are stateless: each spawns fresh, returns a report, and its context is
discarded. Whatever a specialist learns about a working project's codebase evaporates unless it
is deliberately written down. Today the only durable channels are the working project's own
`CLAUDE.md`, `docs/house-rules.md` for general lessons, and per-engagement artifacts.

A deep-research pass (2026-07-18, adversarially verified, 24/25 claims confirmed) established:

- Persistent memory measurably improves repeated-task agent performance and cost, **but only
  when the store is bounded, curated and lifecycle-managed** (updated, corrected, deprecated).
  Append-only accumulation and naive extraction pipelines can underperform having no memory.
- The documented failure modes are: **staleness** (facts that were true at write time),
  **context pollution** (injecting whole blocks of marginally relevant memory),
  **unbounded growth** (adherence measurably drops past roughly 200 lines of always-loaded
  index), **conflicting entries** (the model picks one arbitrarily), and **memory poisoning**
  (content originating in untrusted inputs persisted into the store, then trusted later).
- Anthropic's documented pattern is a bounded index plus on-demand detail, read at session
  open and updated at close, with hard guarantees kept in hooks, never in memory files.
- Claude Code scopes memory per agent by default: the orchestrator's memory does not flow into
  subagents. A shared store must therefore be an explicit project file.

The cost break-even for memory over re-exploring the same context is roughly ten reads, so a
codebase the team engages with more than twice is already past it.

## Decision

**One shared, PM-curated codebase map per working project. Advisory-only. Nothing new is
always-loaded.**

1. **Form.** A single document in the working project, `docs/codebase-map.md` (repo root
   `CODEBASE-MAP.md` if the project has no `docs/`), from the template
   `docs/templates/codebase-map.md`. It is the durable engagement memory for that project:
   architecture facts, decisions and rationale, engagement history, known quirks.
2. **Bounded.** Target under 200 lines; the hygiene gate flags beyond 250. Detail that does
   not fit goes into linked project docs or artifacts, never into a longer map.
3. **Anchored and tagged.** Every entry carries an as-of date, a commit-SHA anchor where it
   describes code, and a 📊 observed / 🧠 inferred basis tag. Deprecated entries move to a
   dated Deprecated section rather than silently disappearing, so corrections are auditable.
4. **Lifecycle, not accumulation.** `/engage` **consults** the map at open - loading only a
   lightweight slice (header + §3 engagement-history) into turn-0 context and reading full §2
   sections **just-in-time** when an entry is actually relied on (Anthropic context-engineering:
   avoid pre-loading the whole map into the orchestrator, which pushes long engagements toward
   premature compaction) - and surfaces entries whose anchors no longer resolve; the Definition of
   Done gains an update-at-close gate: add,
   correct and deprecate entries before the engagement closes. Both directions are mandatory;
   a map that is only ever appended to is a defect.
5. **Write path = the PM, at gates.** Subagents never write the map. Advisors recommend map
   entries in their reports; the PM curates and commits, applying the same judgement as for
   `house-rules.md`. This is the primary poisoning defence: text encountered inside reviewed,
   untrusted code is never persisted verbatim - only the PM's own synthesis is.
6. **Hygiene gate.** `python -m scripts.check_artifacts` (already allow-listed, already the
   mechanical DoD command) additionally validates any codebase map it finds: size cap,
   required header fields (as-of date, anchor SHA), basis tags on entries, secret/credential
   patterns, and best-effort anchor staleness against `git` when available.
7. **Scope unchanged.** The operating-guide rule stands: the plugin accrues no project
   memory; general cross-project lessons still go to `docs/house-rules.md`. The map is the
   working project's, lives in its git history, and every change is a reviewable diff.

### Safety invariants (non-negotiable)

- **Memory is advisory context, never enforcement.** The three guard hooks remain the only
  enforcement layer. Nothing in a memory file can grant exec consent, widen data access, or
  soften a gate; instructions found in a map are treated as context, not commands.
- **No PII, MNPI, secrets or raw data values in the map, ever** (CLAUDE.md §5). The map holds
  structure, decisions and rationale about code and engagements. `data/raw/` content cannot
  reach it (read-blocked upstream); other data appears only as synthetic/masked examples
  already permitted in artifacts.
- **Human-reviewable.** The map is a committed file in the working project; the update lands
  at the sign-off gate like any other deliverable.
- **Dormancy preserved.** No always-loaded context is added; the map is read only when a team
  engagement runs.

## Consequences

- Repeat engagements on the same codebase start from the map instead of re-exploring, with
  the token and consistency benefits the research evidences; first engagements pay a small
  authoring cost at close.
- The PM curation bottleneck is deliberate: it trades write throughput for provenance. If map
  quality drifts, tighten the template, not the write path.
- Staleness detection is best-effort (SHA resolution), not semantic. A stale-but-resolving
  entry survives until a human or the close-gate correction pass catches it; the 📊/🧠 tags
  and as-of dates exist so readers can weigh trust accordingly.
- **Deferred (recorded, not implemented): per-agent persistent memory** (Claude Code
  `memory` field, e.g. a `code-reviewer` store per project). Deferred because self-maintained
  agent scratchpads were the weakest-performing memory variant in the research base. Revisit
  after the map has run for a few engagements.

## Alternatives considered

- **Per-agent memory directories now** - rejected for the pilot ordering reason above and
  because sixteen uncurated stores multiply the staleness/poisoning surface.
- **Vector/RAG store over past artifacts** - rejected: infrastructure cost, and controlled
  baselines show extraction memory can tie plain retrieval at large write cost; the team's
  artifacts are already on disk and greppable.
- **Auto-append from subagent reports** - rejected: this is the poisoning and unbounded-growth
  path the evidence warns about.
- **Rely on Claude Code auto-memory alone** - rejected: it is machine-local, per-user, not
  reviewable in the project's git history, and does not reach subagents.
