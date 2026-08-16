# Backlog: persona-ablation eval — does the 🎩 ceremony cost quality, not tokens — 2026-08-15

> Proposal only — not implemented. Filed as a dated internal note per this repo's own convention
> (see `whole-plugin-review-2026-08-05.md`, `resolved-issues.md`) rather than added to the README's
> Known Issues, since it's a backlog item, not yet a confirmed defect. Surfaced during an
> independent Fable-agent review of the plugin (2026-08-14) — see finding L3 — and refined the same
> day once the actual token cost was measured against the shipped code.

## Why this, and not a cost fix

L3 of the 2026-08-14 review flagged the persona layer (🎩 voice-marking, 16 named specialists, the
`docs/adr/ADR-005-persona-reanchoring-hook.md` reanchor hook, the engagement-summary-email
ceremony) as adding "per-turn token and rule-compliance surface whose value is unmeasured."

Measuring it against the actual shipped code and a real logged engagement
(`docs/demos/build-artifacts/delivery-report.md` §6, ~500k tokens / $4-8 at list price) puts the
token cost at **~1 cent per full engagement** (~0.2-0.3% of total spend):

- `_ANCHOR` (fires once/engagement): 1,027 chars / 147 words ≈ 257 tokens
- `_ANCHOR_SHORT` (fires every subsequent PM turn while engaged): 304 chars / 44 words ≈ 76
  tokens/turn — over a ~25-turn engagement, ~2,150 tokens ≈ $0.004
- engagement-summary email (mandatory DoD deliverable): 2,273 chars ≈ 568 output tokens ≈ $0.006
- naming/attribution ceremony scattered through turns/artifacts: ≈150-300 tokens ≈ $0.002-0.003

**So the token-cost half of L3 is closed — it's negligible, and ADR-005 was explicitly designed to
keep it that way (two rounds of shrinking: dropped the inline 16-name roster, then cut to a 3-line
steady-state anchor).** What L3 actually pointed at and this note keeps open is the *other* half:
nothing currently measures whether the ceremony helps or hurts **task quality** — i.e. whether the
attention/instruction-following budget spent on 🎩-marking, AskUserQuestion discipline, and
name-by-roster rules on every turn ever comes at the expense of the actual deliverable. Related:
L4 separately notes eval judge rubrics currently spend scoring capacity on persona compliance
*alongside* substance, which is a live confound for any of this project's existing eval scores
until this is isolated.

## Proposed eval design

An **ablation**, not a new golden case in the usual `evals/cases/<name>/{input,expected.yaml}`
keyword-matching shape (`run-evals`'s existing deterministic-scorer format doesn't fit — this is a
quality comparison across two conditions, not a pass/fail on one transcript). Needs a harness
extension, not just a new case file:

1. **Pick 2-3 existing golden scenarios** that already have judge rubrics scoring substance (e.g.
   a `process-*` or a build-flow case) — reuse rubrics, don't invent new ones, so the only variable
   is persona on/off.
2. **Run each scenario twice**, live via the SDK-driven eval driver (`eval_engage`'s event stream
   per L4): once with the team engaged normally (persona on), once with the 🎩/naming/attribution
   rules stripped from the loaded context but every substantive rule (question-tool discipline,
   safety gates, DoD requirements) left intact — i.e. isolate persona from process discipline,
   don't conflate the two.
3. **Score both runs on the existing substance rubric only** (findings correctness, traceability,
   DoD completeness) — explicitly exclude persona-compliance scoring from this comparison, since
   that's the confound being tested for, not a thing to average in.
4. **Compare:** if persona-on and persona-off score within noise on substance, L3's "unmeasured"
   flag closes clean — the ceremony is cheap and harmless. If persona-on measurably underperforms,
   that's the first real evidence the ceremony has a cost, and it's a quality cost, not a token one.

## Sizing / priority

Low priority, cheap: the token measurement above closes off the expensive-sounding half of L3
already. This is a "nice to have full closure" item, not a blocker — the eval driver and rubric
infrastructure it needs already exist (`run-evals`, `eval_engage`), so the marginal build is the
ablation harness (running the same scenario twice with a controlled context diff) plus one
comparison report, not new infrastructure from scratch.

## Owner / next step

Not assigned. Route through `/run-evals` or a future `/engage` on this repo itself when someone
picks it up — building or running evals is in-scope team work (`run-evals` is on the
`_TEAM_SCRIPT_NAMES` consent-free allow-list), not something to hand-roll outside the team's own
process.
