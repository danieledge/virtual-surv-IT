---
name: False Positive Filtering Rules
---

> **Source & licence.** Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) —
> <https://github.com/turingmindai/turingmind-code-review>. The filtering rules and confidence
> scoring are theirs; the regulated exceptions (§4/§5), the evidence-basis requirement and the
> 🔵 style-&-form lane are ours. See `THIRD-PARTY-LICENSES.md`. Full scoring table in
> `docs/code-review-method.md`.

Decide what's worth reporting. High signal: surface what a senior engineer **and an auditor**
would flag, filter the noise, and **always show what was filtered** so the review is trustworthy.

## Always filter out (report only as counts)

1. **Pre-existing issues** — in lines the diff didn't touch (*change-review mode only*; in
   **audit mode** pre-existing issues are in scope). Use `git blame` if unsure.
2. **Linter/formatter territory** — formatting, import order, unused vars (ruff/black/
   PSScriptAnalyzer/shfmt handle these). Run the tools; don't hand-report their job.
3. **Pedantic nitpicks** — "could be nicer" with no behavioural impact and no senior-engineer
   value. (If it *does* carry senior-engineer value, it's not a nitpick — it's 🔵 style & form.)
4. **Silenced issues** — explicit ignore comments (`# noqa`, `// nolint`, `@SuppressWarnings`) —
   *unless* the silenced issue is a §5 data-safety violation (see exceptions).
5. **Intentional changes** — deliberate functionality or style matching existing patterns.
6. **Style not in CLAUDE.md** — preferences not actually required *and* not worth a 🔵 note.

## Never filter (regulated exceptions)

Even if pre-existing, silenced, or "minor", **always report**:
- Secrets / credentials / connection strings in code, tests, logs or fixtures.
- Real PII/MNPI or raw records used as data (CLAUDE.md §5).
- An undocumented detection threshold, or a broken alert→logic→obligation trace (§4).

A secret doesn't become acceptable because it predates the diff — these are regulatory
findings, not style.

## 🔵 Style & form is NOT a filter

Don't bury meaningful style/form/idiom/documentation suggestions in the filtered counts. They
are **reported** in their own non-blocking lane (`docs/review/output-format.md`) as
"consider in future." Filtered = the linter's job; 🔵 = a senior engineer's judgement call the
developer should see, just not be blocked by.

## Evidence basis (state it, don't filter for it)

A real-but-unverified finding is **not** filtered for lacking a measurement — it is reported
and **labelled 🧠 inferred**, with the measurement that would confirm it. Only present a finding
as 📊 measured when you observed it directly (profiler, benchmark, test failure, or an explicit
value in the code). Never upgrade an inference to a certainty to make it "report-worthy."

## Confidence score & thresholds

See `docs/code-review-method.md` for the full 0–100 rubric (the scoring criteria, the §4/§5
weighting, and the report/filter thresholds: 🔴 95–100, 🟠 80–94, 🟡 70–79 [deep/audit],
< 70 filtered). The orchestrator (**Morgan**) independently re-scores and may **downgrade** a
lens's finding before it reaches the user — confidence is the team's, not a single lens's.
