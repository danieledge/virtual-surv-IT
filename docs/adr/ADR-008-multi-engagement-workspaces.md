# ADR-008: Multi-engagement workspaces - several engagements, one project, independent states (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-008` · Version `0.1` · Status `Accepted`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-07-27`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-27 | user-driven design (audit-then-scope scenario) | Accepted & implemented: workspaces, derived registry, resolution rules, hook scans, checker iteration |

| | |
|---|---|
| **Status** | **Accepted / implemented** (0.31) |
| **Date** | 2026-07-27 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | ADR-006 (state file - per-workspace unchanged), user requirement: "two engagements in the same project might be at separate states"; live scenario: a full codebase audit parked ⛔ awaiting sign-off while a requirements-scoping engagement runs beside it |

## Context

Pre-0.31 the project had one implicit engagement: state, index and artifacts sat flat in
`artifacts/`, with fixed filenames. A second engagement would collide with the first, and
the hooks/checker knew only the one flat pack. Real usage needs several engagements per
project at INDEPENDENT lifecycle states.

## Decision

1. **One workspace per engagement**: `artifacts/<slug>/` holds that engagement's
   `engagement-state.json`, rendered START-HERE and every artifact. `init` creates the
   workspace by default (an explicit `--dir` keeps flat semantics for tests/custom layouts).
2. **A DERIVED root registry**: `artifacts/engagements.json` + rendered `ENGAGEMENTS.md`,
   regenerated from a scan of the packs on every state mutation - it can never become a
   second source of truth. `REGISTRY-STALE` (mechanical, auto-fixed by regeneration) covers
   the crash window.
3. **Resolution rules** for every state command: `--dir` wins; else `--slug` under the
   root; else the project's only pack (flat or single workspace) auto-resolves so the solo
   UX is unchanged; ambiguity is an explicit error listing the options. `list` prints the
   registry; `migrate` moves a legacy flat pack into its own workspace.
4. **Hooks scan all packs.** The persona anchor arms when ANY pack is open (⏳ or ⛔) and
   appends an open-engagements line so a session always knows the landscape and states its
   ACTIVE slug. The stop gate gates ONLY ⏳ in-progress workspaces - a ⛔ workspace is
   already truthfully parked and must not nag a session working a sibling engagement. The
   legacy flat pack keeps its pre-0.31 gate semantics (⏳ or ⛔) so solo engagements behave
   exactly as before.
5. **The checker iterates workspaces** with slug-prefixed findings, each pack checked in
   its own scope (close-only rules, interim naming and email requirements per engagement -
   one engagement's interim state can never block a sibling's close), plus the registry
   check. A flat pack coexisting with workspaces gets one finding - `FLAT-PACK-UNMIGRATED` -
   instead of deep checks whose rglob would cross workspace boundaries.
6. **Front door selection**: when workspaces exist, `/engage` (and `/engage-light`) ask
   resume-or-new via the question tool; one engagement ACTIVE per session, named in the
   banner. Cross-engagement reads are allowed read-only and recorded as brief inputs; the
   codebase map remains the one shared cross-engagement memory (ADR-003).

## Consequences

- The audit-then-scope scenario works: the audit parks ⛔ with its outstanding list intact
  and silent, scoping opens, runs and closes beside it, either resumable any time.
- Registry, being derived, is rebuildable at will; deleting it costs nothing but a
  regeneration.
- Consumers updated: dashboard aggregates per-workspace gate findings; the eval driver's
  artifact probe finds packs in either layout. Legacy flat packs work unchanged everywhere.
- Residual: two sessions concurrently mutating the SAME workspace remains out of scope
  (unchanged from pre-0.31: one active session per engagement is the working assumption).
