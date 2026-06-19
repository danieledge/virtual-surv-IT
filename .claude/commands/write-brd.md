---
description: Turn an idea into a Business Requirements Document (BABOK + EARS)
argument-hint: <the idea / business need>
---

Under the PM (CLAUDE.md §6), turn this idea into a BRD: **$ARGUMENTS**

1. Clarify first — ask the user any questions needed (scope, jurisdiction, success metrics);
   don't guess material decisions.
2. Route to **requirements-analyst** to draft using `docs/templates/brd.md`.
3. Write each requirement in **EARS** form ("When `<trigger>`, the system shall
   `<response>`") with a stable ID (BRD-001, …) and the regulatory/business driver cited
   per requirement (CLAUDE.md §2).
4. List open questions for the PM to raise with the user.
5. Save `artifacts/BRD-<slug>.md` and render: `python -m scripts.render_html artifacts/BRD-<slug>.md`.

Hand off: the BRD feeds `/brd-to-fsd`.
