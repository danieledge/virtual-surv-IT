# Plan: a first-class workflow view - stages, models, cost, loops

**Status:** SUPERSEDED and REMOVED, 2026-08-25, the same day it was built.

The implementation read Claude Code's internal session transcript. That source has no
recorded cost, no engagement boundary, no visibility into a subagent's turns, and no
stability guarantee - and every one of those limits showed in use. The owner's verdict was
"this feels unreliable", then "no transcript reader for unattended at all - the user can
read the transcript themselves", and both are right.

`workflow_trace`, `render_workflow` and the launcher's workflow screen
are deleted rather than left dormant, because code kept "in case it is useful" rots into
something nobody dares remove. What replaces it is in
`docs/internal/plan-supported-monitoring-2026-08-25.md`: `claude -p --output-format
stream-json`, which publishes cost and the session id outright instead of having them
inferred.

Kept as the design record - the reasoning about scope, loops, cost honesty and export
placement is what carries into the replacement.

---


## 1. The finding that makes this buildable

I checked before designing, because a beautiful view of data we do not have is worse than no
view. **Every input this needs already exists**, in the session transcript
(`~/.claude/projects/<cwd-slug>/<session-id>.jsonl`). Verified against this session's own
transcript, 31MB, 3,546 assistant messages:

| Need | Where it actually is | Verified |
|---|---|---|
| Which stage ran | `toolUseResult.agentType` on each Agent result | 📊 yes |
| **Which model that stage used** | `toolUseResult.resolvedModel` | 📊 yes - read `claude-haiku-4-5-20251001` |
| Tokens per stage | `toolUseResult.usage` (input, output, cache create, cache read) | 📊 yes |
| Duration per stage | `toolUseResult.totalDurationMs` | 📊 yes - 15,268ms |
| Work done in a stage | `toolUseResult.toolStats` (reads, searches, bash, edits, lines +/-) | 📊 yes |
| Stage outcome | `toolUseResult.status` | 📊 yes - `completed` |
| Orchestrator's own model + cost | `message.model` + `message.usage` per assistant message | 📊 yes - opus-5 and fable-5 both present |
| Named phases | `engagement-state.json` `phase` / decisions | 📊 yes |

**One gap, and it matters:** there are **no sidechain messages in any of the 465
transcripts** on this machine. A subagent's internal turns are not in the parent transcript;
only its *totals* come back on the result. So per-stage figures are exact **totals**, and a
drill-down INTO a stage's individual turns is not available from this source. The design
below treats a stage as the atom rather than pretending otherwise.

---

## 2. Shape: three layers, and only the top one is pretty

The mistake to avoid is a renderer that also parses. Three modules, each testable alone:

**(a) `workflow_trace` - pure data, no UI.**
Reads a transcript, returns a `Trace`: ordered stages, each with `agent`, `model`, `tokens`,
`cost`, `duration`, `tool_stats`, `status`, `loop_index`. Also the orchestrator segments
between stages, so the timeline has no unexplained gaps. Pure functions over a file path -
runnable headless, in CI, or from the launcher. **This is the whole feature**; the screens
below are two views onto it.

**(b) `launcher_app.workflow_screen` - the live TUI view.**
Reads (a) on the monitor's existing 2s refresh.

**(c) `render_workflow` - export.**
The same `Trace` to `.md` + `.html` via the existing `render_html`, and `.json` + `.csv` for
anyone who wants their own analysis. Export is not a bolt-on: it is the same object the
screen renders, which is the only way the two cannot disagree.

---

## 3. Cost: measured tokens, inferred money - and the UI must say so

Tokens are **📊 observed**. Money is **🧠 inferred** from a rate table, and the distinction is
not pedantry here: rates change, tiers differ, and a number that looks like a bill invites
being treated as one.

- **One rate table, and it already existed.** The build shipped a second table before this
  was caught: `scripts/dashboard.py` has priced models since the spend work, and the new one
  DISAGREED with it (opus 15/75 against 5/25, fable 3/15 against 10/50). Two tables that
  disagree are worse than one that is stale, because `budget-status` measures an unattended
  run's ceiling against dashboard's - the workflow view and the spend gate would have
  reported different costs for the same run. Pricing now goes through
  `dashboard.price_usage`, and removing the duplicate exposed a live bug in the survivor:
  it matched no model id carrying a context suffix (`claude-opus-5[1m]`) or a release date
  (`claude-haiku-4-5-20251001`), so every message from the models actually in use priced as
  unknown and the ceiling was being compared against an under-counted spend.
- An **unknown model is never guessed** - it shows tokens and `cost: unknown`, because a
  silently wrong figure is worse than a visibly missing one. New model IDs will appear.
- Cache reads are priced separately and shown separately. They dominate long sessions and
  make raw input-token totals meaningless if merged.
- Every rendered total carries the 🧠 mark and a footer naming the rate date.

## 4. Loops: name them, because they are the interesting part

A "loop" is what a delivery team actually does - review, fix, re-review. Detection is
sequence-based and deterministic, no inference:

- **Repeat**: same `agentType` runs again later → `loop_index` 2, 3, … on that stage.
- **Cycle**: an A → B → A sequence (e.g. `code-reviewer` → `rules-developer` →
  `code-reviewer`) is a named fix-cycle, rendered as a bracket spanning its members.
- **Cost of iteration** is the number that earns this feature its place: the view shows what
  the second and third passes cost, which is exactly what nobody can see today.

## 5. What it looks like

Vertical timeline, newest last, one row per stage. Constraints learned the hard way this
week: the left pane is **~47 columns** (two clipping bugs caught under a real pty, invisible
to the headless harness), and **cp1252 consoles cannot render box-drawing or emoji** - so
every glyph goes through `_can_encode` with an ASCII twin.

```
  Workflow                                    $2.41 est · 18m 04s
  ─────────────────────────────────────────────────────────────
  ✓ business-analyst      sonnet   1.2m tok   $0.31   2m 10s
  ✓ rules-developer       sonnet   0.9m tok   $0.24   3m 02s
  ┌ code-reviewer         opus     0.4m tok   $0.52   1m 45s
  │ rules-developer  ↻2   sonnet   0.3m tok   $0.08   1m 12s
  └ code-reviewer    ↻2   opus     0.2m tok   $0.28   0m 58s   fix cycle
  ● qa-engineer           sonnet   0.6m tok   $0.16   running
  ─────────────────────────────────────────────────────────────
  🧠 cost estimated from rates of 2026-08-01 · tokens 📊 measured
```

Colour carries meaning, never decoration: running, done, blocked, and a cost that has passed
the engagement ceiling. `e` exports, `Enter` opens a stage's detail (tool stats, what it
touched), `Esc` stops watching.

## 6. Where it plugs in

The monitor screen built today already watches an unattended run on a 2s refresh. This
becomes its second pane - or `w` toggles between status and workflow. **Attended runs get it
too**: `virt-surv go` → `[v] view artifacts` gains a workflow entry for any engagement whose
transcript can be found. Nothing about this is autonomy-specific; that is just where the
need was loudest.

## 7. Risks, honestly

- **The transcript is an internal file, not a public API.** Its shape can change without
  notice. Mitigation: one parser module, defensive field access, a `trace_unavailable`
  state the UI renders plainly rather than crashing, and a test corpus of real captured
  lines so a format change fails a test rather than a user's screen. This risk cannot be
  removed, only contained - and it should be stated in the feature's own docs.
- **Correlating a session to an engagement.** The launcher spawns the session but does not
  learn its session id. Approach: newest transcript in the project's transcript directory
  whose `cwd` matches and whose first timestamp is after the launch. Fallback: ask, or show
  the newest. Never silently attribute the wrong session's cost.
- **Stage attribution of orchestrator tokens is approximate.** Work Morgan does herself
  between stages is real cost but belongs to no stage; it gets its own "orchestration" rows
  rather than being spread across neighbours.
- **Scale.** 31MB and 3,546 messages in one session here. The parser must stream, cache by
  `(path, size, mtime)`, and never hold the file in memory - the same discipline the
  `repo_skeleton` and `profile_temporal` work needed.
- **Privacy.** The trace holds prompts and file paths. Export is local-only by default, and
  the exporter must never include message CONTENT - stage names, models, counts and
  durations only. That keeps an exported workflow safe to attach to a client report, which
  is the point of exporting it.

## 8. Build order

1. `workflow_trace` + a captured-transcript test corpus. No UI. **This is most of it.**
2. Costing through the EXISTING `dashboard.py` table, with the unknown-model path tested
   first. (No new table - see above.)
3. Loop detection over the ordered stages.
4. `render_workflow` export (`.md`/`.html`/`.json`/`.csv`).
5. `workflow_screen` in the launcher, pty-rendered before it is believed.
6. Wire into the monitor and into `[v] view artifacts`.

Steps 1-4 are useful with no UI at all: a `python -m scripts.workflow_trace --export` that
prints what an engagement cost, per stage, per model, is already a feature people would use.
