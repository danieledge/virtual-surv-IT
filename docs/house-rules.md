# House rules - accumulated team knowledge

A **committed, shared** record of what the team learns over time: recurring typologies,
threshold rationales and tuning outcomes, venue quirks, effective lexicon patterns and
false-positive sources, recurring code-review and performance findings, and validation
standards.

> Why a file, not "agent memory": Claude Code subagents have **no** per-agent persistent
> memory (that was a misconception in an earlier version of this repo). The real, durable,
> auditable mechanism is a committed file like this one - advisory agents *recommend*
> additions and the PM (or a build agent) commits them, so the knowledge is visible,
> reviewable and travels with the repo.

## Detection typologies & thresholds
- _(e.g. 2026-06-18 - spoofing: 5× median size + ≤2s lifetime calibrated on synthetic set.)_
- 2026-06-27 - **Wash trade / self-match** (from the build demo, `trade-surveillance-sme`): the
  beneficial-owner (UBO) link - *not* legal entity - is the correct entry point (accounts under
  common control). Off-market price must be a **necessary condition**, not just price convergence
  within a tolerance, and that tolerance must be validated against the **prevailing spread at time
  of trade**, not a fixed basis-point figure. Obligation: MAR Art 12(1)(a) (jurisdiction-portable).

## Tuning outcomes & false-positive sources
- 2026-06-27 - **Wash-trade FP drivers** (build demo, `trade-surveillance-sme`): (1) legitimate
  two-way business between **affiliated funds** under one manager - the highest-volume FP source;
  scope the UBO graph as a *surveillance perimeter*, not just "same UBO" (too wide floods alerts,
  too narrow misses abuse). (2) **Market-making / riskless-principal** activity - exempt via
  designated-MM status per venue/jurisdiction (RTS 3 / FINRA 5320). (3) Coincident independent
  orders at a liquid price - mitigated by the off-market-price necessary condition above.
- 2026-06-27 - **Implementation rule** (build demo, `rules-developer`): when a condition is
  *necessary* (e.g. off-market price), implement it as an **early-continue that fully terminates the
  pair's evaluation**, not a weighted score - otherwise a strong UBO/volume signal can compensate
  for a missing price condition. That compensation is a common FP source and a frequent audit finding.
- 2026-06-27 - **Alert-record rule** (build demo, `compliance-reviewer`): every alert dataclass must
  carry the **obligation citation** and the **keystone linkage ID** (here, the UBO ID) as *fields* -
  not only in a free-text `reason` - so the alert record *alone* satisfies the alert→obligation
  trace, which is the one place an investigator and a regulator actually look.

## Venue / market quirks
-

## Data quality
- 2026-06-27 - **UBO-graph freshness is the wash-trade keystone** (build demo, `trade-surveillance-sme`):
  stale/incomplete beneficial-owner linkage causes both false negatives (missed abuse) and false
  positives (linking accounts no longer under common control), and is the most common reason a
  wash-trade scenario fails audit. Require a defined refresh cadence + a data-quality gate before the
  scenario runs, and include the BO source + its as-of date in the investigator evidence pack.

## Comms lexicon patterns
-

## Surveillance evidence base (DA/BA expansion)
- 2026-06-25 - **Evidence state by area (three deep-research passes).**
  - ✅ **AML/TM tuning - VERIFIED**: ATL/BTL, risk-based segmentation, SR 11-7 model validation,
    FFIEC BSA/AML.
  - ✅ **FCA Market Watch 79 - VERIFIED**: surveillance testing is **four-component** (parameter
    calibration · model logic · model code · **data** comprehensiveness/accuracy), not calibration
    alone; failures often from **data-ingestion gaps** (a dead news feed → an insider-dealing
    scenario fired zero alerts for 3+ years). Drives `/assess-coverage`.
  - ✅ **Trade / market-abuse regulatory spine - VERIFIED (primary sources: EUR-Lex,
    legislation.gov.uk, ESMA)**: **MAR Art 16(2)** STOR obligation on PPAETs (statute says
    "notify"; "STOR" is RTS terminology); **CDR (EU) 2016/957** (Art 3 analyse every order
    placed/modified/cancelled/rejected + alerts; Art 6 file "without delay" on **reasonable
    suspicion** of actual/attempted abuse; Art 7 + Annex content; 5-yr retention of reasons to
    file *or not*); **RTS 24 (CDR 2017/580**, MiFIR Art 25) order-book records - Field 21 lifecycle
    events (NEWO/CAME/FILL…) are the spoofing/layering substrate; **RTS 22 (CDR 2017/590**, MiFIR
    Art 26) is the *separate* T+1 transaction report; **RTS 25** clock-sync. Folded into
    `trade-scenario-design.md`.
  - ✅ **Comms-surveillance regulatory spine - VERIFIED (primary sources: ESMA, EUR-Lex,
    legislation.gov.uk, SEC, FINRA, CFTC)**: **MiFID II Art 16(7)** (record own-account + client-
    order comms, incl. *intended* transactions even if none results; **5yr / up-to-7yr** retention)
    detailed by **CDR (EU) 2017/565 Art 76** (written recording policy incl. internal comms; UK →
    FCA **SYSC 10A**); **Exchange Act 17a-4(b)(4)** (business comms ≥3yr, first 2 readily accessible)
    + **FINRA 4511(b)** (6yr default); **WORM or the Oct-2022 audit-trail alternative**; the
    **off-channel sweep** (SEC Sep'22 16 firms >$1.1bn, Aug'23 11/$289m, Sep'23 10/$79m; CFTC Aug'23
    4/$260m) - core failing = failure to **preserve/supervise** business comms on personal-device
    channels. Folded into `comms-surveillance-policy.md` + `lexicon-spec.md`.
  - 🟡 **STILL UNVERIFIED - treat as foundational**: comms-surveillance **practice** (lexicon
    design/tuning, NLP risk-scoring, voice transcription, FP reduction) and **coverage-assurance
    methodology**; per-scenario **detection-tuning practice** (spoofing/layering approaches; trade-
    vs-AML tuning); the **DA-vs-BA boundary** in trade/comms. Run a dedicated pass before relying on
    these in a real engagement.

## Execution safety
- 2026-06-25 - **Hooks are declared in TWO files by design - keep them in sync.** The PreToolUse
  guards live in both `hooks/hooks.json` (plugin-install mode) and `.claude/settings.json`
  (repo-as-project mode); JSON can't carry a comment, so this note + `tests/test_hooks_in_sync.py`
  are the guard against drift. Edit one → edit the other identically.
- 2026-06-24 - **Reviewing code is static by default; executing it is gated.** Running tests,
  the script, or a profiler *executes* the code (PowerShell `Measure-Command`, `cProfile`/
  `py-spy`, `JMH`, `hyperfine`, `pytest`/`Pester`). The `guard-code-execution.py` hook blocks
  these unless authorised by the `.claude/.exec-consent` marker (written on user "yes") or the
  human-set `CST_ALLOW_EXEC=1`. Static-by-default + a prominent consent disclaimer + the hook;
  the user is responsible for the safety of code they hand over (CLAUDE.md §7).

## Recurring code-review findings
- 2026-06-20 - **String-matching Bash commands in PreToolUse hooks is advisory only.**
  Arbitrary shell trivially bypasses lexical checks (`cd data/raw && cat`, indirection,
  obfuscation). The real raw-data boundary is the `permissions.deny` list in
  `.claude/settings.json`, `data/raw/` in `.gitignore`, and masking-at-source via
  `scripts/ingest.py`. Any new file-reading tool must be added to the guard matcher.
- 2026-06-20 - **Lexical/regex redaction is best-effort and order-sensitive.** Every new PII
  pattern needs an ordering rationale *and* an overlap test (date vs phone vs account); never
  rely on it as the sole control - free-text comms needs NER before real data.

## Recurring performance hotspots
-

## Model validation standards & failure modes
-
