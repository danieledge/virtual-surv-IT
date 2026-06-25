# House rules — accumulated team knowledge

A **committed, shared** record of what the team learns over time: recurring typologies,
threshold rationales and tuning outcomes, venue quirks, effective lexicon patterns and
false-positive sources, recurring code-review and performance findings, and validation
standards.

> Why a file, not "agent memory": Claude Code subagents have **no** per-agent persistent
> memory (that was a misconception in an earlier version of this repo). The real, durable,
> auditable mechanism is a committed file like this one — advisory agents *recommend*
> additions and the PM (or a build agent) commits them, so the knowledge is visible,
> reviewable and travels with the repo.

## Detection typologies & thresholds
- _(e.g. 2026-06-18 — spoofing: 5× median size + ≤2s lifetime calibrated on synthetic set.)_

## Tuning outcomes & false-positive sources
-

## Venue / market quirks
-

## Comms lexicon patterns
-

## Surveillance evidence base (DA/BA expansion)
- 2026-06-25 — **AML/TM tuning is fully evidenced; trade & comms are only partially.** The DA/BA
  expansion (tuning-analyst, BA workflows, coverage/trade/comms templates) rests on two deep-
  research passes. The AML/TM pass verified cleanly (ATL/BTL, segmentation, SR 11-7 validation).
  The trade/comms pass was **cut short by a session limit** — only **3** claims fully verified:
  (1) **FCA Market Watch 79** — surveillance testing is **four-component** (parameter calibration ·
  model logic · model code · **data** comprehensiveness/accuracy), not calibration alone;
  (2) **MW79** — failures often come from **data-ingestion gaps** (a dead news feed → an insider-
  dealing scenario fired zero alerts for 3+ years); (3) **MiFID II RTS 25** clock-sync / timestamp
  granularity. The MAR / MiFID / STOR / SEC 17a-4 / comms-recordkeeping detail in the trade/comms
  templates is **foundational standard-practice, not freshly machine-verified** — re-run the
  trade/comms research pass to confirm specifics before relying on them in a real engagement.

## Execution safety
- 2026-06-24 — **Reviewing code is static by default; executing it is gated.** Running tests,
  the script, or a profiler *executes* the code (PowerShell `Measure-Command`, `cProfile`/
  `py-spy`, `JMH`, `hyperfine`, `pytest`/`Pester`). The `guard-code-execution.py` hook blocks
  these unless authorised by the `.claude/.exec-consent` marker (written on user "yes") or the
  human-set `CST_ALLOW_EXEC=1`. Static-by-default + a prominent consent disclaimer + the hook;
  the user is responsible for the safety of code they hand over (CLAUDE.md §7).

## Recurring code-review findings
- 2026-06-20 — **String-matching Bash commands in PreToolUse hooks is advisory only.**
  Arbitrary shell trivially bypasses lexical checks (`cd data/raw && cat`, indirection,
  obfuscation). The real raw-data boundary is the `permissions.deny` list in
  `.claude/settings.json`, `data/raw/` in `.gitignore`, and masking-at-source via
  `scripts/ingest.py`. Any new file-reading tool must be added to the guard matcher.
- 2026-06-20 — **Lexical/regex redaction is best-effort and order-sensitive.** Every new PII
  pattern needs an ordering rationale *and* an overlap test (date vs phone vs account); never
  rely on it as the sole control — free-text comms needs NER before real data.

## Recurring performance hotspots
-

## Model validation standards & failure modes
-
