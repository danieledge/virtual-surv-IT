---
description: Turn an idea into a Business Requirements Document (BABOK + EARS)
argument-hint: <the idea / business need>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), turn this idea into a BRD: **$ARGUMENTS**

**The standard open applies before drafting begins, even when this skill is invoked directly.**
Read `.claude/skills/.shared/engagement-bookends.md` and follow it - the Engagement Brief and
`engagement_state init` (unless `/engage` already wrote them) before step 1, the closing bookend
at the end.

1. Clarify first - **ONE `AskUserQuestion` call, one question per axis inside it** (scope,
   jurisdiction, success metrics - up to 4 axes per call, each **single-select** where
   mutually exclusive); never a screen per axis (2026-08-17 flow review - the same
   batching the intake gate uses). Don't guess material decisions. If scope/stakeholders
   are unclear, start with `/elicit-requirements`.
2. Route to **business-analyst** to draft using `docs/templates/brd.md` (plugin mode: `$PLUGIN_ROOT/docs/templates/brd.md` - resolve it; missing from the working repo is never a blocker).
3. Write each requirement in **EARS** form ("When `<trigger>`, the system shall
   `<response>`") with a stable ID (BRD-001, …) and the regulatory/business driver cited
   per requirement (CLAUDE.md §2). **Retrieve any pinpoint regulatory citation from the register**
   (`config/regulatory-register.yaml`; `<python> -m scripts.check_citations --typology <x>`) - never
   invent an article/section/rule; mark unsupported pinpoints as to-verify (ADR-001).
   (`<python>`: the `INTERPRETER=` word the step-0 probe printed, verbatim, never re-probed; direct invocation and plugin-mode paths: `.claude/skills/.shared/run-mode.md`)
4. List open questions for the PM to raise with the user.
5. Save `VSIT/engagements/<slug>/BRD-<slug>.md` (the engagement workspace, ADR-010) and render: `<python> -m scripts.render_html VSIT/engagements/<slug>/BRD-<slug>.md`.

**Close - don't dead-end (CLAUDE.md §6).** Summarise the BRD (what it covers, the key
requirements, any open questions for the user), then offer the next step with a
recommendation: proceed to the Functional Spec now (`/brd-to-fsd`), or pause for the user to
resolve the open questions first. Offer to carry it out and wait for the go-ahead - don't
leave the user at the BRD with no obvious next move.
