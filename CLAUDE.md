# Compliance Surveillance Engineering — Team Handbook

This file is shared context for every agent in this repository. Claude Code loads it
into the main session and into every custom subagent at startup. Keep it current — it is
the single source of truth that keeps the virtual team aligned.

> ⚠️ Edit the `TODO` markers below to match your actual stack, jurisdictions and platforms.

---

## 1. What this team does

We build and maintain detection and surveillance capability across three domains:

- **Transaction Monitoring (TM)** — AML scenario detection, thresholds, typologies, alert
  generation, SAR/STR support.
- **Trade Surveillance** — market abuse detection (spoofing, layering, wash trades,
  marking the close, insider dealing, front running).
- **Communications Surveillance** — lexicon and NLP-based monitoring of e-comms and voice.

## 2. Regulatory scope

Trim this to the jurisdictions you actually operate in.

- **US:** BSA / FinCEN (AML), SEC & FINRA rules, Dodd-Frank, CFTC, SEC Rule 17a-4 / FINRA
  4511 (recordkeeping & retention).
- **EU / UK:** MLR 2017 & 6AMLD (AML), Market Abuse Regulation (MAR), MiFID II, FCA
  SYSC / SUP record-keeping.
- **Model risk governance:** US SR 11-7, UK PRA SS1/23 — applies to every statistical or
  ML model used in detection.

When designing or reviewing any detection logic, cite the specific obligation it serves.

## 3. Tech stack  <!-- TODO: replace with your real stack -->

- Languages: Python (rules + ML), SQL (analytics). TODO: others (Scala/Java)?
- Data: TODO streaming (e.g. Kafka), TODO batch/warehouse (e.g. Spark, Snowflake/BigQuery).
- Surveillance platform: TODO (e.g. NICE Actimize / Nasdaq / Behavox / in-house).
- Cloud: TODO (AWS / Azure / GCP). Examples in agents are cloud-agnostic.
- Orchestration / CI: TODO.

## 4. Engineering conventions

- Every detection rule/model must be **explainable and auditable**: deterministic inputs,
  documented thresholds, and a traceable link from alert → logic → regulatory obligation.
- No hard-coded thresholds without a comment recording rationale and tuning date.
- All changes to detection logic require review by `compliance-reviewer` before merge.
- Tests are mandatory for rule logic, including known true-positive and false-positive cases.

## 5. Data handling (non-negotiable)

- Treat all transaction, order, trade and communications data as containing **PII and
  potentially MNPI**. Never paste raw records into prompts, commits, logs or test fixtures.
- Use synthetic or masked data for examples and tests.
- Never write secrets, credentials or connection strings into the repo.

## 6. How the virtual team works

- **Advisory agents** (`*-sme`, `model-validator`, `compliance-reviewer`) are read-only.
  Consult them for design, critique and sign-off — they cannot change code.
- **Build agents** (`requirements-analyst`, `rules-developer`, `data-analyst`,
  `ml-engineer`, `cloud-architect`) implement.
- **You** are the orchestrator/PM. Route work and chain agents, e.g.:
  *"Have requirements-analyst write the spec, trade-surveillance-sme review the logic,
  then rules-developer implement it and compliance-reviewer check the audit trail."*

## 7. Guardrails

- An advisory agent that finds itself wanting to edit code should stop and hand back to the
  orchestrator with a recommendation instead.
- `model-validator` is independent of `ml-engineer` by design — it must be free to challenge.
- Prefer chaining agents in one session. Use agent teams only for genuinely parallel,
  multi-workstream tasks (they cost significantly more tokens).
