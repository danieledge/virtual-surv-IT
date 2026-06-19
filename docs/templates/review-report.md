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

## 2. Findings

### 🔴 Critical (must fix)
| # | File:line | Issue | Standard / rule | Recommended fix |
|---|-----------|-------|-----------------|-----------------|
| 1 | `path:42` | … | CWE-89 / OWASP ASVS V5 | … |

### 🟠 Warnings (should fix)
| # | File:line | Issue | Standard / rule | Recommended fix |
|---|-----------|-------|-----------------|-----------------|

### 🟡 Suggestions
| # | File:line | Issue | Standard / rule | Recommended fix |
|---|-----------|-------|-----------------|-----------------|

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

## 5. Recommendation & next steps
Fixes routed to `rules-developer` / `ml-engineer`; re-review loop until no Critical remains.
