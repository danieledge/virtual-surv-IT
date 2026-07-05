# Code & Compliance Review Report - <TITLE>

> Output of a **deep or audit review** (`/deep-review`, `/audit-review`, or `code-reviewer`
> directly). Produced by `code-reviewer` (engineering quality & security) and, for audit,
> `compliance-reviewer` (auditability & regulatory trail). Authored in `.md`, rendered to `.html`.
>
> **Format source of truth:** `docs/review/output-format.md` - the console scoreboard, the
> severity lanes (incl. style & form), the evidence basis (📊/🧠) and the diff-fix shape. This
> template is that format laid out as a standalone file; keep them consistent.

> **Document control** · ID `REV-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Scope** | <files / commit range reviewed> |
| **Languages** | <Python / TypeScript-JS / Scala / Java / PowerShell / Bash / SQL> |
| **Date** | <YYYY-MM-DD> |
| **Reviewer / independence** | `code-reviewer` (AI, independent of builder); `compliance-reviewer` (AI, independent of builder) - no involvement in the code under review |
| **Verdict** | audit-ready / conditional / not yet |

## 1. Summary
Plain-language verdict: would this stand up to audit and regulatory scrutiny, and what (if
anything) must change first.

**Found N · Reported R · Filtered F** (depth: quick / deep · mode: change / audit)

## 2. Findings
Confidence score per `docs/code-review-method.md` (Critical 95-100, Warning 80-94, Medium
70-79 - deep only). **Each finding carries a concrete `diff`-style fix + "why it works"**, a
**Basis** tag (📊 measured / 🧠 inferred), and a **Status** (`docs/review/output-format.md`):
Open · Fixed · Accepted · Deferred · **Open (needs human review)** when there's no
straightforward/safe fix. If there are none: *No significant issues found* (still show the
filtered counts below).

**Disposition summary:** _N_ fixed · _N_ open · _N_ accepted · _N_ deferred - so it's
never ambiguous what was actioned. A not-yet verdict must list the Open items explicitly.

### Critical (must fix)
| # | File:line | Issue | Conf. | Basis | Standard / rule | Status |
|---|-----------|-------|-------|-------|-----------------|--------|
| 1 | `path:42` | ... | 97 | 📊 measured / 🧠 inferred | CWE-89 / OWASP ASVS V5 | Fixed (commit abc123) / Open |

> **Fix for #1:**
> ```diff
> - vulnerable_line
> + fixed_line
> ```
> *Why this works:* ...

### Warnings (should fix)
| # | File:line | Issue | Conf. | Basis | Standard / rule | Recommended fix |
|---|-----------|-------|-------|-------|-----------------|-----------------|

### Medium *(deep review only)*
| # | File:line | Issue | Conf. | Basis | Standard / rule | Recommended fix |
|---|-----------|-------|-------|-------|-----------------|-----------------|

### Filtered (transparency - show what was not reported)
| Reason | Count |
|--------|-------|
| Pre-existing (not in diff) | |
| Below confidence threshold | |
| Linter/formatter territory | |
| Silenced by comment | |

## 3. Audit & regulatory checks
- Auditability: alert -> logic -> obligation traceable? (RTM present/complete?)
- Thresholds documented with rationale + date (§4)?
- Data handling: no PII/MNPI/secrets in code/tests/logs; synthetic/masked only (§5)?
- Test coverage: true-positive and false-positive cases present?
- Change control: reviewed and documented before merge?

## 4. Tooling coverage
| Analyser | Ran? | Notes |
|----------|------|-------|
| ruff / mypy / bandit | | |
| ShellCheck / PSScriptAnalyzer / SpotBugs / ... | | |
| Semgrep / gitleaks | | |

State explicitly which analysers were unavailable - nothing silently skipped.

## 5. Architectural notes *(deep review only)*
- Pattern consistency: ...
- Coupling & cohesion: ...
- Test coverage: ...
- Dependencies: ...

## 6. Impact analysis *(deep review only)*
- **Affected files / modules:** ...
- **Blast radius:** ... (what else could this change break?)
- **Breaking changes:** ...

<!-- Section 7. The heading below is canonical and mechanically checked by the review skills
     (/deep-review, /audit-review) - keep it verbatim: no number, no extra annotation. -->
## 🔵 Developer guidance - improving future code
*(Always include, even on a clean pass.)*
Constructive, non-blocking guidance on the **original coding style overall** and how the author
could improve in **future** work - patterns, structure, naming, testing/documentation habits.
2-4 short points. If the code is strong, say so and name what's done well. The developer should
always leave with something to learn, not just a pass/fail. (These are style/form - they do
**not** affect the verdict.)

## 8. Recommendation & next steps
Fixes routed to the relevant builder; re-review loop until no Critical remains. **State the
disposition** (fixed / open / accepted / deferred) - and for anything with no
straightforward fix, mark it **Open (needs human developer review)** with the reason and the
options, rather than guessing a fix.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
