# `/prepare-data` — enhancement roadmap ("throw anything at it")

> Today `/prepare-data` is a **guided, schema-driven** on-ramp (synthetic by default; masking via
> `scripts/ingest.py` + `config/masking-schema.yaml`, gated by `validate_masking`). It handles
> **flat JSONL** where the human maps each field to a role. This doc is the credible path to make
> it accept far more, *without* weakening the safety model.

## The framing: assisted, not blind
Fully *blind* universality is an **anti-pattern for PII** — one auto-missed identifier is a real
breach, and agents are walled off from raw data on purpose. So the goal is **assisted universality
+ hard validation**: take more formats, *propose* the mapping for a human to confirm, and catch
leaks harder. Not a "trust-me button".

## Options, by leverage

| # | Upgrade | Buys | Effort | Safety note |
|---|---|---|---|---|
| 1 | **Local schema-inference profiler** | A local script (not an agent — stays behind the guard) profiles the raw file and **proposes a draft schema**: high-cardinality strings → likely IDs, timestamp detection, email/IBAN pattern hits → redact, numerics → signal. Emits only **non-sensitive stats** (types, cardinalities, pattern counts — never values). Human confirms. Removes the biggest friction. | Med | Keeps the agents-never-see-raw boundary intact. |
| 2 | **NER redaction (Presidio / spaCy)** | Replace regex-only free-text masking with a PII model — catches **names, locations, orgs, obfuscated IDs**. Makes **comms/chat** data viable. | Med-High | Closes the #1 weakness (regex misses free-form PII). |
| 3 | **Format adapters** | Accept **CSV, Parquet, Excel, nested JSON** (auto-flatten) → normalise to the internal record shape. "Any structured file." | Med | Pure parsing; low risk. |
| 4 | **Proper synthetic (SDV / CTGAN)** | Upgrade `synthesise.py` from fit-and-sample to a real synthetic-data library → fully synthetic, no 1:1 mapping → **not personal data**. The genuine "throw anything, trust the output" route. | High | Best privacy posture. |
| 5 | **Validation hardening** | Run the NER scanner over the **output** to prove no PII leaked; add re-identification risk scoring (l-diversity / t-closeness on top of the existing k-anonymity). | Med | Makes "throw anything" *trustworthy*, not just possible. |
| 6 | **Pluggable transforms** | User-registered roles: format-preserving encryption, differential-privacy noise, date generalisation, per-field. | Med | Extensibility without forking `ingest.py`. |

## Recommendation
Build the **trio #1 + #2 + #3** (schema-inference profiler · NER redaction · format adapters) — that
delivers ~80% of "throw a structured dataset at it and it walks me to safe output" with no loss of
safety. **#4 (real synthetic)** is the gold standard for a truly universal, trust-the-output path,
and the larger build. **#5** should ship alongside whatever capability is added, never after.

## Non-negotiables (whatever we build)
- Agents **never** read `data/raw/` — inference/profiling runs as a **local script**, surfacing
  stats not values.
- `MASKING_KEY` required; no insecure default.
- `validate_masking` stays the **hard gate**: no residual PII **and** identical detection results on
  masked vs original, before any agent sees the data.
- Masked ≠ anonymous (GDPR) — prefer **synthetic** for anything leaving the environment.
