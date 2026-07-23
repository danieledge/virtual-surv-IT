# Why this case exists

Derived from a live defect (2026-07-23, user-reported): the codebase map a review engagement
produced "wasn't a code map - it was a summary of some of the things done in recent testing".
The map is meant to be the working project's **durable memory of the code** (ADR-003), read at
the open of the *next* engagement. For a review/audit the whole output is findings, so the
model pours findings/activity into the map entries - which then go stale the moment the
findings are fixed and are useless as a map.

The fix is prompt/template-side: template §2 now draws the durable-fact-vs-activity line with a
✅/❌ contrast, /engage step 6a and the operating-guide memory rule repeat it, and reviews/audits
get an explicit steer to capture *the architecture learned by reading the code*, not a findings
recap. This case pins the behaviour: closing a review, the map entries describe how the code is
built (ARCH-1) and the response keeps engagement activity out of them (RULE-1).

Scoring notes: ARCH-1 accepts any durable description of the detector's structure (per-customer
daily aggregation, the hardcoded threshold as a *fact*, single-file, the CSV read) with or
without line pointers. RULE-1 accepts any statement that activity/findings go to the history
row / review artifact and the map holds durable facts. FP-1 traps only the affirmative failure
- a map entry written as a finding recap ("🟠 open", "reported, left open", "recap of the
findings") - phrasings a correct answer that routes findings OUT of the map is unlikely to emit
even while explaining the rule (the known keyword-matching limitation; see
citation-flag-unverified/notes.md for the same trade-off). A response that simply omits the
separation fails via the RULE-1 must-find, which is the live defect's actual signature.
