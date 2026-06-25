---
description: Turn an idea into a Business Requirements Document (BABOK + EARS)
argument-hint: <the idea / business need>
---

Under the PM (CLAUDE.md §6), turn this idea into a BRD: **$ARGUMENTS**

1. Clarify first - **ask via the question tool, one question per axis** (scope, jurisdiction,
   success metrics); make any mutually-exclusive axis **single-select**; don't guess material
   decisions. If scope/stakeholders are unclear, start with `/elicit-requirements`.
2. Route to **business-analyst** to draft using `docs/templates/brd.md`.
3. Write each requirement in **EARS** form ("When `<trigger>`, the system shall
   `<response>`") with a stable ID (BRD-001, …) and the regulatory/business driver cited
   per requirement (CLAUDE.md §2).
4. List open questions for the PM to raise with the user.
5. Save `artifacts/BRD-<slug>.md` and render: `python -m scripts.render_html artifacts/BRD-<slug>.md`.

**Close - don't dead-end (CLAUDE.md §6).** Summarise the BRD (what it covers, the key
requirements, any open questions for the user), then offer the next step with a
recommendation: proceed to the Functional Spec now (`/brd-to-fsd`), or pause for the user to
resolve the open questions first. Offer to carry it out and wait for the go-ahead - don't
leave the user at the BRD with no obvious next move.
