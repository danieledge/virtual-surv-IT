# Architecture Decision Records - index

One file per significant decision (Nygard format), so the *why* is auditable later. Statuses
below are read from each ADR's own document control; the ADR is the source of truth.

| ADR | Title | Status | One line |
|---|---|---|---|
| [ADR-001](ADR-001-retrieved-citation-grounding.md) | Ground regulatory citations in a retrieved source, not model memory | Accepted / implemented | Pinpoint citations resolve against a version-controlled register or are flagged to-verify; `scripts/check_citations.py` is the mechanical gate. Register grows entry by entry; CI gate deferred. |
| [ADR-002](ADR-002-safety-hook-threat-model.md) | Safety-hook threat model | Accepted / implemented (open backlog) | Bypass analysis for the three guard hooks: file-tool blocks are backed by `permissions.deny` in repo mode, the Bash channel is advisory lexical checking, and the hardening backlog is recorded. |
| [ADR-003](ADR-003-engagement-memory.md) | Engagement memory - a curated codebase map, advisory-only | Accepted / implemented | One per-project codebase map: bounded, PM-curated, SHA-anchored, hygiene-checked by `check_artifacts`, advisory context never enforcement. |
| [ADR-004](ADR-004-capture-backstop-hook.md) | A session-end capture backstop | Proposed | A hook to capture learnings as proposals when a session ends without a clean close; design only, not wired. |
| [ADR-005](ADR-005-persona-reanchoring-hook.md) | Persona re-anchoring - a dormancy-aware per-turn hook | Accepted / implemented | `scripts/persona_anchor.py` re-injects a tiny persona + discipline anchor each turn while an engagement is live, so the soft discipline survives long sessions and compaction. |
| [ADR-006](ADR-006-machine-readable-engagement-state.md) | Machine-readable engagement state | Accepted / implemented | `engagement-state.json` is the authoritative lifecycle record; `START-HERE.md` is a rendered, hash-verified view of it. |
| [ADR-007](ADR-007-codebase-map-evolution.md) | Codebase map evolution - regenerate the mechanical, curate the durable | Re-scoped | Staleness detection shipped in reduced, git-based form (anchors, As-of checks, a staleness budget); the generative layer is parked with the evidence recorded. |
| [ADR-008](ADR-008-multi-engagement-workspaces.md) | Multi-engagement workspaces | Accepted / implemented (0.31) | Several engagements per project at independent states: per-engagement `artifacts/<slug>/` workspaces plus a derived root registry. |
| [ADR-009](ADR-009-company-extensions.md) | Company extensions - additive instructions, tools and steps, never waivers | Accepted / implemented (0.32) | A first-class extensions contract per working project: standing instructions, close actions, an analyser registry and named integrations - additive only, never a safety waiver. |
| [ADR-010](ADR-010-one-placement-rule.md) | One placement rule - the engagement workspace layout | Accepted / implemented | Every artifact has exactly one home in its engagement workspace; one deterministic placement rule instead of per-skill conventions. |
| [ADR-011](ADR-011-session-resume-brief.md) | SessionStart resume brief - re-read the disk after compaction | Accepted / implemented (0.33.1) | A SessionStart hook re-briefs a mid-engagement session from disk after compaction or `--resume`, so state and decisions are recovered instead of re-asked. |
