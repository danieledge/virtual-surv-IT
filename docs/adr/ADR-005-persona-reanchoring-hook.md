# ADR-005: Persona re-anchoring - a dormancy-aware per-turn hook (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-005` · Version `0.3` · Status `Accepted`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-08-01`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-23 | persona-decay discussion (user-reported) | Initial proposal: dormancy-aware UserPromptSubmit re-anchor hook |
> | 0.2 | 2026-07-24 | best-practice review remediation | Accepted & implemented: `scripts/persona_anchor.py` (tested, ≤8-line anchor, live-engagement trigger); wiring by a one-shot human-run script, retired 2026-07-30 after its wiring was committed (re-wiring today: `bash scripts/apply-project-anchor.sh`) |
> | 0.3 | 2026-08-01 | documentation-drift audit | Revision note: the flat `artifacts/START-HERE.md` path the engaged signal was written against is **superseded by [ADR-008](ADR-008-multi-engagement-workspaces.md)** (0.31, per-engagement workspaces `artifacts/<slug>/`) and by [ADR-006](ADR-006-machine-readable-engagement-state.md) (state leads, START-HERE renders). The decision itself (a dormancy-gated per-turn re-anchor) is unchanged; only the signal's location and shape moved. `scripts/persona_anchor.py` now scans every workspace pack under `artifacts/` plus the legacy flat pack, reading each pack's `engagement-state.json` first and falling back to that pack's `START-HERE.md` emoji. |

| | |
|---|---|
| **Status** | **Accepted / implemented** - `scripts/persona_anchor.py`; wiring into the two hook files was human-run (ADR-002 rec 5; applied 2026-07-24 - the hook ships wired). The original one-shot wiring script was retired 2026-07-30 once its wiring was committed; the live re-wiring path today is `bash scripts/apply-project-anchor.sh` (syncs the staged copies to the live hooks) |
| **Date** | 2026-07-23 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | ADR-004 (session-end capture hook); README "Known issues" (persona decay + name drift); `docs/team-operating-guide.md` §Voice/Roster; CLAUDE.md §6 (persona), §5/§7 (hook-enforced guards) |

## Context

A user reported (2026-07-23, live) that on a long engagement the `/engage` persona faded:
Morgan's voice dropped, responses reverted toward default Claude Code, and concurrent subagents
showed generic "Agent A/B/C" labels. This is the general form of the existing **name-drift**
known issue (the PM narrating "Isla"/"Jordan" for a real specialist).

**Root cause.** The persona and soft discipline - the 🎩 voice, the named specialists, the
question-tool rule, the fix-list gate, the lifecycle discipline - are defined in the `/engage`
SKILL.md and the operating guide, which load **once** when the user types `/engage`. They are
**never re-asserted**: the plugin is dormant-by-default (`disable-model-invocation: true`), so
those instructions live only in the **conversation history**. Distance in a long session, and
especially Claude Code **context compaction/summarisation**, erode that history, and the model
drifts back to its default behaviour. A prompt instruction to "stay in persona" cannot fix this -
it decays for the very same reason.

**What is NOT affected (important).** The hard controls - the raw-data read block, the
execution-consent gate, the consent-write gate - are enforced by **hooks** (`hooks.json`),
independent of the model's persona, so they hold regardless of how faded Morgan is. Only
*presentation* and *soft, prompt-enforced* discipline decay. The critical rails were deliberately
put in hooks precisely so they survive this.

## Decision

Re-assert the persona from **outside** the conversation, every turn, but **only while the team is
engaged** - via a **`UserPromptSubmit` hook** (`reanchor-persona.py`):

- **Engaged signal (dormancy gate):** reuse existing state - an open engagement is
  `artifacts/START-HERE.md` present with status ⏳/⛔ (not ✅ closed). No new marker needed.
  When there is no open engagement, the hook is a **zero-token no-op**.
  > **Superseded path (0.3):** as shipped, the signal is per engagement, not flat. ADR-006 made
  > `engagement-state.json` authoritative with START-HERE as its render, and ADR-008 moved both
  > into `artifacts/<slug>/`, so the hook scans every workspace pack (plus a legacy flat pack)
  > and reads `<pack>/engagement-state.json` first, `<pack>/START-HERE.md` second. The
  > zero-token no-op property is unchanged: no open pack, no output.
- **The anchor (tiny):** when engaged, inject ~10-15 lines - "🎩 You are Morgan; mark every turn
  🎩; roster: Amara=`business-analyst`, Ravi=`code-reviewer`, Hassan=`tm-sme`, … (all 16 +
  Morgan); standing rules: question-tool, the fix-list gate, lifecycle discipline, data-safety
  §5; detail in `docs/team-operating-guide.md`." Re-injected each turn, so it **survives
  compaction**.
- **Source of truth:** the anchor derives from `docs/team-operating-guide.md` (the roster line +
  standing rules), or a small dedicated `docs/persona-anchor.md`, pinned by a docs-consistency
  test - so it can't drift like every other duplicated fact eventually has.

**Two-for-one:** injecting the full **name↔role roster** each turn also fixes the existing
name-drift known issue - that low-salience name↔role lookup is exactly what fades today.

## Consequences

**Positive:** the persona and soft discipline survive long sessions and compaction; the name-drift
quirk is fixed as a side effect; the mechanism is invisible (free) in ordinary non-team sessions;
it reuses the existing hooks infrastructure and the same "hooks re-assert what prompts forget"
philosophy as ADR-004.

**Negative / risks:**
- **Per-turn token cost while engaged** (a few hundred tokens/turn). Cheap versus losing the
  persona, but real - it slightly dents the dormancy-lean posture *during* an engagement (never
  when idle). The anchor must stay minimal.
- **Cross-project blast radius:** a `UserPromptSubmit` hook fires in *every* session in *every*
  working project the plugin is installed in - the engaged-check must be fast and bulletproof, or
  it becomes latency/noise everywhere.
- **Sync risk:** the anchor duplicates roster/rules; without a docs-consistency test binding it to
  the source, it will drift.

**Rejected alternatives:**
- **A minimal always-on line in `CLAUDE.md`.** Cheaper (no hook), but `CLAUDE.md` is loaded in
  *every* session including non-team ones, and is deliberately kept lean (0.8.x); an always-on
  persona line pollutes ordinary sessions and fights the token budget. It also still rides the
  conversation/compaction path, so it is less robust than a per-turn re-inject.
- **Periodic self-re-read** (the model re-reads the operating guide every N turns). Won't fire
  reliably - the instruction to re-read decays with everything else.

## Verification (before it lands)

- **Dormancy test:** the hook is a strict no-op with no open engagement pack (or a ✅-closed
  one) - zero output, negligible latency. (Written against the flat `artifacts/START-HERE.md`;
  per ADR-006/ADR-008 the test now covers per-engagement packs, see the 0.3 revision note.)
- **Compaction-survival check:** a behavioural eval that simulates a long/compacted context and
  asserts the persona markers and correct specialist names are still present after the re-anchor.
- **Sync test:** a docs-consistency test that the anchor's roster/rules match the operating guide.
- Standard rigor for a team-behaviour change: full pytest + a live golden-slice spot check.

## Status / next step

**Accepted and implemented** (0.27.0; wiring human-applied 2026-07-24 - the hook ships wired in
both hook files). The hook script (`scripts/persona_anchor.py`), the engaged-signal check, the
anchor content, the dormancy guard and the tests above all landed; re-wiring today is
`bash scripts/apply-project-anchor.sh`.
