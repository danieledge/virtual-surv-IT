# Review-type menu - LOCKED construction (read when the work is a review)

> Loaded just-in-time by `engage` step 1b. Use **exactly** these questions, options and
> descriptions - do not improvise, merge or reword (a loose version once offered "Quick **and**
> Deep" as a multi-select - illogical, Deep already includes Quick). `scripts/locked_menu_guard.py`
> (audit finding #7, 2026-07-30) mechanically blocks that exact class of drift before the
> question reaches the user - don't rely on it instead of following this file.

**Price the choice in the accompanying message (2026-08-17, assessment rec).** In the chat
text that precedes this AskUserQuestion call - never inside the locked option wording below -
state one rough cost line for THIS target so depth is chosen priced, e.g.: "For this diff:
Quick runs in-session (cents) · Deep is one reviewer pass (roughly $1-3 at list) · Audit adds
the close machinery (roughly $3-8); plus the perf pass if chosen (~$0.5-1). **Expect the
engagement ALL-IN at roughly 2x the pass figure** - orchestration, scoring, the challenge and
artifacts ride on top - and more when caches run cold (5-minute TTL boxes). Budget status:
<DAILY/HEADROOM line when a budget is recorded>." Scale the figures to the target's size
honestly; the pass price and the all-in are both stated so neither is mistaken for the other -
order-of-magnitude is the point, not a quote.

**Critical construction rules:**
- **Ask Q1, Q2 and Q3 in ONE `AskUserQuestion` call** (one screen, not three round-trips). They
  remain **three distinct questions**, each `multiSelect: false`; batching the *call* is not
  merging the *lists*.
- **This call is SEPARATE from the intake gate's batch** (`Work type` / `Execution` /
  `Data safety`, `engage` step 0a) - that batch already ran earlier in this engagement, before the
  work was even classified as a review. Never carry `Execution` or `Data safety` into this call:
  by step 1b they are already answered and recorded, not still pending.
- **Headers:** Q1 `Depth` · Q2 `Performance` · Q3 `Fix-cycle` (locked, like the option wording).
- **Q1 (depth) is single-select** - exactly one depth; Quick ⊂ Deep ⊂ Audit.
- **Q2 (performance) is a SEPARATE question** (yes/no) - never merged into the depth list.
- Every depth produces the **same clean findings artifact** - keep the option descriptions
  parallel: each states *what it checks* and *when you'd use it*, nothing more.

**Q1 - "What depth of code review?"  (single-select):**

| Label | Description (use ~verbatim) |
|---|---|
| **Quick** | Fast check on the **changed code only** - bugs, security, language. Reports 🔴 Critical / 🟠 Warning. *Best for "am I OK to commit?"* |
| **Deep** | Everything in Quick **plus** architecture, 🟡 Medium findings, impact analysis and test/doc coverage - the whole change in context. *Best for "is this solid before a PR?"* |
| **Audit** | A Deep review in **audit-readiness mode** - keeps pre-existing issues in scope and checks the §4/§5 regulatory audit trail, for an audit-ready verdict. *Best for "would it survive an auditor?"* (A convenience preset; the fix→re-review loop is a **separate** choice below.) |
| **None** | Skip the code review (e.g. you only want the performance review). |

**Q2 - "Also run a performance & scalability review?"  (single-select):**

| Label | Description |
|---|---|
| **Yes** | Add a **static** scalability review vs target data volumes - findings 🧠 inferred (📄 coded for an explicit coded cost), with a total-impact summary. Measured profiling is a future opt-in. Runs alongside the chosen depth. |
| **No** | No performance review. |

**Q3 - "After the review, what should happen to the findings?"  (single-select) - applies to ANY depth, *including Quick*:**

| Label | Description |
|---|---|
| **Report only** | Surface the findings; change nothing. |
| **Apply fixes** | Fix the findings, then stop. |
| **Fix → re-review loop** | Fix, re-review, repeat until clean (no Criticals) or you call it. This is the loop "Audit" implies - now available to **Quick/Deep too**. |

**Security is already in every depth - never invent a "dedicated security pass" question
(2026-08-17 live report).** The security lens loads for all code at every depth (router
matrix); a session improvised an extra "also run a dedicated /security-audit alongside?
(Recommended)" question and planned a separate sequential pass, exactly the shape the
consolidation rule bans. If the user's request emphasises security, say the lens is included
at no extra pass, and offer the full `/security-audit` machinery (ASVS depth, threat model,
evaluator-optimizer loop) only as a priced alternative for a security-FOCUSED engagement -
never as a default-recommended add-on pass beside a deep review.

**Report-only staffs reviewers only (same live report: 5 agents planned for a report-only
deep review).** No `qa-engineer` (nothing is built, so there is nothing to test) and no
`compliance-reviewer` sign-off unless the depth is Audit or detection logic is in scope. The
right-sized report-only shape is the review pass(es) + the perf pass if chosen + Pip - state
that count at the gate.

Only **one** depth runs (Audit ⊃ Deep ⊃ Quick - no triple-passing). The fix-cycle (Q3) is
independent of depth, so e.g. *Quick + Fix→re-review loop* is valid. **If Q1 = None AND Q2 = No**
there is nothing to run - don't dead-end or invent work: say so and return to the outcome question
via the question tool ("no review selected - what would you like instead?"). For taking on legacy
code end-to-end (assess → fix → re-review → handover) use the heavier **`/remediate`**, not this
in-review loop. After the choice, the review skill asks the finer **scope** (dimensions · breadth ·
change-vs-audit mode) - type *then* scope, never needing a slash command.
