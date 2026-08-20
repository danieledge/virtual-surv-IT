# Plan: turn `virt-surv go` into a real TUI app

**Date:** 2026-08-20 · **Status:** plan, not started · Supersedes the TUI item in
`docs/internal/backlog-2026-08-20.md`, which assumed a new dependency was required.

## The finding that changes the recommendation

**`prompt_toolkit` 3.0.53 and `rich` 15.0.0 are already vendored** in `vendor/`, and the
full-screen API (`Application`, `Layout`, `HSplit`/`VSplit`, `Frame`, `Box`, `Window`,
`ScrollablePane`) imports and works from the vendored tree - verified, not assumed.

So the honest comparison is **not** "hand-printed lines vs Textual". It is:

| Option | New dependency | Real layout | Effort | Verdict |
|---|---|---|---|---|
| **Full-screen `prompt_toolkit` app** | **none** (vendored) | Frames, splits, focus, mouse, scrolling | Medium | **Recommended** |
| Textual | Yes - a real tree, into the component that must work FIRST on locked-down Windows | Best-in-class | Medium-high | Rejected for now |
| Stay as-is | none | none | zero | Only if the launcher stays a one-question screen |

Textual is the nicer framework, but it buys a better *widget set* at the cost of a new
dependency in the exact place the project cannot afford one: corporate Windows, where
installs are the constraint and the launcher is what runs before anything else. The
vendored `prompt_toolkit` already delivers the things actually being asked for - borders,
regions, focus, mouse - so the dependency buys polish we do not need yet.

## The problem worth solving (not "it looks plain")

The launcher has **two renderers that must be kept in visual sync by hand**: the numbered
`input()` flow and the `prompt_toolkit` picker. That is not cosmetic - it produced a real
defect on 2026-08-19: a redesign (title-first rows, status marks, relative age,
recommended marker) landed in the numbered tier only, and the picker tier - **the one most
users actually see** - kept the old `resume <slug> <status> opened <date>` rows until a
screenshot exposed it. Any plan that leaves two hand-synced renderers has not fixed the
actual problem.

## Target shape

One full-screen app, three regions, `[Enter]`/hotkeys unchanged:

```
┌ Virtual Surv-IT ─ virt-survtecb · v0.35.0 · dev ─────────────────────┐
│ 🎩 Good morning, I'm Morgan (PM) - an AI agent, Virtual Surv IT      │
├──────────────────────────────┬───────────────────────────────────────┤
│ Resume an engagement         │ Threshold tuning pass                 │
│ > * Threshold tuning pass    │ slug     alert-tuning                 │
│   ! Reconciliation fix       │ opened   yesterday · plan             │
│                              │ open     2 items                      │
│ Start something new          │ next     independent QA - not yet run │
│   [n] a new engagement       │                                       │
│   [j] from a Jira ticket     │ ⚠ 1 engagement blocked                │
├──────────────────────────────┴───────────────────────────────────────┤
│ Project defaults: all at defaults        [c] settings  [Enter] launch│
└──────────────────────────────────────────────────────────────────────┘
```

The right-hand detail pane is the real gain: today's two-line rows cram slug, age, phase,
open count and blocked reason onto one cramped line. A pane shows the selected engagement
properly and scales when there are ten engagements rather than two.

## Constraints that must survive (each has drawn blood already)

1. **stdout is the decision channel.** `virt-surv go` prints ONLY the decision to stdout;
   everything else goes to stderr, because the shell function captures it via `$(...)`.
   A full-screen app must render to **stderr** (`Application(output=...)` bound to
   stderr), and the decision must be the only stdout write, after the app exits. A live
   bug already came from `input()` leaking its prompt onto stdout.
2. **cp1252 consoles.** Box characters and emoji must degrade, exactly as `_can_encode`
   already decides for the wordmark and Morgan's hat. Frame styles chosen accordingly.
3. **The numbered fallback stays.** Non-tty, dumb terminals, a broken vendor tree, tests:
   `_ptk_ui()`'s existing gate already handles this. The fallback is not deleted - but it
   becomes a genuinely *plain* fallback, not a second design to maintain.
4. **Windows rebinding.** The Win32 layer renders via the process stdout handle, which the
   alias captures; the existing rebinding workaround in `_ptk_ui()` must carry over.
5. **Headless testability.** `VIRT_SURV_FORCE_PTK=1` plus pipe-input/dummy-output already
   drives the picker in tests; the app must be drivable the same way or the tier goes
   untested - which is how the drift happened.

## Sequencing

**Phase 1 - one source of row content (do this even if the rest is dropped).** Extract the
row/label building into pure functions returning structured data, consumed by both tiers.
This alone kills the drift class. Small, low-risk, independently valuable.

**Phase 2 - the app shell.** `Application` on stderr, `Frame` + `HSplit`/`VSplit`, the
three regions above, hotkeys and Enter preserved, Esc/Ctrl-C returning the same "decide
in session" result as today. Same return contract as `_pt_menu_round` so the caller is
unchanged.

**Phase 3 - the detail pane**, fed by the Phase-1 structured data.

**Phase 4 - tests.** Headless drive of the app: selection moves, hotkeys fire, the decision
lands on stdout and nothing else does, Esc behaves, cp1252 degradation, and a test that
the two tiers render the same *content* (the drift guard).

**Phase 5 - retire the bespoke picker** (`_pt_pick`) once the app covers its cases, so
there are two renderers total (app + plain), never three.

## What I would NOT do

- **Adopt Textual** while the vendored toolkit does the job - not without a corporate
  Windows install story.
- **Full-screen the settings editor and archive menus in the same change.** Convert the
  main menu first, prove the contract holds, then move the others.
- **Render to stdout** under any circumstance, or write the decision before the app exits.
- **Delete the numbered tier.**
- **Start this before the Control Tower decision.** A live engagement view is the use case
  that would justify going further (and is the one thing that might genuinely warrant
  Textual). Decide them together - the app shell here is a prerequisite either way.
