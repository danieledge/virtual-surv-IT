# Regulatory scope & tech stack (example — customise)

The customisable example content for CLAUDE.md §2 and §3. It lives here (not in the
always-loaded handbook) so the core stays lean and dormant-friendly — read this when an
engagement actually needs jurisdiction or stack detail, and **edit it to match your reality**.

## Regulatory scope (CLAUDE.md §2)

_Example scope_ — common starting points. Trim to the jurisdictions you actually operate in
(and add any others). When designing or reviewing detection logic, cite the specific
obligation it serves.

- **US:** BSA / FinCEN (AML), SEC & FINRA rules, Dodd-Frank, CFTC, SEC Rule 17a-4 / FINRA
  4511 (recordkeeping & retention).
- **EU / UK:** MLR 2017 & 6AMLD (AML), Market Abuse Regulation (MAR), MiFID II, FCA
  SYSC / SUP record-keeping.
- **Model risk governance:** US SR 11-7, UK PRA SS1/23 — applies to every statistical or
  ML model used in detection.

## Tech stack (CLAUDE.md §3)

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
