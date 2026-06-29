# ADR-001: Ground regulatory citations in a retrieved source, not model memory

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-001` · Version `0.1` · Status `Draft`
> · Classification `Internal` · Owner `Morgan (PM) / compliance-reviewer` · As-of `2026-06-29`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-29 | project review | Initial draft |

| | |
|---|---|
| **Status** | proposed |
| **Date** | 2026-06-29 |
| **Deciders** | Morgan (orchestrator), `compliance-reviewer`, human approver |
| **Traceability** | Obligation: traceability spine integrity (CLAUDE.md §4, §8); RTM `obligation → BRD/FSD → code → test` |

## Context

The team's central promise is **auditability**: a traceable link from `alert → logic →
regulatory obligation`, recorded in the RTM and checked by `compliance-reviewer`. That spine is
only as trustworthy as the regulatory references in it.

How the model works makes this a first-order risk. An LLM emits citations like "MAR Article 12",
"FFIEC BSA/AML §X" or "Rule 10b-5" from **parametric memory** - precisely the regime in which it
confabulates *confidently and fluently*. A fabricated or subtly wrong pinpoint citation
(article, paragraph, effective date) is not a typo in this domain: it is a control failure that
survives into a signed-off audit pack, because every downstream reviewer is the *same* model
sharing the *same* blind spot. Self-verification cannot fix this - the model cannot reliably
introspect which of its own citations are grounded.

Today the project's defences are partial: `docs/scope-and-stack.md` carries **example** regimes,
and the `📊 measured vs 🧠 inferred` convention is honour-based (the model self-tags). There is
no mechanism that *prevents* an invented pinpoint citation from being asserted as fact. Two new
eval cases (`citation-no-fabricated-reg`, `citation-flag-unverified`) now demonstrate the failure
mode but do not remove it.

## Decision

Treat a regulatory citation like a threshold: **it must be grounded or flagged, never invented.**

1. **Source of truth.** Maintain a project-local, version-controlled **regulatory register** (the
   firm's in-scope obligations - regime, instrument/typology, pinpoint reference, effective date,
   source URL/document id). `docs/scope-and-stack.md` becomes the example seed for it.
2. **Retrieve, don't recall.** When any deliverable needs a pinpoint citation, the producing agent
   must **retrieve** it from the register (lookup over a controlled corpus), not generate it from
   memory. If the register has no matching entry, the agent cites at the **level it can support**
   (named regime / typology) and marks the pinpoint as `to-be-verified` with an owner.
3. **Mechanical check at the gate.** `compliance-reviewer` verifies every emitted pinpoint citation
   **against the register** rather than reading it for plausibility. An unmatched pinpoint is an
   audit finding, not prose to be trusted.
4. **Earn the tag.** `📊` on a citation is permitted only when it resolves to a register entry; an
   unresolved citation is `🧠 inferred / unverified` by default.

## Consequences

**Positive**
- Removes the highest-severity silent failure (confident wrong citation) from the audit trail.
- Makes the traceability spine *verifiable* instead of *asserted*; `compliance-reviewer`'s pass
  becomes a check with ground truth, not a second opinion from the same weights.
- The register is reusable across engagements and is itself auditable / diff-able.

**Negative / costs**
- Requires building and maintaining the register (curation effort; must be kept current as
  obligations change - ties into `/reg-change-impact`).
- Retrieval adds a step and some latency to citation-bearing work.
- The register's *accuracy* becomes a new dependency - garbage in, garbage cited - so its
  provenance and update process need ownership.

## Alternatives considered

- **Status quo (honour-based tagging).** Rejected: relies on model introspection it does not have;
  the new eval cases show the failure mode persists.
- **LLM self-check ("are you sure this citation is real?").** Rejected as *sole* control: same model,
  same blind spot; improves confidence calibration marginally but cannot supply a missing fact.
- **Forbid all specific citations (cite only at regime level).** Rejected: throws away genuine
  traceability value where a pinpoint *is* known and correct; the register preserves it safely.
- **Live web retrieval of regulations.** Deferred: provenance/version-pinning and access are harder
  to make audit-stable than a curated, version-controlled register; revisit later.

## Implementation status & follow-up

| Item | Detail |
|------|--------|
| Implementation status | **core implemented (2026-06-29).** `config/regulatory-register.yaml` (seeded, example status), `scripts/check_citations.py` (retrieve via `lookup()`, mechanical gate via `check_text()` / CLI), 5 unit tests, and `compliance-reviewer` now runs the gate (a register-lookup step). Authoring skills wired (`/write-brd`, `/new-scenario`, `/reg-change-impact`); the 7 seed entries **verified against primary sources on 2026-06-29** (EUR-Lex, Cornell LII, FINRA) and flipped to `status: verified`. **Deferred:** `/brd-to-fsd` wiring (it inherits citations from the BRD); a CI gate (held off so it doesn't flag existing docs that cite obligations not yet in the register). |
| Implementing agent / team | `platform-engineer` (register + retrieval), `compliance-reviewer` (gate check) |
| Target completion | seed verification + skill wiring next |
| Follow-up actions | verify the seed obligations against primary sources (flip `status`); wire `lookup()` into citation-bearing skills; consider a CI gate once the register covers the repo's docs; `citation-*` eval cases remain the regression net |
| Linked tickets / PRs | - |

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
