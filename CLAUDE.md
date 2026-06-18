# Compliance Surveillance Engineering — Team Handbook

This file is shared context for every agent in this repository. Claude Code loads it
into the main session and into every custom subagent at startup. Keep it current — it is
the single source of truth that keeps the virtual team aligned.

> ℹ️ Sections 2 and 3 ship with **example defaults** so the team works out of the box.
> They are illustrative, not prescriptive — replace them with your real jurisdictions,
> stack and platforms whenever you have them.

---

## 1. What this team does

We build and maintain detection and surveillance capability across three domains:

- **Transaction Monitoring (TM)** — AML scenario detection, thresholds, typologies, alert
  generation, SAR/STR support.
- **Trade Surveillance** — market abuse detection (spoofing, layering, wash trades,
  marking the close, insider dealing, front running).
- **Communications Surveillance** — lexicon and NLP-based monitoring of e-comms and voice.

## 2. Regulatory scope

_Example scope_ — the obligations below are common starting points. Trim to the
jurisdictions you actually operate in (and add any others).

- **US:** BSA / FinCEN (AML), SEC & FINRA rules, Dodd-Frank, CFTC, SEC Rule 17a-4 / FINRA
  4511 (recordkeeping & retention).
- **EU / UK:** MLR 2017 & 6AMLD (AML), Market Abuse Regulation (MAR), MiFID II, FCA
  SYSC / SUP record-keeping.
- **Model risk governance:** US SR 11-7, UK PRA SS1/23 — applies to every statistical or
  ML model used in detection.

When designing or reviewing any detection logic, cite the specific obligation it serves.

## 3. Tech stack  <!-- Example defaults — replace with your real stack -->

Until you customise it, the team assumes this **example stack** — a common, cloud-agnostic
surveillance setup. Edit any line to match your environment.

- Languages: Python (rules + ML), SQL (analytics). _Example:_ add Scala/Java if your
  streaming jobs use them.
- Data: _Example:_ Kafka for streaming ingestion, Spark for batch, a columnar warehouse
  (Snowflake / BigQuery / Redshift) for analytics.
- Surveillance platform: _Example:_ in-house detection on the above, interoperable with
  vendor platforms (NICE Actimize / Nasdaq / Behavox) where present.
- Cloud: _Example:_ cloud-agnostic — agents keep designs portable across AWS / Azure / GCP.
- Orchestration / CI: _Example:_ Airflow (or similar) for pipelines; Git-based CI with
  tests gating any change to detection logic.

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

**Real data must never reach an agent.** Anything an agent reads is sent to the model
provider as prompt context, so the team is structured to sit *downstream* of masking:

- Raw data, if it exists at all, lives under `data/raw/` and is **off-limits to agents** —
  the `data/raw/` read-guard hook (`.claude/hooks/guard-raw-data.py`) blocks it.
- The **only** sanctioned path in is `python -m scripts.ingest` (config in
  `config/masking-schema.yaml`): it destroys the identity layer (tokenise IDs, shift
  timestamps, redact free text) while preserving the behavioural signal detection needs.
  The HMAC key comes from `MASKING_KEY` in `~/.secrets` — there is no insecure default.
- Validate every masking config with `python -m scripts.validate_masking`: it must show
  no residual identifiers/PII **and** identical detection results on masked vs. original.
- **Pseudonymised ≠ anonymous.** Masked output is still personal data (GDPR) — keep it
  governed. For anything leaving the environment, prefer fully **synthetic** data.
- If asked to analyse real data, **stop** and require it be passed through `scripts/ingest.py`
  (or replaced with synthetic data) first.

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
