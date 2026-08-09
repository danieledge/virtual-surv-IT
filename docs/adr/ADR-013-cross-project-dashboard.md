# ADR-013: Cross-project dashboard - settings snapshot, run time, timeline, React frontend (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-013` · Version `0.3` · Status `Accepted`
> · Classification `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-08-08`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-08-08 | 0.33.54 feature (user-requested, straight-to-implementation) | Accepted, implemented same day |
> | 0.2 | 2026-08-08 | 0.33.55 feature (live UX feedback, user approved a JS framework) | Rendering ownership split: Python stays the data layer (`emit_json()`), a new `dashboard-ui/` Vite/React app owns ALL presentation, including a swimlane/loop-arc engagement timeline and a 3-tab page split. See §6 below. |
> | 0.3 | 2026-08-08 | 0.33.57 feature (live feedback: "portfolio feels disjointed", "cost table should be scoped... and have an actual cost") | Portfolio&rarr;Engagements cross-linking; sessions priced in real dollars per-model and date-matched to engagements (🧠 inferred); per-model cost breakdown; cache hit-rate KPI. See §7 below. |

| | |
|---|---|
| **Status** | **Accepted / implemented** (0.33.54 + 0.33.55; `scripts/dashboard.py`, `scripts/engagement_state.py`, `scripts/engage_probe.py`, `.claude/skills/dashboard/`, `dashboard-ui/`) |
| **Date** | 2026-08-08 |
| **Deciders** | Human requester (brainstorm → "both!" → straight to implementation → two rounds of live UX feedback → "happy to use a JS framework"), Morgan (design) |
| **Traceability** | ADR-006 (machine-readable engagement state - `settings_snapshot`/`log` extend it additively), ADR-008 (workspaces - `scan_engagements()` is the per-project source this reads), `docs/team-operating-guide.md` (`log-note --tag review-loop` convention) |

## Context

The team already wrote a rich local dashboard (`scripts/dashboard.py`, 2026-07-31) but it
was effectively invisible - no `/dashboard` skill, no mention in the operating guide - and
the user's complaint ("hard to find engagements across multiple folders, no top-down view
of what's been delivered") plus three follow-on asks (settings captured per engagement,
total run time, a visual timeline of artifacts and agent review loops) needed a decision on
scope before implementation, specifically: whether to build a new cross-project registry
file, and how to represent "run time" and "review loops" without a schema rewrite.

## Decision

**No new registry file.** `discover_projects()` already unions evidence from Claude Code's
own project config and transcript fingerprinting, and `dashboard.py`'s `main()` already
defaults to it with no project args. Building a second, hand-maintained registry would
duplicate working, dependency-free logic for no gain - the actual gap was that nothing
pointed at the existing mechanism. Fixed with a `/dashboard` skill instead.

**Settings are snapshotted at open, not live-resolved.** `engagement_state._cmd_init` now
calls `engage_probe.resolve_preferences()` (extracted from `build_report()`, same
precedence chain: project → machine-default → built-in) and stores the result as
`state["settings_snapshot"]` - a point-in-time record. Re-resolving live at dashboard-render
time was rejected: an engagement's settings should read as "what was true when this ran",
not silently drift to match the project's *current* preferences.

**Run time is two separate, honestly-scoped numbers, never blended into one.** Mirrors the
page's own existing token-cost separation (measured vs inferred):
- 🧠 inferred, per engagement: `closed - opened`, date-granularity only (`_day_span`).
- 📊 measured, portfolio-wide: sum of consecutive-message transcript-timestamp gaps under a
  15-minute idle cap (`_active_seconds`). A first-to-last span was tried first and rejected
  - a live check against this repo's own transcripts produced "171h 55m" for one session,
  because Claude Code sessions routinely sit open for hours or days between messages
  (resume-later is normal), and a raw span counts that idle time as active work.

**The engagement timeline reuses `log` as a plain `list[str]` - no schema change.**
`log-note` gained an optional `--tag NAME` flag that stores a bracket-prefixed string
(`"2026-08-08 [review-loop]: X -> Y: reason"`) instead of a new structured field. This keeps
`validate_state()` untouched (a genuine schema addition for "events" was considered and
rejected as disproportionate to the ask) while giving the dashboard enough signal to render
a distinct icon for a review handback. The timeline itself is built from data three mutators
already write (`init`'s `opened`, `add-artifact`'s `added` date, `log-note`'s entries,
`set-status closed`'s `closed`) - nothing new to track, nothing inferred.

**The obligation-coverage map reuses `check_citations`'s own matcher verbatim** (`_load_register`,
`check_text`) rather than writing a second citation parser - scanned across every known
engagement's artifacts, portfolio-wide, tallied by register id.

## Consequences

- Zero new dependencies, zero new persistent files beyond the additive
  `settings_snapshot` state field and the (unchanged-shape) `log` string convention.
- `settings_snapshot` and the `--tag` convention are best-effort: a foreign install that
  can't load `engage_probe` gets `settings_snapshot: null`; an engagement that never used
  `--tag` still gets a real timeline, just without loop-specific icons. Neither degrades to
  a broken page - both are stated on the page (`_settings_chips`'s "not captured" text).
- The `log-note --tag review-loop` convention only populates itself if specialists actually
  use it - `docs/team-operating-guide.md` now names the convention at the point handoffs
  happen, but nothing enforces it mechanically (a deliberate choice: forcing every log-note
  through a tag taxonomy was rejected as more ceremony than the ask warranted).
- Residual: the activity heatmap caps at the most recent 120 days (stated on the page, not
  silent); a portfolio with genuinely ancient history would need that raised.

## §6 - v0.2: React frontend, swimlane timeline, page split (2026-08-08, same day)

Two rounds of live feedback on the v0.1 result: a general "materially enhance the UX/UI" ask
(answered in-place with a KPI strip, card accents, agent-name humanization), then a specific
one - *"i want the timeline to be more graphically nice - visually showing the loops - so it
has the real feel of a team and its interactions. the long list of sessions and then only one
engagement is confusing"*. A flat bulleted list with one amber-tinted row was never going to
satisfy "visually showing the loops" - that needs a real layout engine, not more CSS on a
Python-templated string. The user explicitly approved pulling in a JS framework for this.

**Decision: split rendering ownership, don't rewrite the data layer.** `scripts/dashboard.py`
keeps every aggregation function unchanged and gains one additive function, `emit_json()`,
serializing the same in-memory structures to camelCase JSON. A new `dashboard-ui/` (Vite +
React + TypeScript) app owns 100% of presentation - the KPI strip, project/engagement cards,
portfolio views, and the new swimlane/loop-arc timeline. The plain HTML `render()` path is
**frozen, not deleted** - it stays the no-Node fallback (`--out`, unchanged, still tested),
kept because rewriting it added no value and removing it would break plugin-cache installs
with no Node available.

**Decision: static build, zero server** (locked via `AskUserQuestion` before implementation) -
`npm run dashboard` = `emit_json()` write + `vite build`, producing one `dashboard-ui/dist/
index.html` you still just double-click open. No `npm run dev` loop, no running local server -
the project's own "no server, no port, no auth surface" house rule stays honoured.

**A real technical trap, caught before it shipped broken:** Vite's default build emits
`<script type="module" src="...">`, which Chrome/Edge block from loading under `file://`
(module-script cross-origin restriction) - the page would silently render blank when
double-clicked open, the exact failure mode "static build, zero server" was supposed to
prevent. `vite-plugin-singlefile` fixes this correctly: it inlines JS/CSS into one **inline**
`<script type="module">` (no external `src=`), which does NOT trigger the restriction (the
restriction is about a module *fetching another file* cross-origin, not an inline script with
no external imports left after bundling). Verified live: built the app, ran
`google-chrome --headless --dump-dom "file://.../dist/index.html"` and confirmed real content
(KPI strip, tab labels, the swimlane SVG, a rendered `REVIEW-LOOP` arc) in the DOM - not just
`npm run dev`, the actual `file://` path the tool is supposed to work under.

**Decision: ordinal (not linear) time axis for the timeline** - dates are day-granular and
sparse; a linear scale would either crush same-day back-and-forth into illegible overlap
(exactly the loops most worth showing) or waste width on empty gaps. Column pitch is ordinal
with a capped `log2(day-gap)` nudge, so a real time gap is still hinted at without dominating
the layout.

**Decision: three tabs (Engagements / Portfolio / Sessions & cost), not an accordion** - the
session/token table is ops telemetry, categorically different from delivery tracking, and was
the literal source of "the long list of sessions and then only one engagement is confusing."
An accordion still occupies the same scroll position directly after an engagement; a tab
removes it from that flow entirely.

### Consequences (v0.2)

- `dashboard-ui/` adds this repo's first Node/npm dependency - scoped deliberately to this
  one user-run, not-agent-invoked tool (see `dashboard.py`'s own docstring); the plugin's own
  agent-invoked tooling stays stdlib-only, untouched (CLAUDE.md's pip-less requirement is
  about `scripts/*.py` the TEAM runs, not this).
- Two implementations of the same view now exist (Python HTML, React). This is accepted, not
  ignored: the Python path is explicitly frozen/insurance-only, not under active visual
  development, so it doesn't become two things drifting apart - it becomes one thing plus one
  known-stale fallback.
- `dashboard-ui`'s primary path needs a repo-as-project checkout with Node; a plugin-cache
  install (or a machine with no Node) falls back to the plain HTML path automatically - see
  `.claude/skills/dashboard/SKILL.md` step 1's mode check.
- Pure timeline-parsing logic (`buildTimelineModel`, `parseHandoff`, …) is unit-tested
  (Vitest, `dashboard-ui/src/lib/timelineModel.test.ts`); component/rendering tests are
  explicitly out of scope for v1 (visual verification is the headless-Chrome dump above plus
  manual review) - a narrower bar than the Python side's test discipline, stated rather than
  silently lower.

## §7 - v0.3: engagement cross-linking, real dollar cost, per-model breakdown (2026-08-08, same day)

Two more rounds of live feedback on v0.2's shipped result. First: *"its not there eg no links
to the actual engagements, portfolio feels disjointed from the page that actually shows
engagements"* - the Portfolio tab (roster bars, obligation coverage) was a dead end, showing
aggregate facts about engagements with no way to reach the engagement itself. Second, in the
same breath: *"the cost table should be scoped to actual engagements... and have an actual
cost"* - the Sessions & cost tab showed every raw transcript as one flat 20-row list with token
counts only, no dollar figure and no relationship to the engagements the rest of the page is
organized around.

**Decision: cross-link via a callback, not a router.** Adding client-side routing for three
static tabs would have been a disproportionate answer to "clicking something in Portfolio
should take me to that engagement." Instead `App.tsx` owns a small `navTarget` state
(`{project, slug}`) and a `goToEngagement` callback threaded down to `RosterBars` and
`ObligationTable`: switch to the Engagements tab, `scrollIntoView` the target row (found by a
stable `id`, `lib/links.ts`'s `engagementAnchorId`), and flash it via a CSS animation
(`prefers-reduced-motion`-safe) so the click's effect is visible even when the row was already
on screen. `ObligationTable` needed a Python-side change first - `obligation_coverage()` now
tracks per-citation `sources` (the distinct project/engagement pairs that cited it), since
there was previously no way to know *which* engagement a citation count belonged to.

**Decision: date-range matching for cost-to-engagement scoping, stated as inferred, not
hidden as fact.** There is no session-to-engagement link anywhere in the data model - a
Claude Code transcript file has no engagement field. Asked via `AskUserQuestion` how to
handle this; the answer ("rollup + filtered table") confirmed inferring the link rather than
skipping the feature. `_match_engagement()` matches a session's date against the engagement
whose `opened`&rarr;`closed` window contains it (ties broken by most-recently-opened); a
session matching nothing is explicit "Unattributed", never silently dropped. Every UI surface
showing this data - the engagement-card cost badge, the Sessions & cost tab's group headers -
is labeled 🧠 inferred, consistent with the operating guide's data-provenance discipline.

**Decision: real dollar cost from a cached pricing table, not token counts alone.** The
literal ask ("have an actual cost") required knowing *which model* priced *which tokens* -
previously discarded, since `_walk_usage` only ever extracted the `usage` dict, never its
sibling `model` field on the same message. Fixed by reading both together
(`_walk_message_usage`) and pricing each message against `_MODEL_PRICING_PER_MTOK` (a cached
snapshot via the `claude-api` skill, list rates, not the time-limited Sonnet 5 intro rate -
keeps historical figures from silently shifting when that window closes). A message whose
model isn't in the table (a synthetic/internal message, or a model shipped after the table
was last refreshed) doesn't guess - it's excluded from the dollar total and the whole
session/engagement/portfolio total it rolls into is marked `costPartial`, rendered with a
trailing "+" so the figure reads as a floor, not a claim of completeness. Live data caught a
real gap this way before it shipped: the first pricing-table pass covered Opus/Sonnet/Haiku
only, and real transcripts showed `claude-fable-5` usage pricing at $0 - Fable 5 and Mythos 5
rates were added and pinned with a regression test.

**Decision: per-model breakdown and cache hit-rate, requested directly after seeing two
comparable open-source dashboards** (`AgentHydra`, `yahav10/claude-code-dashboard` - fetched
and summarized live, not otherwise part of this codebase). Both were additive once the
model-per-message data existed: `_cost_by_model_rows()` aggregates the same per-session
`cost_by_model` breakdown machine-wide into a new "Cost by model" table; cache hit rate
(cache-read &divide; (cache-read + input)) needed no Python change at all, computed
client-side from fields already on the wire.

### Consequences (v0.3)

- `scripts.check_citations`'s obligation-coverage sources and the new per-message pricing
  both changed the shape of `emit_json()`'s payload - every shape change is pinned by a
  dedicated Python test (`test_emit_json_sessions_carry_engagement_slug_and_rollup_attaches`,
  `test_cost_by_model_rows_aggregates_across_sessions_and_projects`, etc.), not just visual
  review, so a future regression fails a test before it fails a screenshot.
- Cost figures throughout the page are **estimates at current list pricing** - they exclude
  negotiated discounts, time-limited introductory rates, and (for the "Unattributed"/floor
  cases) a small and clearly-marked share of real usage. This is stated in-page (the Sessions
  & cost tab's footnote) rather than left implicit in a plain dollar sign.
- The pricing table is a maintenance surface with no automated freshness check - a new model
  release means a manual edit to `_MODEL_PRICING_PER_MTOK` (and, ideally, a test like
  `test_price_usage_covers_fable_and_mythos`) or its tokens keep pricing at $0 silently until
  someone notices, exactly as happened once already in this same pass.
