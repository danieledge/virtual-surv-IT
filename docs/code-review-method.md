# Code review method — confidence scoring, filtering & transparency

How `code-reviewer` decides what's worth reporting. The goal is high signal: surface what a
senior engineer (and an auditor) would genuinely flag, filter the noise, and **always show
what was filtered** so the review is trustworthy and defensible.

> Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) —
> <https://github.com/turingmindai/turingmind-code-review>. The confidence-scoring and
> filter-transparency approach is theirs; the regulated-domain adaptations (audit mode,
> data-safety/traceability weighting) are ours.

## Two modes

| Mode | When | Pre-existing issues |
|---|---|---|
| **Change review** | reviewing a diff / PR (`/new-scenario`, a code change) | filtered out — only flag what the change introduces |
| **Audit review** | reviewing existing code for audit-readiness (`/audit-review`) | **in scope** — the existing code *is* the subject; never silently drop them |

The scoring below is identical in both modes except for the "new vs pre-existing" criterion,
which only applies in change review.

## Confidence score (0–100)

Start at 50 and adjust:

| Criterion | Adjustment |
|---|---|
| New in this diff *(change review only)* | +20 |
| Pre-existing, outside the diff *(change review only)* | −50 |
| Would cause a failure, **missed alert, or false alert** | definitely +30 · likely +20 · possibly +10 |
| Affects **auditability / regulatory traceability / data safety** (CLAUDE.md §4–§5) | +30 |
| Required by CLAUDE.md or a cited standard (OWASP ASVS / CWE / SEI CERT) | +20 |
| Would a senior engineer flag it in review? | yes +20 · maybe +10 · no −20 |
| Silenced by an ignore comment (`# noqa`, `// nolint`, `@SuppressWarnings`, …) | −50 |

## Report / filter thresholds

| Score | Severity | Change review | Audit review |
|---|---|---|---|
| 95–100 | 🔴 Critical | report | report |
| 80–94 | 🟠 Warning | report | report |
| 70–79 | 🟡 Medium | filter | report |
| < 70 | — | filter | filter |

## Always filter out (noise)

1. **Linter/formatter territory** — formatting, import order, unused vars (ruff/black/
   prettier handle these). Run the tools; don't hand-report their job.
2. **Pedantic nitpicks** — "could be nicer" with no behavioural impact.
3. **Silenced issues** — explicit ignore comments (unless the silenced issue is a §5
   data-safety violation; see exception).
4. **Intentional changes** — deliberate functionality or style matching existing patterns.
5. **Style not in CLAUDE.md** — preferences not actually required.

## Never filter (regulated exceptions)

Even if pre-existing, silenced, or "minor", **always report**:
- Secrets / credentials / connection strings in code, tests, logs or fixtures.
- Real PII/MNPI or raw records used as data (CLAUDE.md §5).
- An undocumented detection threshold, or a broken alert→logic→obligation trace (§4).

These are regulatory findings, not style — a secret doesn't become acceptable because it
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
