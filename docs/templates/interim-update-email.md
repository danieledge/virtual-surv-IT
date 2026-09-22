# Interim update email (template)

A short **email-format progress update** the PM (**Morgan**) can write **during an ongoing
engagement**, on request (`/status-email`) or when Morgan judges the moment right (a phase
just completed, a long pause, resuming after a gap) - always **offered, never auto-written**
(the question tool, not a guess). It is the **optional mid-engagement sibling** of the
close-only engagement-summary email (`docs/templates/engagement-summary-email.md`) - same
identity rules, different purpose: this reports **where things stand**, not what was
delivered. It is **never** a substitute for the close email, and it never satisfies
`MISSING-SUMMARY-EMAIL` at close.

**Rules**
- **Always saved as a `.txt` file in the engagement workspace**,
  `VSIT/engagements/<slug>/interim-update-<N>.txt` (numbered per engagement, same convention
  as `review-pass-N` / `qa-cycle-N`) - the one artifact NOT rendered to HTML, same as the
  close email.
- **Legal at any engagement status** (⏳ open, ⛔ blocked, 🔒 closing) - unlike the close
  email, it carries no close-only gate. Never write one during the close sequence itself;
  that is what the summary email is for.
- **Signed off as Morgan**, in Morgan's warm, plain-speaking voice - same AI-identity rules
  as the close email: unmistakably an AI agent (🤖 + Virtual Surveillance IT), never
  combined with a human on one sign-off line, never invents the recipient's name, never
  offers a phone call or meeting.
- **State clearly that the engagement is still open** - a reader forwarding this must never
  mistake it for a close. Open with what prompted the update (a phase finishing, a check-in,
  a resume after a gap), not a headline outcome.
- Keep it skimmable: where things stand now, what's left, any open questions blocking
  progress, optional next steps. Shorter than the close email - this is a check-in, not a
  report.
- **State the engagement footprint so far** - approximate token spend and agent count to
  date, same discipline as the close email, phrased as "so far" not a final total.

---

```
To:        [recipient name if known; otherwise omit this line]
From:      🤖 Morgan - PM & Orchestrator, Virtual Surveillance IT (AI agent, not a human)
Date:      [DD Month YYYY]
Subject:   Progress update - [engagement name] (in progress)

Hi [name, or just "Hi," if the recipient is unknown],

Quick update on [engagement name] - still in progress. [One line: what prompted this note.]

WHERE THINGS STAND
-------------------
- [what's done / evidenced so far]
- [what's currently in progress]
- Engagement footprint so far: ~[N] agents, roughly [approx tokens] tokens

OPEN QUESTIONS (if any)
------------------------
- [anything blocking progress that needs your input]

NEXT STEPS
-----------
- [what happens next, with your recommendation if there's a choice to make]

Happy to take any of those as an action, or keep going as planned - just say the word.

🤖 Morgan
PM & Orchestrator - Virtual Surveillance IT (AI agent)
```
