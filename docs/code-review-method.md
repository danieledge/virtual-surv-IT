# Code review method - confidence scoring, filtering & transparency

How `code-reviewer` decides what's worth reporting. The goal is high signal: surface what a
senior engineer (and an auditor) would flag, filter the noise, and **always show
what was filtered** so the review is trustworthy and defensible.

> Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) -
> <https://github.com/turingmindai/turingmind-code-review>. The confidence-scoring and
> filter-transparency approach is theirs; the regulated-domain adaptations (audit mode,
> data-safety/traceability weighting) are ours.

## Two modes

| Mode | When | Pre-existing issues |
|---|---|---|
| **Change review** | reviewing a diff / PR (pull request) (`/new-scenario`, a code change) | filtered out - only flag what the change introduces |
| **Audit review** | reviewing existing code for audit-readiness (`/audit-review`) | **in scope** - the existing code *is* the subject; never silently drop them |

The scoring below is identical in both modes except for the "new vs pre-existing" criterion,
which only applies in change review.

## Confidence score (0-100)

Start at 50 and adjust:

| Criterion | Adjustment |
|---|---|
| New in this diff *(change review only)* | +20 |
| Pre-existing, outside the diff *(change review only)* | −50 |
| Would cause a failure, **missed alert, or false alert** | definitely +30 · likely +20 · possibly +10 |
| Affects **auditability / regulatory traceability / data safety** (CLAUDE.md §4-§5) | +30 |
| Required by CLAUDE.md or a cited standard (OWASP ASVS / CWE / SEI CERT) | +20 |
| Would a senior engineer flag it in review? | yes +20 · maybe +10 · no −20 |
| Silenced by an ignore comment (`# noqa`, `// nolint`, `@SuppressWarnings`, …) | −50 |

## Report / filter thresholds

| Score | Severity | Change review | Audit review |
|---|---|---|---|
| 95-100 | 🔴 Critical | report | report |
| 80-94 | 🟠 Warning | report | report |
| 70-79 | 🟡 Medium | filter | report |
| < 70 | - | filter | filter |

> **Audit the filter, not just the report.** A real issue scored *just under* the threshold is a
> **false negative** - the costliest miss in a regulated review, and the one mechanical scoring can
> make silently. So the PM (Morgan) samples the **filtered / below-threshold** set as well as the
> reported findings (operating guide §Challenge): a wrongly-filtered finding is **promoted**, not
> left in the counts. Regulated exceptions (below) are never filtered in the first place.

## Evidence basis - measured vs inferred (state it for every claim)

A developer will (rightly) challenge a finding that *sounds* certain but was only reasoned.
So **every finding states how we know it** - never let an inference read as a measurement:

| Basis | Means | How to cite it |
|---|---|---|
| **Measured** 📊 | Observed directly by **running** something - a profiler run, a benchmark, an analyser result, a test failure. | Quote the number: *"cProfile: 4.2s in `join()` @ 100k rows"* or *"bandit B608 at `q.py:30`"*. |
| **Coded** 📄 | An **explicit literal read from the source** (a `sleep(5)`, a hard timeout, `LIMIT 100`) - a hard fact, but nothing ran, so it is **not** 📊 measured. | Quote the line: *"`time.sleep(5)` at `worker.py:88` → 5s fixed delay per call"*. |
| **Inferred** 🧠 | Reasoned from the code without executing it - complexity from structure, "this won't scale", likely-null. | Say so and give the reasoning **and the measurement that would confirm it**: *"Inferred O(n²) from the nested scan at `match.py:40`; not benchmarked - confirm with the stack's benchmark harness at 100k rows."* |

Rules:
- A performance or behaviour claim with **no number and no executed evidence is Inferred** - label it, never present it as fact.
- Prefer to **measure** before asserting impact; if you couldn't (tool missing, no rig), say that explicitly in Tooling coverage rather than upgrading a guess to a certainty.
- Distinguish **what the code says** (explicit: a coded pause, a fixed batch size, a declared timeout) from **what we derive** (the emergent cost). Both are legitimate; conflating them is not.

## Severity lanes (what goes where)

Five lanes, kept distinct so the signal stays clean and nothing important hides among nits:

| Lane | What | Blocks? |
|---|---|---|
| 🔴 **Critical** | must fix before merge (failure, missed/false alert, §4/§5 breach) | yes |
| 🟠 **Warning** | should fix | yes (for an audit verdict) |
| 🟡 **Medium** | worth fixing (deep/audit only) | no |
| 🔵 **Style & form** | meaningful idiom / readability / naming / structure / documentation a senior dev would suggest - **non-blocking, "for future consideration"** | no |
| 🔇 **Filtered** | noise the tools own (formatting, import order) or out-of-scope - *shown as counts, not findings* | no |

**🔵 Style & form is not 🔇 filtered.** Filtered = the linter/formatter's job, reported only as a count. Style & form = judgement-level suggestions worth a developer's attention later (clearer naming, better decomposition, a missing docstring, a more idiomatic construct). Surface them in their own section, never inflate them into Warnings, and never let them affect the verdict.

## Console scoreboard & artifact

The console gets a **clean traffic-light scoreboard**; full findings go to the artifact. The
exact scoreboard shape and artifact sections are defined once in **`docs/review/output-format.md`**
- that file is canonical for *what the user sees*; this file is canonical for *how findings are
scored and filtered*. Don't restate the format here.

## Model tiering (wired)

Scoring, filtering and context detection are **rote, mechanical** work, so they run on the cheap
tier: the review skills delegate them to the **`review-scorer` (haiku)** agent. The dimension
lenses run **within `code-reviewer` today** (running them as separate **sonnet** sub-agents is an
optional next step); only `code-reviewer`'s judgement on findings + **Morgan's** challenge pass +
the §4/§5 regulated calls pay **opus** (CLAUDE.md §8). See `docs/review/agent-router.md`.

## Always filter out (noise)

> `docs/review/false-positive-rules.md` no longer restates these rules - it summarises the
> regulated exceptions and the 🔵 style-vs-filter distinction and points back here as canonical,
> so there is nothing to keep in sync; this file leads on scoring.

1. **Linter/formatter territory** - formatting, import order, unused vars (ruff/black/
   prettier handle these). Run the tools; don't hand-report their job.
2. **Pedantic nitpicks** - "could be nicer" with no behavioural impact.
3. **Silenced issues** - explicit ignore comments (unless the silenced issue is a §5
   data-safety violation; see exception).
4. **Intentional changes** - deliberate functionality or style matching existing patterns.
5. **Style not in CLAUDE.md** - preferences not actually required.
6. **Documented, intentional bounds** - a constraint that carries a rationale (an explaining
   comment, a named constant like `max_col=EXPECTED_COLUMNS`, or a documented threshold with a
   tuning date) is correct-by-design; don't flag it as a defect. Mirror of §4: an *undocumented*
   threshold is a finding, a *documented* one is not. Flag it only if the rationale is demonstrably
   wrong or the value contradicts its stated intent.

## Never filter (regulated exceptions)

Even if pre-existing, silenced, or "minor", **always report**:
- Secrets / credentials / connection strings in code, tests, logs or fixtures.
- Real PII/MNPI or raw records used as data (CLAUDE.md §5).
- An undocumented detection threshold, or a broken alert→logic→obligation trace (§4).

These are regulatory findings, not style - a secret doesn't become acceptable because it
predates the diff.

## Transparency (always)

Every review reports the counts and reasons, so nothing looks hidden:

```
Found N issues · Reported R · Filtered F
```

| Filtered reason | Count |
|---|---|
| Pre-existing (not in diff) | … |
| Below confidence threshold | … |
| Linter/formatter territory | … |
| Silenced by comment | … |

This counts table and the per-finding confidence score go into the Review Report
(`docs/templates/review-report.md`).
