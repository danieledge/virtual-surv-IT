# Acronym glossary

The domain and spec shorthand used throughout the repo and the team's artifacts.

| Acronym | Meaning |
|---|---|
| ADR | Architecture Decision Record - a short note recording why a design decision was made |
| AML | Anti-Money Laundering |
| ATL/BTL | Above-The-Line / Below-The-Line threshold testing (what a threshold catches vs what it just misses) |
| BABOK | Business Analysis Body of Knowledge - the standard reference for how to do business analysis, from the International Institute of Business Analysis (IIBA) |
| Blackboard | A coordination pattern: agents work through shared artifacts (files on a common board) instead of talking to each other - here, the engagement's `VSIT/engagements/` workspace is the blackboard |
| BRD / FSD | Business Requirements Document / Functional Specification Document (the plain-language "what we need" and the detailed "how it works") |
| CI | Continuous Integration - the automated checks (tests, linters, scans) that run on every code change |
| Codebase map | The team's per-project memory file (`VSIT/shared/map.md`, ADR-003/ADR-007) - a bounded, PM-curated, hygiene-gated index of durable code facts, read at every engagement open and updated at every close |
| CWE | Common Weakness Enumeration - the standard catalogue of software weakness types that security reviews cite |
| DoD | Definition of Done - the checklist a deliverable must pass before it counts as finished |
| EARS | Easy Approach to Requirements Syntax (unambiguous requirement phrasing) |
| ETL | Extract, Transform, Load - the plumbing that pulls data from a source, reshapes it, and loads it where it is used |
| Evaluator-optimizer | An agent pattern: one agent produces work, another evaluates it, and the loop repeats until it passes (how `/audit-review` runs) |
| FP | False Positive - an alert that turns out to be nothing |
| Gherkin | The Given-When-Then format for acceptance criteria, written so each one maps straight to a test |
| ISO/IEC 29119 | The international standard for software testing - test processes and documentation |
| ISO/IEC/IEEE 29148 | The international standard for requirements specification (supersedes IEEE 830) |
| k-anonymity | A privacy measure: each record is indistinguishable from at least k-1 others on the fields that could identify someone indirectly |
| LLM | Large Language Model - the AI text engine behind tools like Claude or ChatGPT |
| MAR | (EU) Market Abuse Regulation |
| MCP | Model Context Protocol - an open standard for connecting AI assistants to external tools and data sources |
| MI | Management Information - the metrics, reporting and dashboards a compliance team runs on |
| ML | Machine Learning - software that learns patterns from data instead of being coded rule by rule |
| MNPI | Material Non-Public Information - price-sensitive information not yet public; trading on it, or leaking it, is insider dealing |
| MW79 | [FCA Market Watch 79](https://www.fca.org.uk/publications/newsletters/market-watch-79) (May 2024) |
| NER | Named-Entity Recognition (finding names/IDs in free text) |
| NLP | Natural Language Processing - getting software to read and interpret human text (here, trader chat and email) |
| Orchestrator-workers | An agent pattern: a lead agent breaks the work down and hands the parts to worker agents (how `/build-solution` runs) |
| OWASP ASVS | The OWASP Application Security Verification Standard - the security checklist reviews verify against |
| PII | Personally Identifiable Information - data that can identify a person (names, account numbers, and so on) |
| PM | Project Manager - here, Morgan, who runs the engagement and coordinates the specialists |
| Prompt chaining | An agent pattern: the output of one step becomes the input of the next (idea → BRD → FSD → build) |
| QA | Quality Assurance - independent testing that a deliverable actually works before sign-off |
| RTM | Requirements Traceability Matrix - a table linking each requirement to the code, test and regulatory obligation that satisfies it, so nothing is orphaned |
| SAR / STR / STOR | Suspicious Activity Report / Suspicious Transaction Report / Suspicious Transaction and Order Report |
| SARIF | Static Analysis Results Interchange Format - the standard JSON format analyser tools emit findings in |
| SME | Subject-Matter Expert |
| SR 11-7 | The US Federal Reserve's supervisory guidance on model risk management |
| TM | Transaction Monitoring |
| UAT | User Acceptance Testing |

---

Next: [Overview](OVERVIEW.md) · [Demos](demos/review-demo.md) · [FAQ](FAQ.md) · [README](../README.md)
