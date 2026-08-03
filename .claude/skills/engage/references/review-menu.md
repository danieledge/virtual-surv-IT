# Review-type menu - LOCKED construction (read when the work is a review)

> Loaded just-in-time by `engage` step 1b. Use **exactly** these questions, options and
> descriptions - do not improvise, merge or reword (a loose version once offered "Quick **and**
> Deep" as a multi-select - illogical, Deep already includes Quick). `scripts/locked_menu_guard.py`
> (audit finding #7, 2026-07-30) mechanically blocks that exact class of drift before the
> question reaches the user - don't rely on it instead of following this file.

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

Only **one** depth runs (Audit ⊃ Deep ⊃ Quick - no triple-passing). The fix-cycle (Q3) is
independent of depth, so e.g. *Quick + Fix→re-review loop* is valid. **If Q1 = None AND Q2 = No**
there is nothing to run - don't dead-end or invent work: say so and return to the outcome question
via the question tool ("no review selected - what would you like instead?"). For taking on legacy
code end-to-end (assess → fix → re-review → handover) use the heavier **`/remediate`**, not this
in-review loop. After the choice, the review skill asks the finer **scope** (dimensions · breadth ·
change-vs-audit mode) - type *then* scope, never needing a slash command.
