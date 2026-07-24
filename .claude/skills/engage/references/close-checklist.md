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
