# House rules - the team's general, cross-project conventions

The durable **engineering, review, process and safety** conventions the team follows on **every**
engagement. This file ships with the plugin and is **general by design**.

> **This is NOT a project memory.** The plugin is typically installed user-wide and used across
> many independent projects, so it must hold **no project-specific knowledge**. Anything specific
> to a given engagement - a typology nuance, a threshold rationale, an FP driver, a venue quirk, a
> calibration choice - lives in **that project's own memory** (its `CLAUDE.md`), **not here**
> (CLAUDE.md §6). Keep this file to patterns that hold regardless of the project. Advisory agents
> *recommend* additions; the PM commits them.

## Engineering & review patterns
- **A *necessary* condition is an early-continue, not a weighted score.** When a condition must
  hold (e.g. a price/threshold gate), implement it as a hard gate that terminates evaluation - never
  a score that a strong signal elsewhere can compensate for. That compensation is a common
  false-positive source and a frequent audit finding.
- **Carry the obligation + the keystone linkage as alert *fields*, not just free-text.** The alert
  record *alone* must satisfy the alert→logic→obligation trace - that's the one place an investigator
  and a regulator actually look. Don't bury it in a `reason` string.
- **Never let an unresolved mapping masquerade as finalised.** If a regulatory mapping or scope is
  still an open decision, carry an explicit status (e.g. `PROVISIONAL`) or reference it via an
  RTM/decision-log id - don't embed a lone citation literal that *looks* final.

## Reporting & audit conventions
- **Disposition every open question before sign-off (don't let them dangle).** When a spec/BRD/review
  raises open questions for a downstream owner, the owner must **formally disposition each one**
  (✅ answered / ⏭️ needs deployment input / 🔴 open-decision-required) in a tracked decision log, and
  the Definition of Done checks it. A question *partly touched in passing* is **not** dispositioned.
- **Two-snapshot reporting (as-found vs as-delivered) - don't retro-edit evidence.** When a
  fix→re-review loop resolves findings, **preserve the as-found record** (the QA handover / review
  report - the audit trail of *what was caught*) and record the **resolved** state in the delivery
  report's disposition. Never rewrite the source evidence to "look passed". (Codified in
  `docs/templates/qa-handover.md` + `docs/templates/delivery-report.md`.)
- **Two kinds of "open" - keep them distinct.** 🔴 *unresolved defects* (a real problem; the verdict
  cannot be ✅) vs ⏭️ *deferred deploy-gates* (calibrate on real data, scale-test, human sign-off)
  that are **correctly** open and out of scope for the current stage. A report that honestly shows
  deploy-gates as open is *good*; one that hides them to look "all green" is the failure. The verdict
  must match the disposition.

## Execution safety
- **Hooks are declared in TWO files by design - keep them in sync.** The PreToolUse guards live in
  both `hooks/hooks.json` (plugin-install mode) and `.claude/settings.json` (repo-as-project mode);
  JSON can't carry a comment, so this note + `tests/test_hooks_in_sync.py` are the guard against
  drift. Edit one → edit the other identically. (The standard `hooks/hooks.json` is **auto-loaded**;
  it must *not* be re-declared in `plugin.json` - that double-loads it. See `docs/adr/ADR-002`.)
- **Reviewing code is static by default; executing it is gated.** Running tests, the script, or a
  profiler *executes* the code. `guard-code-execution.py` blocks these unless authorised by the
  `.claude/.exec-consent` marker or the human-set `CST_ALLOW_EXEC=1`. **The marker is human-only**
  (since ADR-002 rec 5 / `guard-consent-writes.py` the model cannot write it - the user creates it;
  always quote the command with the **absolute project path**, e.g.
  `! touch /path/to/project/.claude/.exec-consent`, so a terminal in another directory can't
  create it in the wrong place); the intake "yes" is *intent*, the marker is the *consent*.
  The user is responsible for the safety of code they hand over (CLAUDE.md §7). Threat model:
  `ADR-002`.

## Recurring code-review findings
- **String-matching Bash commands in PreToolUse hooks is advisory only.** Arbitrary shell trivially
  bypasses lexical checks (indirection, subshells, `eval`, `base64|sh`). The real raw-data boundary
  is the `permissions.deny` list in `.claude/settings.json`, `data/raw/` in `.gitignore`, and
  masking-at-source via `scripts/ingest.py`. Any new file-reading tool must be added to the guard
  matcher. (Full bypass enumeration + hardening backlog: `docs/adr/ADR-002`.)
- **Lexical/regex redaction is best-effort and order-sensitive.** Every new PII pattern needs an
  ordering rationale *and* an overlap test (date vs phone vs account); never rely on it as the sole
  control - free-text comms needs NER before real data. The masking engine is **basic** by design.

## Domain evidence base (general reference, not project memory)
Provenance for the regulatory content the team ships. This is **domain-general** (it applies to any
surveillance engagement), so it lives here; per-engagement findings do not.
- ✅ **AML/TM tuning - VERIFIED**: ATL/BTL, risk-based segmentation, SR 11-7 model validation, FFIEC
  BSA/AML.
- ✅ **FCA Market Watch 79 - VERIFIED**: surveillance testing is **four-component** (parameter
  calibration · model logic · model code · **data** comprehensiveness/accuracy), not calibration
  alone; failures often from **data-ingestion gaps**. Drives `/assess-coverage`.
- ✅ **Trade / market-abuse regulatory spine - VERIFIED** (EUR-Lex, legislation.gov.uk, ESMA): MAR
  Art 16(2) STOR obligation; CDR (EU) 2016/957; RTS 24 (CDR 2017/580) order-book records; RTS 22
  (CDR 2017/590) transaction reports; RTS 25 clock-sync. Folded into `trade-scenario-design.md`.
- ✅ **Comms-surveillance regulatory spine - VERIFIED** (ESMA, EUR-Lex, SEC, FINRA, CFTC): MiFID II
  Art 16(7) + CDR (EU) 2017/565 Art 76 (UK SYSC 10A); Exchange Act 17a-4(b)(4) + FINRA 4511(b); WORM
  / Oct-2022 audit-trail alternative; the off-channel sweep. Folded into
  `comms-surveillance-policy.md` + `lexicon-spec.md`.
- 🟡 **STILL UNVERIFIED - treat as foundational**: comms-surveillance **practice** (lexicon design,
  NLP risk-scoring, voice transcription, FP reduction) and **coverage-assurance methodology**;
  per-scenario detection-tuning practice; the DA-vs-BA boundary in trade/comms. Run a dedicated pass
  before relying on these in a real engagement.
