# QA Handover — Test Evidence — <TITLE>

> Produced by `qa-engineer` (independent of the builder). Evidences what was tested, the
> results, what is **not** covered, and what the QA team should note or re-verify. Authored
> in `.md`, rendered to `.html`.

| | |
|---|---|
| **Deliverable** | <name> |
| **Version / commit** | <…> |
| **Tested by** | qa-engineer |
| **Date** | <YYYY-MM-DD> |
| **Overall** | ✅ ready for QA / ⚠️ ready with notes / ❌ not ready |

## 1. Test execution summary
| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| unit | | | | |
| integration | | | | |
| performance | | | | |

How to reproduce (exact commands — use the project's test framework, not an assumed one):
```bash
# Example shown for this repo (Python/pytest). Replace with the target stack's commands,
# e.g. Pester (Invoke-Pester), Maven/Gradle (mvn test / ./gradlew test), Jest (npm test).
pip install -r requirements-dev.txt
pytest
```

## 2. Environment & test data
- Environment / versions:
- Test data: **synthetic / masked only** (§5) — provenance and how it was generated.

## 3. Coverage
- **Covered:** scenarios, true-positive and false-positive cases, edge cases, error paths.
- **NOT covered (and why):** be explicit — unstated gaps are the dangerous ones.
- **Residual risk:** what could still go wrong in production.

## 4. Defects & known issues
| ID | Severity | Description | Status |
|----|----------|-------------|--------|

## 5. Items for the QA team to note / re-verify
Things a human reviewer should manually confirm (e.g. regulatory mapping, alert wording,
threshold rationale, anything not fully automatable).

## 6. Sign-off
| Role | Name | Date | Decision |
|------|------|------|----------|
| qa-engineer (AI) | | | |
| QA reviewer (human) | | | |
