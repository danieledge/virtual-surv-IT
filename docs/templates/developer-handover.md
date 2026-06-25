# Developer Handover - <TITLE>

> Everything a developer needs to take this over, run it, and extend it safely. Authored in
> `.md`, rendered to `.html`.

| | |
|---|---|
| **Deliverable** | <name> |
| **Version / commit** | <…> |
| **Date** | <YYYY-MM-DD> |
| **Owner / contact** | <…> |
| **Traces to** | BRD-<…> / FSD-<…> |

## 1. What it is
Purpose, the problem it solves, and where it fits in the wider surveillance platform.

## 2. Architecture & how it works
A short walkthrough (C4-style context if useful): components, data flow, key modules and
their responsibilities. Diagram welcome.

## 3. Build, run & test
```bash
# install
# build
# run
# test
```
Exact, copy-pasteable commands. Note any prerequisites.

## 4. Configuration & dependencies
Config options, environment variables (secrets via env only - never in code), external
dependencies and versions.

## 5. Key design decisions
Link the ADRs (`docs/templates/adr.md`) and summarise the important trade-offs and *why*.

## 6. Data handling
Inputs/outputs, classification, and how synthetic/masked data is used (CLAUDE.md §5).

## 7. Known limitations & technical debt
Honest list of what's incomplete, fragile, or deliberately deferred - with severity.

## 8. How to extend
Where to add a new rule / pipeline stage / script; conventions to follow; what tests to add.

## 9. Operational notes
Logging, monitoring, retention, failure modes, and how to recover.

## 10. Links
RTM, review report, performance report, QA handover, scenario/spec docs.
