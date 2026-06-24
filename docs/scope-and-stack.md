# Regulatory scope & tech stack (example — customise)

The customisable example content for CLAUDE.md §2 and §3. It lives here (not in the
always-loaded handbook) so the core stays lean and dormant-friendly — read this when an
engagement actually needs jurisdiction or stack detail, and **edit it to match your reality**.

## Regulatory scope (CLAUDE.md §2)

**Our operating jurisdictions: Europe (EU), UK, US, Singapore, Hong Kong, Japan.** When
designing or reviewing detection logic, cite the specific obligation it serves, and assess
against the regime(s) applicable to the data/desk in question — not every rule applies to every
flow. Key frameworks per jurisdiction:

- **EU:** MLR / 6AMLD (AML), Market Abuse Regulation (MAR), MiFID II.
- **UK:** MLR 2017 / JMLSG (AML), UK MAR, FCA SYSC / SUP record-keeping, PRA SS1/23 (model risk).
- **US:** BSA / FinCEN (AML), SEC & FINRA rules, Dodd-Frank, CFTC, SEC Rule 17a-4 / FINRA 4511
  (recordkeeping & retention), SR 11-7 (model risk).
- **Singapore (MAS):** Securities and Futures Act (SFA) — market manipulation & insider
  trading; MAS AML/CFT Notices (e.g. 626); MAS guidelines.
- **Hong Kong (SFC):** Securities and Futures Ordinance (SFO) — market misconduct (manipulation,
  insider dealing); AMLO (AML); HKMA/SFC guidelines.
- **Japan (JFSA / SESC):** Financial Instruments and Exchange Act (FIEA) — market manipulation
  & insider dealing; Act on Prevention of Transfer of Criminal Proceeds (AML, JAFIC); JFSA model
  risk management principles.
- **Cross-cutting (AML):** FATF recommendations underpin the AML regimes above.
- **Cross-cutting (model risk):** apply the applicable model-risk standard to every statistical
  or ML detection model — SR 11-7 (US), PRA SS1/23 (UK), and the JFSA/MAS equivalents.

> The compliance review assesses against **these** jurisdictions. State explicitly which
> regime(s) apply to a given deliverable and which don't. Edit this list if your footprint changes.

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
