# Code & Compliance Review Report — <TITLE>

> Output of an audit-review engagement. Produced by `code-reviewer` (engineering quality &
> security) and `compliance-reviewer` (auditability & regulatory trail). Authored in `.md`,
> rendered to `.html`.

| | |
|---|---|
| **Scope** | <files / commit range reviewed> |
| **Languages** | <Python / Scala / Java / PowerShell / Bash> |
| **Date** | <YYYY-MM-DD> |
| **Verdict** | ✅ audit-ready / ⚠️ conditional / ❌ not yet |

## 1. Summary
Plain-language verdict: would this stand up to audit and regulatory scrutiny, and what (if
anything) must change first.

**Found N · Reported R · Filtered F** (depth: quick / deep · mode: change / audit)

## 2. Findings
Confidence score per `docs/code-review-method.md` (Critical 95–100, Warning 80–94, Medium
70–79 — deep only). **Each finding carries a concrete `diff`-style fix + "why it works".**
If there are none: *✅ No significant issues found* (still show the filtered counts below).

### 🔴 Critical (must fix)
| # | File:line | Issue | Conf. | Standard / rule |
|---|-----------|-------|-------|-----------------|
| 1 | `path:42` | … | 97 | CWE-89 / OWASP ASVS V5 |

> **Fix for #1:**
> ```diff
> - vulnerable_line
> + fixed_line
> ```
> *Why this works:* …

### 🟠 Warnings (should fix)
| # | File:line | Issue | Conf. | Standard / rule | Recommended fix |
|---|-----------|-------|-------|-----------------|-----------------|

### 🟡 Medium *(deep review only)*
| # | File:line | Issue | Conf. | Standard / rule | Recommended fix |
|---|-----------|-------|-------|-----------------|-----------------|

### 🔇 Filtered (transparency — show what was not reported)
| Reason | Count |
|--------|-------|
| Pre-existing (not in diff) | |
| Below confidence threshold | |
| Linter/formatter territory | |
| Silenced by comment | |

## 3. Audit & regulatory checks
- Auditability: alert → logic → obligation traceable? (RTM present/complete?)
- Thresholds documented with rationale + date (§4)?
- Data handling: no PII/MNPI/secrets in code/tests/logs; synthetic/masked only (§5)?
- Test coverage: true-positive and false-positive cases present?
- Change control: reviewed and documented before merge?

## 4. Tooling coverage
| Analyser | Ran? | Notes |
|----------|------|-------|
| ruff / mypy / bandit | | |
| ShellCheck / PSScriptAnalyzer / SpotBugs / … | | |
| Semgrep / gitleaks | | |

State explicitly which analysers were unavailable — nothing silently skipped.

## 5. Architectural notes *(deep review only)*
- Pattern consistency: ✅/⚠️/❌ …
- Coupling & cohesion: …
- Test coverage: …
- Dependencies: …

## 6. Impact analysis *(deep review only)*
- **Affected files / modules:** …
- **Blast radius:** … (what else could this change break?)
- **Breaking changes:** …

## 7. Recommendation & next steps
Fixes routed to `rules-developer` / `ml-engineer`; re-review loop until no Critical remains.
