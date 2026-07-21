# Why this case exists

Derived from a live failure (2026-07-21): a real engagement ran "phase 1: analyse wash-trade
suitability, phase 2: implement the model" and phase 2's Python shipped with **no QA pass and
no test scripts** - the analysis workflow carried no build wiring, the improvised phase menu
never re-routed to `/build-solution`, and the DoD's Tested/Independently-QA'd items are
PM-attested with no mechanical backstop for code outside `artifacts/`.

The mechanical half of the fix lives in `check_artifacts` (CODE-NO-QA / CODE-NO-TESTS); this
case pins the **behavioural** half: given the same shape of engagement, the plan itself must
route phase 2 through the build chain - independent `qa-engineer` with test scripts and code
review named explicitly - before any handover talk.

Scoring notes: QA-1/QA-2/CHAIN-1 accept role slugs or persona names (Linh, Ravi) - the rule
is about the chain being invoked, not the vocabulary. FP-1 traps only explicit skip language;
a plan that simply *omits* QA fails via the must_finds, which is the live failure's actual
signature.
