---
description: BA elicitation - stakeholder analysis, requirements gathering and traceability (BABOK)
argument-hint: <the need / obligation / problem to elicit requirements for>
---

Run a Business-Analysis **elicitation** for: **$ARGUMENTS**

Under the PM (CLAUDE.md §6), drive **business-analyst** through the BABOK elicitation → analysis
→ specification flow. **Ask material questions via the question tool, one question per axis, and
wait** - single-select where the axis is mutually exclusive; never invent scope, stakeholders or
thresholds.

> If the need is already clear and you just need the BRD, use `/write-brd`.

1. **Stakeholder analysis** - who's affected / consulted / decides (RACI), and their needs and
   concerns (`docs/templates/stakeholder-analysis.md`).
2. **Elicit** - from the obligation/problem and any documents provided: interviews/workshop
   prompts, document analysis. Capture needs and **confirm** them back.
3. **Analyse & specify** - business + functional requirements in **EARS**, each with a stable ID
   and the **regulatory/business driver cited** (CLAUDE.md §2). Note current vs target where a
   process is involved (point at `/reg-change-impact` or a process map if needed).
4. **Acceptance criteria** in Gherkin (incl. true-positive and false-positive handling), and an
   **RTM** entry (`obligation → BRD → FSD → code → test`).
5. For detection logic, get the relevant **`*-sme`** to confirm typology; thresholds are
   SME/`tuning-analyst` decisions - flag them, don't invent.

Output: an **elicitation/requirements doc** (`docs/templates/elicitation-requirements.md`) +
stakeholder analysis, under `artifacts/`, rendered to `.html`.

**Close - don't dead-end.** Summarise the requirements + open questions, then offer the next
step with a recommendation: proceed to the FSD (`/brd-to-fsd`) or the build (`/build-solution`),
or resolve open questions first.
