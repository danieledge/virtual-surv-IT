---
description: BETA - assess a Quantexa TM implementation against BRDs/TSDs - requirements-to-artifact traceability with a Quantexa knowledge base
argument-hint: <repo path + where the BRDs/TSDs are>
disable-model-invocation: true
---

**BETA.** Assess a **Quantexa transaction-monitoring implementation** against business
requirements for: **$ARGUMENTS**

This is the `/audit-review` requirements-traceability assessment **specialised for Quantexa
estates**: same conventions (evaluator-optimizer loop, verdicts with dispositions, 📊/🧠
evidence basis, the audit-compatible skeleton, iteration log, brief/email DoD bookends), plus
a platform knowledge base so assessors know **every place a requirement can be satisfied** -
in a Quantexa estate that is emphatically not just the Scala.

**0. Read the knowledge base first.** `references/quantexa-kb.md` (in this skill's directory)
holds the verified platform knowledge: artifact taxonomy, the scoring DAG and pipeline stages,
code-vs-config split, build conventions, version sensitivities, and the assessment traps.
Every KB claim is evidence-tagged with a source and confidence. **The KB tells you where to
look; the estate tells you where it is** - the KB never outranks 📊 observed repo structure.

**1. Day-one calibration (mandatory - the KB demands it).** Before any requirement verdict:
- **Fingerprint the platform version**: the Quantexa artifact versions referenced from the
  build (private Nexus/Artifactory coordinates), release-note mentions in the repo, and
  framework idioms (Scoring Framework 1 vs Assess - package names/base classes). Version
  determines where detection logic can live; on 2.8.1+ some of it can be **UI-managed
  (Decision Systems) and outside the repo entirely** - if so, agree with the client what
  platform-side configuration will be exported for review, and record anything not provided
  as an explicit coverage limitation.
- **Map the estate's actual layout** against the KB's expected artifact classes (ETL/Fusion,
  resolver config, scorers, scoring config, scorecards, alerting/re-alerting, task loading)
  and record the mapping in the working project's codebase map (ADR-003) - corrected, not
  assumed. Ask the client for **Project Example at their platform version** (community
  download) as the canonical-layout baseline if available.
- **Request client access to the Quantexa docs/community portal** - artifact-level schemas
  are login-gated; without access, schema-level claims stay 🧠 inferred and must say so.

**2. Requirements decomposition.** `business-analyst` decomposes the BRDs/TSDs into numbered,
testable requirements (EARS where possible) and classifies each by **requirement type** so it
routes to the right artifact classes per the KB routing table: data-coverage → ETL/Fusion;
matching/ER → resolver config + data-model declarations; detection → scorers **and** their
config **at every score level the estate uses** (Document/Entity/Network/Event, batch and
dynamic); thresholds/tuning → scoring config + tuning evidence (ATL/BTL packs); alert
generation → scorecard wiring + alerting/re-alerting stage; investigation/UI → task loading
and UI config.

**3. Trace both directions.**
- **Forward (requirement → artifact):** per requirement, a coverage verdict - implemented /
  partial / missing / contradicts - with cited evidence (`file:line` for Scala, key-path for
  config, commit SHA), checking **all** candidate artifact classes before a "missing" verdict.
- **Every non-clean verdict is a fully explained finding - first pass, no iteration needed.**
  A live engagement had to iterate the assessment document because verdicts named the gap but
  did not explain it. Each partial / missing / contradicts verdict carries **all six**, written
  for a reader who did not build the code and was not in the session:
  1. **Expected:** what the TSD/BRD requires (cited - document § and version);
  2. **Found:** what the implementation actually does (cited evidence, 📊/🧠 tagged);
  3. **Why this is an issue:** the discrepancy in plain language - no Quantexa jargon
     without a gloss, no "see code" hand-waves;
  4. **Likely cause:** why the gap exists - spec drift, config error, misunderstanding,
     regression ("undetermined - needs investigation" is allowed; silence is not);
  5. **Potential impact if unaddressed:** the consequence in the domain's terms - missed
     detections / false negatives, alert-volume or tuning effects, scorecard/alerting
     behaviour changes, audit or regulatory exposure, operational cost - tagged 🧠 when
     projected rather than observed, and honest about magnitude uncertainty;
  6. **Recommended action:** concrete and routed (code change / config change / TSD
     correction / client decision needed).
  This is the audit profession's **5 C's** (criteria / condition / cause / consequence /
  corrective action) in the team's shape. The same applies to reverse-traceability findings
  (unmapped scorers, unwired scorecards). Format reference: `docs/review/output-format.md`;
  **anchor on the worked verdict exemplar in `docs/review/gold-findings.md` before writing.**
- **Reverse (artifact → requirement):** inventory every scorer and score-producing config in
  the estate and map each back to a requirement. **Verify scorecard wiring for every scorer**
  - a scorer not wired into a scorecard contributes nothing to alerts (KB-confirmed) and is
  either dead logic or undocumented detection; both are findings.
- **The trap list** (KB §6) is checked explicitly: unwired scorers, hardcoded thresholds
  where config is expected, per-environment config drift, TSD-vs-implementation drift,
  alerting/re-alerting suppression logic nobody traced, tuning evidence absent for
  business-supplied thresholds.

**4. Deliver.** Standard artifacts via the audit-review conventions: RTM (both directions),
Delivery Report with iteration log, review report in the audit skeleton (the **Limitations &
residual risk** section must state: static-only basis, gated-documentation limits, any
UI-managed configuration not exported, and every 🧠 inferred schema assumption). Update the
working project's codebase map at close.

**Data safety (§5):** BRDs/TSDs and estate code stay in `artifacts/`/local paths - never
commit client material, never put client detail in this skill or its KB (the KB is
plugin-scoped and travels across projects; estate-specific knowledge belongs in the working
project's codebase map).

**Scale discipline:** requirement-led fan-out only (each specialist gets a requirement
cluster + the RTM as coordination artifact) - never "read the repo". Right-size the team and
say so at the gate, per the operating guide.
