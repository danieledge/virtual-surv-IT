---
description: Write a short interim progress-update email for an ongoing engagement, optionally paired with a fuller interim status report - the mid-engagement sibling of the close-only summary email and delivery report
argument-hint: "[--slug SLUG] [--report] [context/reason for the update]"
disable-model-invocation: true
---

# /status-email

An **optional, mid-engagement** progress update - Morgan's short email-format note on
where things stand, for a requester who wants (or you judge would appreciate) a check-in
before the engagement closes. Optionally paired with a fuller **interim status report** when
real substance has accumulated. Neither is **ever** the close-only engagement-summary email
or `delivery-report.md` (operating guide "Outcome discipline" rules 3/3a) and neither
satisfies `MISSING-SUMMARY-EMAIL` - that pair is written automatically at close,
unconditionally, and is not what this command is for.

**Email vs. email + report - decide this first:**
- **`--report`, or the user explicitly asks for a report/write-up/full status** (not just "an
  update" or "how's it going") → produce BOTH: the report (step 4) and the email pointing at
  it (step 3). An explicit ask needs no confirmation, same rule as the email itself.
- **A bare request, or your own judgement that a check-in is due** → the email only, by
  default. Additionally *offer* a report only if real substance has accumulated since the
  last one (or since open, if there has not been one) - a real completed phase, several
  new deliverables, a meaningful findings-disposition change. Ask via the question tool before
  writing a report on your own judgement; never on the email alone (see "Offer, don't assume"
  below).
- **A report is never sent without its email.** The email is what tells the reader the report
  exists; a report with no cover note is a document nobody was told about. The reverse is
  fine: plenty of check-ins are email-only, no report attached.

**Offer, don't assume.** If the EMAIL was triggered by your own judgement (a phase just
finished, a long pause, resuming after a gap) rather than a direct user request, confirm via
the question tool before writing anything - a single yes/no is enough. A direct request
(`/status-email`, or the user asking in plain English, including mid-engagement with no slash
command typed at all) needs no confirmation for the email. The REPORT half of that judgement
call is separate and stated above.

1. **Find the engagement.** `<python> -m scripts.engagement_state show` (plugin mode: see
   `.claude/skills/.shared/run-mode.md`) resolves the active engagement the same way every
   other `engagement_state` command does - `--slug SLUG` overrides it if `$ARGUMENTS` names
   one. If it errors because more than one engagement is open and none is active, list the
   open slugs (`engagement_state list --menu`) and ask via the question tool which one; never
   guess. If NO engagement is open (or the only one is 🔒 closing / ✅ closed), say so plainly
   - a closing/closed engagement wants the close summary, not this - and stop; never invent an
   engagement to report on.

2. **Decide email-only or email + report**, per the rule above.

3. **Write the email.** Number it: check the workspace for existing `interim-update-*.txt`
   files and use the next integer (`interim-update-1.txt`, `interim-update-2.txt`, ...).
   Follow `docs/templates/interim-update-email.md` exactly - the identity rules (signed
   Morgan, 🤖-marked, never a phone call, never invents the recipient) are the same as the
   close email's; the content is different: where things stand *right now*, not a final
   outcome. Draw WHERE THINGS STAND from the engagement's own state (`engagement_state show`
   - status, artifacts so far, outstanding items) rather than re-deriving it from memory.
   State the **footprint so far**, phrased as "so far," never as a final total. **If a report
   is also being produced this turn, its WHERE THINGS STAND section is one line pointing at
   the report** (`Full status report: interim-status-report-<N>.html`) instead of restating
   the report's content in the email.

4. **Write the report, only when step 2 decided one is warranted.** Number it independently
   from the email (`interim-status-report-1.md`, `interim-status-report-2.md`, ... - its own
   counter, not shared with `interim-update-*`). Follow
   `docs/templates/interim-status-report.md` exactly - it is the mid-engagement sibling of
   `delivery-report.md`, not a smaller copy of the email: progress against the original
   brief, deliverables so far with links, the current findings-pack disposition tally if this
   engagement produces findings (drawn FRESH at report time, not copied from an earlier
   pass), and - for report #2 onward - a "since report N-1" section so the report stays
   additive rather than restating everything each time. Render to `.html`
   (`<python> -m scripts.render_html <path>`) - it is a real document, not an email; it needs
   the HTML sibling like any other artifact.

5. **Register everything written this turn like any other artifact:**
   `<python> -m scripts.engagement_state add-artifact <path> --title "<title>"` for the email
   and, if produced, the report - this keeps the index in sync (`STALE-INDEX` fires on an
   unlisted file exactly as it would for any other artifact) and renders it into START-HERE.

6. **Say what was optional, out loud, once written.** Confirm what you saved (email only, or
   email + report), state plainly that this is a progress note and not the close, and
   continue the engagement exactly as you would have without it - this command never changes
   engagement status or advances the lifecycle.
