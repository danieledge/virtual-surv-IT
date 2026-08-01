# ADR-006: Machine-readable engagement state - `engagement-state.json` leads, START-HERE renders (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-006` · Version `0.3` · Status `Accepted`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-08-01`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-26 | external-review discussion (user-driven) | Accepted & implemented: `scripts/engagement_state.py` (schema v1, validate/render/mutators), `check_artifacts` STATE-* gates, state-first lifecycle hooks with legacy fallback |
> | 0.2 | 2026-07-26 | live-run artifact review remediation (same day) | Schema v2: `log` split from `outstanding` (+ blocked requires outstanding), structured `ratifications`; close-completeness validation (`set-team`/`finalise-artifacts` before close); gates `RATIFIED-CLAIM-PENDING` + `REVIEW-FINGERPRINT-GAP`; v1 upgrades in place on first mutation |
> | 0.3 | 2026-08-01 | documentation-drift audit | Revision note: the flat paths below (`artifacts/engagement-state.json`, `artifacts/START-HERE.md`) are **superseded by [ADR-008](ADR-008-multi-engagement-workspaces.md)** (0.31): one state file and one rendered index **per engagement workspace**, `artifacts/<slug>/engagement-state.json` + `artifacts/<slug>/START-HERE.md`, with a derived registry (`artifacts/engagements.json` + rendered `ENGAGEMENTS.md`) and the session's ACTIVE slug recorded in `artifacts/.active-engagement.json`. The design in this ADR (state leads, START-HERE renders, mutators re-validate and re-render, the STATE-* gates, the consent exclusion) is unchanged and applies per workspace; a legacy flat pack is still read. Only the location moved. |

| | |
|---|---|
| **Status** | **Accepted / implemented** - `scripts/engagement_state.py`; `check_artifacts` `STATE-MISSING` / `STATE-INVALID` / `STATE-STALE-RENDER`; state-first `persona_anchor.py` + `dod_stop_gate.py` (no wiring change - the hooks were already registered) |
| **Date** | 2026-07-26 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | ADR-002 (consent is a human act - the exclusion below), ADR-003 (engagement memory), ADR-005 (persona anchor trigger); `docs/team-operating-guide.md` §Lifecycle discipline; `docs/templates/start-here.md`; CLAUDE.md §6a |

## Context

The engagement's lifecycle state (⏳ in progress · ⛔ blocked · ✅ closed), outstanding list,
artifact inventory and decisions of record lived only in prose: `artifacts/START-HERE.md`, a
human document. Every machine consumer then had to parse prose:

- `persona_anchor.py` and `dod_stop_gate.py` sniffed the file for status emoji;
- `check_artifacts` reconstructed status with a fail-safe line parser (`_index_status`) and
  cross-checked the folder against the index by filename tokens;
- cold resume asked a fresh session to re-derive state from a rendered document;
- the eval harness scored lifecycle behaviour by keyword matching.

Emoji sniffing is fragile in exactly the situations that matter (a legend line, a stale
banner, a hand-edit mid-crash), and an external design review (2026-07-26) recommended a
structured state file as one of three v0.29 directions. The risk the review missed - and the
constraint this ADR exists to record - is that its sketch put `execution_consent: false` in
the state file. Execution consent already has exactly one authoritative record: the
human-created `.claude/.exec-consent` marker the model is blocked from writing (ADR-002). A
second, model-writable field claiming to describe consent would be a spoofable shadow copy of
the one fact whose provenance the whole threat model protects.

## Decision

1. **One authoritative state file per engagement**: `artifacts/engagement-state.json`
   (schema v1) - status, phase, engagement metadata, team, verdict, footprint, outstanding
   items, artifact inventory, decisions of record. JSON, stdlib-parseable: the hooks and
   checker must work in foreign plugin installs with no pip.
   > **Superseded path (0.3):** since [ADR-008](ADR-008-multi-engagement-workspaces.md) the
   > file lives in the engagement's own workspace, `artifacts/<slug>/engagement-state.json`
   > (a pre-0.31 flat pack is still read). "One per engagement" is unchanged; read every
   > flat `artifacts/...` path in this ADR as `artifacts/<slug>/...`.
2. **START-HERE.md is a rendered view, not a second source.** "The index leads reality"
   becomes "the state leads reality": `scripts/engagement_state.py` renders START-HERE.md
   (and its `.html` sibling) from the state, and every mutator subcommand (`init`,
   `set-status`, `set-phase`, `add-artifact`, `add-outstanding`, `resolve-outstanding`,
   `set-decision`, `set-footprint`) re-validates and re-renders **in the same command** - the
   human view exists from the first moment and can lag the state only inside a crash window.
   The rendered file embeds a `state-hash` so staleness is detectable, and renders the status
   with exactly one state emoji so every legacy emoji consumer still reads it correctly.
3. **The DoD gate closes the crash window.** `check_artifacts` gains `STATE-INVALID`
   (unparseable or schema-invalid state), `STATE-STALE-RENDER` (hash mismatch or missing
   render; auto-fixed by re-render under `--fix`), and `STATE-MISSING` (an index that claims
   state generation whose state file is gone). A legacy engagement with no state file raises
   **no** STATE findings - migration is opt-in per engagement, not a flag day.
4. **Lifecycle hooks read the state first, prose second.** `persona_anchor.py` and
   `dod_stop_gate.py` treat a parseable state file as authoritative (`closed` silences them
   even over a stale ⏳ render; an open status arms them before any render exists) and fall
   back to the legacy emoji sniff otherwise. No hook wiring changed - both were already
   registered - so no human apply step was needed.
5. **The consent exclusion (the one hard rule).** The schema forbids any key containing
   `consent` or `exec`, recursively, at validation - enforced in `validate_state`, surfaced
   as `STATE-INVALID` by the gate, and pinned by tests end-to-end. Execution consent remains
   the marker file and nothing else.

## Consequences

- Cold resume reads structured state instead of parsing prose; the outstanding list and
  decisions of record arrive as data.
- The stop gate can no longer be silenced by a stale ⏳/⛔ render after a real close, and
  conversely arms correctly the instant an engagement opens, even pre-render.
- A hand-edit of the JSON without a re-render is caught at the next turn end
  (`STATE-STALE-RENDER` via the stop gate) and auto-fixed at close (`--fix`).
- Two files now describe one engagement; the pairing is mechanical (every mutator renders,
  the gate checks the hash), so divergence is a detected defect rather than a drift risk.
- Legacy engagements keep working untouched; the eval harness can adopt state-based scoring
  incrementally.

## Alternatives considered

- **YAML sidecar** (as the external review sketched): friendlier to hand-edit, but PyYAML is
  not stdlib and hand-editing is exactly what the design discourages - rejected.
- **Keep START-HERE hand-written and add a parallel state file**: two hand-maintained
  sources that the close must reconcile - the divergence problem this ADR eliminates -
  rejected.
- **A consent field in the state** (the review's sketch): rejected outright; see Context.
- **Front-matter in START-HERE.md** (one file, structured header): keeps a single file but
  makes the human document machine-owned territory and still needs a parser in every
  consumer; the sidecar with an embedded hash is simpler and stdlib-only.
