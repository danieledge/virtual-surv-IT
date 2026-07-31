# ADR-010: One placement rule - the engagement workspace layout (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-010` · Version `0.1` · Status `Accepted`
> · Classification `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-07-29`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-29 | 2026-07-29 workflow-robustness remediation, phase 3 (user-agreed plan, decisions D2/D4) | Accepted & implemented: canonical layout, placement table, close-only REVIEW render, root orphan rule |

| | |
|---|---|
| **Status** | **Accepted / implemented** (remediation phase 3) |
| **Date** | 2026-07-29 |
| **Deciders** | Human approver (plan + D2/D4 rulings); layout detail Morgan (orchestrator) |
| **Traceability** | ADR-008 (workspaces), ADR-006 (state file), 2026-07-29 robustness register P1/P2/P3/P4/P5/P6 (`artifacts/workflow-robustness-findings.md`), remediation plan D2/D4 |

## Context

The 2026-07-29 robustness review found placement split across two worlds: ADR-008 made
`artifacts/<slug>/` canonical while roughly ten docs, six skills and the persona anchor
still taught flat `artifacts/` paths (P1); produced code and QA scripts had three
documented homes (P2); `check_artifacts --fix` manufactured the close-only `REVIEW-<slug>.md`
mid-engagement (P3); five first-class deliverables had a template but no stated address
(P4); the machine-readable `artifacts/data/` lane was defined only in a docstring and
validated non-recursively (P5); and the live tree held five engagements interleaved flat
(P6).

## Decision

1. **The engagement workspace is the one home.** Every engagement document, produced code
   file, test and QA artifact lives in that engagement's `artifacts/<slug>/` workspace.
   The canonical layout is FLAT at the workspace root plus one machine-readable lane:

   - `artifacts/<slug>/` - all deliverable documents (fixed filenames below), produced
     code, tests and QA evidence;
   - `artifacts/<slug>/data/` - machine-readable source (findings packs
     `findings-*.json`), validated recursively, excluded from the .html-sibling and index
     checks;
   - `artifacts/<slug>/adr/` - client-facing ADRs (`ADR-NNN-<topic>.md`), when the
     engagement produces them.

   A deliberate lane split (`deliverables/` / `code/` sub-trees) was considered and
   rejected: the QA-coverage gate scopes per top-level container (register G9 fix), so a
   `code/` lane would separate code from the QA handover that vouches for it. Grouping
   subfolders remain legal for a multi-part engagement, with the gate-enforced rule that
   **a subfolder containing code carries its own tests and QA handover**.

2. **Fixed filenames, fixed addresses** (the P4 homeless five now have homes) - the full
   document-type table lives in `docs/team-operating-guide.md` ("Where every document
   lives") and is the single reference the skills point at.

3. **`REVIEW-<slug>.md` is close-only in tooling, not just prose** (D4 ruling):
   `check_artifacts --fix` renders findings packs only while the pack is 🔒 closing /
   ✅ closed, and an uppercase `REVIEW-*.md` existing earlier is `FINAL-BEFORE-CLOSE`
   (case-sensitive - the interim `review-pass-N.md` names stay legal).

4. **Nothing sits unchecked at the artifacts root.** In workspace mode a root file is
   `ORPHAN-ARTIFACT` unless grandfathered in the one-time snapshot
   `.dod-root-allowlist.json` (D2 ruling: the historical flat files are exempt - no
   migration; the rule applies to new work only). Code delivered into the working
   project's own source tree remains governed by the skill/operating-guide escalation
   rule, not this gate.

5. **The index is generated, and now provably so**: the render embeds a content hash;
   a hand-edited START-HERE is `INDEX-HAND-EDITED`, and `--fix` backs the hand-edited
   file up before re-rendering (P7).

## Consequences

- One answer to "where does this document go", checked mechanically at the gate instead
  of taught inconsistently across a dozen prose surfaces.
- Legacy flat packs keep working (checked exactly as before; `migrate` remains the tidy-up
  path), and the pre-2026-07-29 root files stay grandfathered per D2.
- Standalone `/prepare-data` output (no engagement open) goes under `artifacts/data-prep/`
  so it neither trips the orphan gate nor pollutes an engagement workspace.
- The docs and skills that taught flat paths were swept to workspace paths in the same
  change (register P1); the DoD document's full rewrite follows in remediation phase 5.
