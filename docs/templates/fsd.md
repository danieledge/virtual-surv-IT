# Functional Specification Document — <TITLE>

> Drafted by `business-analyst`, reviewed by the domain SME. Structure follows
> ISO/IEC/IEEE 29148; acceptance criteria in **Gherkin** (Given/When/Then). Authored in
> `.md`, rendered to `.html`.

| | |
|---|---|
| **Document ID** | FSD-<slug> |
| **Traces to** | BRD-<slug> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Status** | draft / approved |

## 1. Overview
What this spec covers and how it realises the BRD.

## 2. Functional requirements (EARS)
Each traces back to a BRD requirement.

| ID | Functional requirement (EARS) | Traces to | Notes |
|----|-------------------------------|-----------|-------|
| FSD-001 | When … the system shall … | BRD-001 | |
| FSD-002 | The system shall … | BRD-002 | |

## 3. Data requirements
Inputs, fields, sources, frequency, classification (PII/MNPI). **Synthetic/masked only in
this repo — see CLAUDE.md §5 and the masking pipeline.**

## 4. Detection logic / behaviour
The intended logic at a functional level; thresholds and their rationale (no undocumented
magic numbers — §4).

## 5. Interfaces & integration
Upstream/downstream systems, formats, contracts.

## 6. Non-functional requirements
Performance/latency SLAs, retention & immutability, auditability/explainability, resilience.

## 7. Acceptance criteria (Gherkin)
```gherkin
Feature: <name>
  Scenario: <true-positive case>
    Given <context>
    When <trigger>
    Then an alert is raised citing <obligation>

  Scenario: <false-positive control>
    Given <benign context>
    When <similar trigger>
    Then no alert is raised
```

## 8. Traceability
| BRD | FSD | Test | Obligation |
|-----|-----|------|------------|
| BRD-001 | FSD-001 | test_… | MAR Art.12 |

## 9. Open questions & approvals
