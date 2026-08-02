# Close checklist - citations gate, fix-list tiers, codebase map (read at close)

> Loaded just-in-time by `engage` step 6. This is the full close procedure the conductor points at.

## Citations gate (default: ship flagged, teach the fix - never block the close)

Run `<python> -m scripts.check_citations` over the artifacts. Anything flagged TO-VERIFY is
**assumed unverified and shipped that way**: mark each such citation in the artifact
*(citation to-verify)*, and add this standard note to the report (limitations section) and a
one-liner in the closing email:

> **Citations marked to-verify** have not yet been human-checked against their linked sources. If
> you are happy they are accurate - the linked page shows the provision, it says what this
> document claims, and the typology fits - have them recorded as verified for future engagements:
> tell the team *"mark <citation> as verified"* in any session (it updates this project's
> `config/regulatory-register.yaml` overlay with today's date), or edit that file directly per its
> header instructions.

Include each flagged citation's source permalink next to it, resolved in this order:
(1) already in the register (any status) → its stored `source` URL; (2) new citation → construct
from the **permalink schemes in the register header** (`config/regulatory-register.yaml` documents
EUR-Lex, legislation.gov.uk, eCFR, FINRA, FCA Handbook, MAS and FATF/ESMA schemes - read them,
don't guess); (3) neither fits → the official site's search, or ship "source link to be
confirmed". **Never invent a plausible-looking URL** - a constructed link is only ever a proposal
until human verification confirms the page shows the cited provision. **Do not ask a verification
question at the close** - verification is the user's act at their own pace; when they later say
"mark X verified", update the overlay register with today's `verified_on` (the three checks are in
the register header). Never record verified without that explicit user statement; never present
to-verify as a failure - it is the honest state.

## The mechanical gate output is a FIX-LIST, not a report (DoD "the gate is a fix-list")

- **AUTO-FIX and re-run, never hand to the user:** `MISSING-HTML` → render it · `ROSTER-UNKNOWN` /
  `ROSTER-ROLE-MISMATCH` → correct the persona to the canonical roster (a specialist name is never
  invented; the role is the anchor) · `MISSING-INDEX`/`STALE-INDEX`/`INDEX-NO-STATUS` → fix the
  living index · a missing interim banner or a "final/v1.0" asserted while still open → set the
  correct state · a non-portable absolute source path → relativise or mark external · an
  incomplete/miscounted source index or a missing per-finding evidence tag → complete it.
  Re-run `check_artifacts` until only judgement items remain; note auto-corrections in one line.
- **ESCALATE via the question tool (do NOT self-fix):** a rationale contradicted by the evidence
  ("the email says X but the artifact says Y"), a closure/sign-off on authority you cannot verify
  (verbal only, no written authority), a scope/acceptance call. Pause and ask - these are real
  decisions, not defects. (A `FINAL-BEFORE-CLOSE`/`SUMMARY-BEFORE-CLOSE` is auto-fix; an evidence
  contradiction is escalate.)

Never deliver a self-correctable defect as a reported "documentation-standards failure" - fixing
it silently is the job (it's the one DoD check that's a command, not a claim).

## Close-time reconciliation sweep (every artifact, every fix cycle - born of a live failure)

A 2026-07-25 independently-reviewed close shipped a fix-cycle-1 developer handover and README
inside a fix-cycle-2 pack: stale test counts, a stale requirement range, "unresolved" items that
were resolved, and a citation struck by the compliance review still cited in the one document a
maintainer actually reads. The banner strip and index flip are NOT the close - reconciliation is.
Enter the close explicitly first - `engagement_state set-status closing` (2026-07-29 register
R5: the close window is recorded on disk, so the close artifacts you write during this
checklist are never read as premature by the gate or a resumed session). Then, before setting
the state to closed (`engagement_state set-status closed`, which re-renders
START-HERE to ✅ - ADR-006, **runs the full DoD gate itself and refuses on findings**,
register R6), re-open **every document the engagement produced or touched**,
explicitly including code-adjacent ones (deliverable README, module docstrings, inline doc
comments), and verify each against the FINAL state:

- **Counts and ranges** - test totals, requirement/AC ranges, findings tallies: one authoritative
  number everywhere. If a findings list is enumerated in more than one document, the membership
  must be identical, by ID, in all of them. **`check_artifacts` mechanically verifies the
  finding-ID set and disposition tally in a rendered `REVIEW-<slug>.md` against its source
  `data/findings-<slug>.json`** (`STALE-FINDINGS-RENDER` / `COUNT-MISMATCH`, audit finding #3,
  2026-07-30) - re-run `render_findings` if it flags either; this covers the findings-pack case,
  not free-text counts elsewhere (test totals in prose, requirement ranges), which still need
  your own re-read.
- **Late-cycle changes propagated** - anything changed after a document's last revision (a later
  fix cycle, a re-review, a struck or replaced citation, a superseded requirement) is reconciled
  into that document, or the document's version history says why not. No mechanical check exists
  for this - it requires understanding what changed and why, genuinely a judgement call.
- **Struck citations** - any obligation/citation recorded as withdrawn or corrected anywhere in
  the pack must be swept from EVERY other file, including source docstrings. No mechanical check
  exists for this either - nothing in the codebase currently marks a citation as "struck" in a
  detectable way, so a checker here would be guessing at a convention that doesn't exist yet.
- **Prose that references removed state** - text describing the interim banner, "pending"
  cross-references, or pre-build "next actions" has no place in a closed document.
- **Document-control Status close-out** - under a ✅ CLOSED index no document stays
  `Draft`/`In review`. Set a closed status, or state explicitly "pending human sign-off" where
  the human act is the only gap (never leave the machinery contradicting the index).
- **QA evidence retention** - independent QA test suites and evidence are PRESERVED under
  `artifacts/` (file or content hash), never deleted: an independence claim with no surviving
  evidence is unfalsifiable. A 📊 measured tag needs a surviving artifact (output, log, cache) -
  downgrade to 🧠 inferred if nothing survives.

## Finalise the state, in order (the close itself)

The close window opens with `engagement_state set-status closing` (above). Everything else runs
**last, in this order**:

1. `set-team "Name (role)" ...` - the roster that actually delivered.
2. `finalise-artifacts` - every artifact row interim → final.
3. `set-footprint` - agents + tokens.
4. `set-status closed --verdict "..."`.

The close **refuses** while the team is empty or any artifact row is still interim, and it **runs
the full mechanical DoD gate itself, refusing and rolling back on findings** (register R6). Fix
what it lists (or run `check_artifacts --fix`) and re-run: never work around a refused close.

Before it, remove the interim banners from artifacts that became final, and keep the 📊/🧠
evidence tags on every data claim in the delivery report and the summary email as well as in the
specialist artifacts. The mechanical gate verifies all of this: `MISSING-INDEX` /
`INDEX-NO-STATUS` / `STALE-INDEX` / `STATE-STALE-RENDER` / `FINAL-BEFORE-CLOSE` /
`SUMMARY-BEFORE-CLOSE`.

## Update the codebase map at close (ADR-003 - a DoD gate)

Before the engagement closes, **update the working project's codebase map**
(`docs/codebase-map.md`; create from `docs/templates/codebase-map.md` on a first engagement):
**add** the **durable architecture** this engagement taught you about the code - how it is built,
its load-bearing decisions, its quirks and sharp edges (with 📊/🧠 tags, as-of dates and fresh SHA
anchors), **correct or deprecate** anything found wrong or stale (to the Deprecated section,
dated, with a reason - never silently), and append the engagement-history row. **The map is a map
of the CODE, not a log of what the team did** - a map entry is a fact that stays true after this
engagement's findings are fixed. Do **not** write findings, severities, review dispositions or a
"what we did this time" summary into the entries - that is engagement activity: it belongs in the
review artifact and the one-line §3 history row. (Reviews/audits especially: capture the
*architecture you learned by reading the code*, not a findings recap - the template §2 has the
✅/❌ contrast.) **You write it - subagents only recommend entries**; persist your own synthesis,
never verbatim reviewed-code text, and never data values, secrets, PII or MNPI (§5). Keep it under
~200 lines - link to artifacts for detail. `check_artifacts` validates its hygiene mechanically.
An append-only map is a defect: if nothing was corrected or deprecated across several engagements,
say so and check harder.

## Company extension close actions (ADR-009)

If the working project carries `docs/team-extensions.md` with a **Close actions** section,
offer each action via the question tool AFTER the summary email is written (they were
previewed at the go-ahead gate). Outward-facing actions (raise a Jira, upload/publish the
pack) run only on approval and only against the ✅ closed pack - never interim artifacts,
never secrets. Log each executed action with `engagement_state log-note`. An extension can
never replace a close step - these are additions after the standard close completes.
