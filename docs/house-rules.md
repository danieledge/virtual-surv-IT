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
