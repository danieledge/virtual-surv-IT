# Quantexa Platform Knowledge Base - for TM implementation assessment (BETA)

> **Read by `/beta-assess-quantexa` at step 0.** Built exclusively from an adversarially
> verified deep-research pass over **public** sources (2026-07-19; 25/25 claims confirmed,
> 3-vote verification; sources are Quantexa's own Community/KB/Academy pages, vendor blog and
> empirical access tests - no independent practitioner literature exists publicly).
>
> **Standing rules:** (1) The estate outranks this KB - every "typically lives in X" claim
> needs day-one calibration against the actual repo; (2) version-sensitivity is high -
> fingerprint the platform version before applying anything below; (3) **never** add
> client/estate-specific knowledge here (plugin-scoped file) - that goes in the working
> project's codebase map; (4) each claim carries its evidence tag - repeat the tag when you
> rely on the claim in a deliverable.
>
> **As-of 2026-07-19.** Version facts current to the 2.8.x announcements (2.8.0 released
> 2025-07-28); a 2.9+/3.x release after the research window could shift deprecations.

## 1. Artifact taxonomy - where a requirement can live

Official building blocks (📊 official Academy/docs, high confidence):
**Data Fusion (ETL)** → **Entity Resolution** (driven by *Fusion files* + *resolver config*)
→ **Assess (scoring)** → **Scorecards** → **Alerting / Re-alerting** → **Task loading** →
**UI (Search / Investigation / Task)**.

Organise the requirements-to-artifact mapping against exactly these classes. In newer
versions (ER Accelerate, Fusion UI) some configuration may be UI-managed rather than repo
files.

## 2. Scoring - a multi-level DAG, two pipelines (📊 official docs, high)

- Scores form a **DAG** across **Document, Entity, Network, Event and Record** levels
  (Event = transaction data rolled up to Document level; Network scores take LiteGraph
  input; Entity scores aggregate/roll down).
- **Batch and Dynamic scoring are distinct pipelines** (Dynamic adds score contexts,
  batch-lookup config, Elasticsearch reads/writes).
- **Assessment consequence:** one TM requirement can be satisfied at any of several score
  levels and in either pipeline. Check all levels the estate uses before a "missing" verdict.

## 3. Code vs config split (📊 official academy/community, high; file naming thin)

- **Detection logic = Scala** ("Scoring Engineers" certification gates on Scala & Spark);
  **business parameters = config**, expected in HOCON-style scoring config (community
  guidance names `scoring.conf` - ⚠️ thin snippet evidence, verify the actual file naming on
  day one). Vendor tuning guidance: a Score identifies behaviour "with the configurations
  given by business".
- **A hardcoded threshold in scorer code is a deviation worth flagging** against both the
  vendor pattern and (usually) the TSD.
- ER is **configuration-driven**: resolver config in **YAML and JSON** ("the technical
  backbone of entity resolution" - 🧠 medium confidence on schema detail, which is gated and
  has changed across versions: a "Resolver Attributes migration" doc exists). ER requirements
  trace into resolver YAML/JSON **plus** Scala data-model element/compound declarations - a
  hybrid.

## 4. Score → Scorecard → Alerting → Task (📊 official KB, high)

Verbatim-verified mechanics with direct assessment consequences:
- "One or more Scores contribute to a Scorecard and the combined contributions give a total
  Scorecard value for alerting." → **A scorer not wired into a scorecard contributes nothing
  to alerts.** Verify wiring for every scorer; unwired = dead logic or undocumented
  detection, either way a finding.
- "Alerting is the name for the process that comes after Scorecard creation and before Task
  loading" - a **distinct stage** deciding which Subjects alert. Look for it as its own
  artifact (code or config; version/client-sensitive), not inside scorers.
- **Re-alerting** compares current vs all previous Scorecard outputs so only new material
  risk alerts - suppression/delta logic that must be traced for any requirement about alert
  volumes or repeat alerts.
- **Tuning evidence is an expected artifact class**: the vendor-recommended method is
  **ATL/BTL validation** and "Scorecard Tuning" is a named vendor activity. If BRD thresholds
  have no tuning pack behind them, flag it (the detailed method doc is login-gated).

## 5. Versions & where logic can escape the repo (📊 official, high)

- **Scoring Framework 1 is deprecated** in favour of Assess/Dynamic Scoring (~2.0.0+).
  Fingerprint SF1 vs Assess era from package names/base classes (exact markers are gated -
  an open question; note the basis if inferring).
- **Platform 2.8.1 (2025): "Decision Systems" GA** - a **low-code UI** where users
  "configure scorecards, select scoring logic, and set up alert workflows without writing
  code". First GA use case is trade finance, not TM, but on 2.8.1+ estates
  **detection-relevant behaviour can live in UI-managed configuration outside the Scala repo
  entirely**. The assessment must ask what platform-side config exists and get it exported,
  or record the gap as a coverage limitation.
- 2.8.0 announced 2025-07-28; no public evidence of a 3.0 line (as-of date above).

## 6. Build & repo conventions (📊 official academy + empirical checks, high)

- Official Quantexa projects build with **Gradle, not sbt** - multi-module, packaging per
  module a **project shadow JAR** (implementation) + **dependency shadow JAR** (libraries),
  e.g. `gradle :projectShadowJar :dependencyShadowJar`.
- Quantexa platform binaries are on **no public registry** (Maven Central: zero; GitHub org:
  no public repos); they arrive as "Software Bundles" in the **client's own
  Nexus/Artifactory**. → The repo's private-registry Quantexa artifact coordinates **reveal
  the platform version** - use them for fingerprinting.
- **Project Example** - Quantexa's official reference codebase (Scoring, Task Loading, Smoke
  Tests; version-matched ZIP, migration branches per release; community login required) - is
  the single best "what canonical looks like" baseline. Ask the client for it at their
  platform version.

## 7. The trap list (🧠 inferred from vendor pipeline mechanics - no public practitioner
literature exists; treat as hypotheses to test, and say so in findings)

1. Scorers not wired into any scorecard (dead or undocumented detection).
2. Thresholds hardcoded in Scala where the TSD/vendor pattern says config.
3. Per-environment config drift (dev/UAT/prod overlays differ materially).
4. TSD-vs-implementation drift (spec describes SF1-era or superseded behaviour).
5. Alerting/re-alerting suppression logic untraced (alert-volume requirements judged on
   scorers alone).
6. Business thresholds with no ATL/BTL tuning evidence.
7. On 2.8.1+: UI-managed (Decision Systems) configuration nobody exported for review.
8. Requirements judged "missing" after checking only one score level or only the batch
   pipeline.

## 8. Public-verification limits (📊 empirical access tests, high)

`docs.quantexa.com` redirects to a customer/partner login; nearly all substantive Scoring KB
articles, the alerting/threshold detail, full release notes and Project Example are
login-gated; the live community 403s unauthenticated tools. **Get client-sponsored
docs/community access on day one.** Public sources validate concepts and taxonomy - not
artifact-level schemas; anything schema-level asserted without portal access is 🧠 inferred
and must be tagged so.

## Open questions (from the research - close them during the first engagement and record
answers in the working project's codebase map, not here)

- Exact canonical repo layout / config directory structure / per-environment overlay
  mechanism / scoring config schema (gated: Project Example or docs portal).
- Which TM detection behaviours are exposed via the low-code path at 2.8.1+, and where
  UI-managed scoring config persists (database vs exportable files).
- SF1-vs-Assess fingerprint markers (package names, base classes, DAG registration).

## Sources (primary, verified 2026-07-19)

Quantexa Community/KB/Academy: Scoring Collection (2813), Individual Score Tuning Guidance
(3719), Alerting & Re-alerting (4232), Resolver Config (25851), Using Gradle Effectively
(38947), Quantexa Resources (39119), Academy introduction (38936), 2.8.0 release announcement
(42087), Scorecard Tuning (5745, 32795), ER Accelerate (11101). Vendor: quantexa.com blog
"How Quantexa Scoring and Decision Systems improve the decision lifecycle";
platform/scoring-analytics; platform/entity-resolution-software. Full URL list in the
research dossier artifact.
