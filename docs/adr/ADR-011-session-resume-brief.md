# ADR-011: SessionStart resume brief - re-read the disk after compaction (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-011` · Version `0.1` · Status `Accepted`
> · Classification `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-07-29`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-29 | 0.33.1 capability adoption (user-approved batch) | Accepted, staged and human-applied same day: SessionStart(compact,resume) brief, dormancy-exact |

| | |
|---|---|
| **Status** | **Accepted / implemented** (0.33.1; human-applied 2026-07-29 via `scripts/apply-session-brief.sh` - wired in both hook files) |
| **Date** | 2026-07-29 |
| **Deciders** | Human approver (the 0.33.1 batch), Morgan (design) |
| **Traceability** | 0.33.0 register R1-R7 (disk-first resume), ADR-004 (capture at session end - this is the reload mirror), ADR-005 (persona anchor), the 2026-07-29 Claude Code capability audit |

## Context

0.33.0 made every session decision recoverable from disk (ACTIVE marker, gate answers,
consent outcome, runtime, phase) and the engage skill's resume path re-reads them. But the
moment right after an automatic compaction or a `--resume` is not an engage invocation: the
model simply continues on a summarised transcript, and nothing tells it that authoritative
state now exists on disk. Claude Code's `SessionStart` hook fires with `source: "compact"`
or `"resume"` at exactly that seam and may inject context.

## Decision

A `SessionStart` hook (matcher `compact|resume`) that prints a short brief - the ACTIVE
pack, its status and phase, the instruction to re-read `engagement-state.json` FIRST, that
recorded answers are never re-asked, and that a recorded consent `declined` stands until
the human says otherwise - **only when a pack under the project's `artifacts/` is live**
(state `in_progress`/`blocked`/`closing`; legacy index sniff as fallback).

Dormancy-exactness is the acceptance bar (the ADR-004 lesson): in any session where no
engagement is live - including every other project the plugin is installed into - the hook
emits nothing, adding zero context. It fails open on every error path, and startup/clear
sources are excluded twice (the matcher AND an in-hook check).

## Consequences

- The compaction hole in the resume story closes: the disk-first re-read no longer depends
  on the user happening to type `/engage` after a compaction.
- One more staged hook surface: ships via `scripts/staged_hooks/` + a human-run apply
  script (ADR-002 rec 5 unchanged); tests pin dormancy, source filtering, ACTIVE-marker
  selection and fail-open (`tests/test_session_brief.py`).
- No new authority: the brief is pointer text, grants nothing, and cannot re-open the
  consent gate (it says the opposite).
- Residual: a compaction that loses the transcript AND has an unreadable state file gets no
  brief - the stop-gate and persona-anchor layers remain the backstop there.
