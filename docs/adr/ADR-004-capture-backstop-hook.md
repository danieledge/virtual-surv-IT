# ADR-004: A session-end capture backstop - proposed, not yet implemented

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-004` · Version `0.1` · Status `Proposed`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-07-23`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-23 | extensibility/memory discussion (user-raised) | Initial proposal: SessionEnd capture backstop; overlap with the codebase-map content fix |

| | |
|---|---|
| **Status** | **Proposed** - design only; NOT wired into `hooks.json` until human sign-off |
| **Date** | 2026-07-23 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | ADR-003 (codebase map); lifecycle discipline (0.16.2); CLAUDE.md §5/§7; `docs/team-operating-guide.md` §Memory scope |

## Context

Two observations converged:

1. **A published pattern.** "Make your setup self-improving: add a stop hook that runs when a
   session ends and prompts the model to propose CLAUDE.md updates while context is fresh."
   (Claude Code guidance for large codebases.)

2. **A residual gap in our own lifecycle work.** The codebase-map update and any recorded
   lesson are **close-time** actions (ADR-003; DoD gate). The 0.16.2 lifecycle release made the
   *engagement state* honest when a close does not run - but if a **session simply ends**
   (terminal closed, context exhausted) mid-engagement, the close never fires, so the map is
   never updated and whatever the team learned evaporates. This is the same "a gate that only
   runs at close is no gate when the close never happens" failure the lifecycle release was
   born from, one level up: at the **session** boundary rather than the engagement boundary.

The published pattern does **not** transfer verbatim here, for reasons that shape the decision:

- **Our `CLAUDE.md` is shipped, versioned and deliberately lean** (dormancy/token cost; 0.8.x
  moved detail to `team-operating-guide.md`). Auto-appending to it fights what it optimises for.
- **It is a plugin across many working projects.** Project learnings belong in the *working*
  project's memory / codebase map, never the plugin's handbook.
- **Changes to the team gate on the eval harness.** Self-improvement that edits shipped prompts
  without evals + a version bump is exactly the drift our rigor exists to prevent.

## Decision

Adopt a **session-end capture backstop**, not a self-editing handbook:

- A **`SessionEnd`/`Stop` hook** that fires when a session ends. It **detects** an engagement
  that did real work but did not cleanly close (START-HERE present and status ⏳/⛔; or artifacts
  written with no ✅) and **prompts to capture before the window closes** - it does not write
  anything itself.
- Capture is routed to the **right target as a proposal, never an auto-apply**:
  - working-project learnings → the **codebase map** (a reviewed git diff; ADR-003 rules);
  - a lesson about the **team itself** → a **lessons-candidate** file a human later triages into
    a house-rule + a golden eval case + a version bump (the recorded-live-lesson pattern).
- **Dormancy-aware:** the hook is a no-op in a session that never engaged the team (no
  START-HERE, no team artifacts) - it must not nag ordinary Claude Code sessions in the many
  projects the plugin is installed across.
- **Never edits `CLAUDE.md` or any shipped prompt.** Those change only through the normal
  eval-gated, version-bumped path.

## Overlap with the codebase-map content fix (0.16.5)

These two are **coupled and must ship in order**:

- The **content fix (0.16.5)** defines *what a good capture is*: the map records **durable
  architecture**, not a findings/activity log (template §2 ✅/❌ contrast; `/engage` 6a;
  operating-guide memory rule; golden case `process-codebase-map-architecture`).
- This **hook (ADR-004)** defines *when capture is guaranteed to happen*: at session end, even
  when a clean close never runs.

The dependency is one-directional and strict: **a hook without the content fix makes things
worse** - it would reliably prompt the capture of *more* activity-summaries, at the exact moment
(session ending, context thinning) when the model is most likely to dump "what I did" rather
than "what the code is". So the content fix lands first (0.16.5, done); the hook follows only
once the map's content discipline is solid and eval-guarded. Together: the fix makes the memory
*correct*, the hook makes it *reliable*.

## Consequences

**Positive:** closes the session-boundary capture gap that complements the engagement-boundary
lifecycle work; reuses existing `hooks.json` infrastructure; keeps self-improvement inside the
team's guardrails (proposals, human triage, eval-gated prompt changes).

**Negative / risks:** a `SessionEnd` hook fires in *every* working project every session - the
dormancy no-op must be exact or it becomes noise; capture prompts add end-of-session tokens
(bounded by firing only on an engaged, unclosed session); a lessons-candidate file needs a human
triage habit or it rots.

**Rejected alternative:** the verbatim published pattern (stop hook auto-proposes/edits
`CLAUDE.md`). Rejected because our handbook is shipped, lean and versioned, and team-prompt
changes must be eval-gated - an auto-editor would bypass the exact rigor that is the project's
value proposition.

## Status / next step

**Proposed.** Not wired into `hooks.json`. Implementation (the hook script, the detect logic,
the lessons-candidate file format, the dormancy guard, tests) awaits human sign-off on this ADR.
