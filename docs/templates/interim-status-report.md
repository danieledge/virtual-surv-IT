# Interim Status Report - <TITLE>

> **The mid-engagement sibling of `delivery-report.md`, not a smaller copy of it.** Produced
> by `/status-email --report` (or an in-session request Morgan judges warrants one), always
> paired with an interim-update-email pointing at it - never sent alone. Authored in `.md`,
> rendered to `.html`, numbered per engagement (`interim-status-report-1.md`,
> `interim-status-report-2.md`, ...) - same pass-scoped naming as `review-pass-N`/`qa-cycle-N`,
> which is what keeps it OUT of the close-only gates (`FINAL-BEFORE-CLOSE` only matches
> `delivery-report.*` and `final-.*`). **This is not a close deliverable** - it carries no
> verdict, no sign-off table, and never substitutes for `delivery-report.md` or the
> close-only summary email.

> **Document control** · ID `ISR-<slug>-<N>` · Version `<N>` · Status `Interim - engagement in
> progress` · Owner `Morgan` · As-of `<YYYY-MM-DD>`

| | |
|---|---|
| **Engagement** | <name / slug> |
| **Phase** | <plan / delivery / close, from `engagement_state show`> |
| **Report #** | `<N>` of this engagement (see `interim-status-report-<N-1>.md` for the prior one, if any) |
| **Prompted by** | user request / a phase completing / a scheduled check-in |

## Where things stand

Plain-language: what's been delivered so far, what's currently in flight, what's next.
**Reconcile with the original brief** - is the plan still on track, has scope shifted, is
anything blocked. No verdict here (this isn't a close) - state, not judgement.

## Deliverables so far

| Artifact | Status | Link |
|----------|--------|------|
| `<name>` | interim / final | [`<name>`](<name>.html) |

## Findings, if this engagement produces any *(omit section entirely if N/A)*

Current disposition, drawn from the live findings pack(s) - **not** a restated snapshot from
an earlier pass (draw fresh at report time, the same discipline
`check_findings_render_freshness` enforces for `REVIEW-<slug>.md`).

**Disposition:** _N_ fixed · _N_ open · _N_ accepted · _N_ deferred.

## Since the last report *(omit for report #1)*

What changed since `interim-status-report-<N-1>.md` - new deliverables, findings resolved,
scope changes. Keeps a long engagement's reports additive instead of each one restating
everything from the start.

## Open questions / risks

Anything that needs the user's input to keep moving, or a risk worth flagging now rather than
at close. Empty is a fine, correctly-reported answer - never invent a risk to fill the section.

## Engagement footprint so far

Approximate token spend and agent count **to date** (never a final total - this engagement
isn't closed). Same discipline as the interim-update-email and the close summary.

---
> **Run provenance.** Model `<model id>` · Framework `compliance-surveillance-team <version>` ·
> Report generated `<YYYY-MM-DD>`. Same non-determinism note as every other artifact this team
> produces: this is one dated snapshot, not a guarantee of what a later pass would find.
