# `/prepare-data` - design specification for assisted-universal masking

> **Status:** design (not yet built). Companion to [`docs/prepare-data-roadmap.md`](prepare-data-roadmap.md),
> which sets the *why* and the option table; this doc is the *how* - the architecture, component
> contracts, threat model and acceptance gates a builder implements against. Authored by Claude
> Fable 5 (2026-07-06) as a design pass; implementation is a later build.

> **The one invariant this design exists to protect:** agents never read `data/raw/`. Every new
> capability below runs as a **local script behind the guard**, surfacing statistics and proposals -
> never raw values - to the human, who confirms before any agent sees anything. "Assisted
> universality + hard validation", not a trust-me button (roadmap §The framing).

---

## 1. Scope

Turns the roadmap's recommended trio (**#1 schema-inference profiler · #2 NER (named-entity recognition) redaction · #3
format adapters**) plus the **#5 auto-validation gate** into a buildable specification. Real
synthetic (#4 SDV/CTGAN) and pluggable transforms (#6) are out of scope here - noted as extension
points, not specified.

**In scope:** the local profiler, the NER redaction role, the format-adapter front door, and the
output-side validation gate that makes "auto-masked" *proven*, not merely attempted.

**Non-goals:** blind/fully-automatic masking (an anti-pattern for PII - roadmap §The framing); any
component that lets an agent process reads raw data; replacing the human confirmation step.

---

## 2. Current pipeline (the baseline being extended)

```
real ─▶ data/raw/ ──[ python -m scripts.ingest ]──▶ data/masked/ ─▶ agents / dev
        (agent-blocked)   schema-driven masking        (governed)
                                  │
                          config/masking-schema.yaml (human-authored: field → role)
```

Established contracts this design must preserve:

- **Roles** (`scripts/ingest.py`): `drop`, `token` (keyed HMAC - a keyed one-way hash - with referential integrity), `shift`
  (per-entity time shift), `keep` (signal-bearing), `generalise` (bucket/map), `redact` (typed
  free-text surrogates). `on_unknown: drop` is the safe default.
- **Key handling:** `MASKING_KEY` from the environment (`~/.secrets`); **no insecure default** -
  `ingest` refuses to run unbounded without it (a fixed non-secret constant exists in
  `validate_masking` for the config self-test *only*).
- **The hard gate:** `scripts/validate_masking.py` proves privacy (no residual identifiers/PII,
  direct-identifier-passthrough check, k-anonymity (each record indistinguishable from at least k-1 others) over declared quasi-identifiers - the attribute combinations that could re-identify someone) **and** utility
  (detection fidelity - the spoofing rule fires identically masked-vs-original). Nothing reaches an
  agent until this passes.
- **The reconciliation house rule** (`docs/house-rules.md`): any extract/convert step ships a
  source-vs-output reconciliation (counts + a control total) and fails loudly - never
  except-and-continue, never silent coercion. `scripts/convert_file.py` is the reference front door.

The design **adds to** this without changing the role semantics or the gate's authority.

---

## 3. Target pipeline

```
                              (all local; agent-blocked; emits STATS + PROPOSALS, never values)
                    ┌──────────────────────────────────────────────────────────────┐
real ─▶ data/raw/ ──┤ 1. adapter → 2. profiler → [HUMAN confirms schema] → 3. ingest ├─▶ data/masked/
        (blocked)   │    (§6)         (§5)          draft masking-schema     (+NER §7)  │
                    └───────────────────────────────────────┬──────────────────────────┘
                                                             ▼
                                                4. auto-validation gate (§8)
                                                   privacy + fidelity + residual-PII over OUTPUT
                                                   BLOCK on residual PII ──▶ (fix schema, re-run)
                                                             │ pass
                                                             ▼
                                                     agents / dev
```

The human-confirm step between the profiler and ingest is **load-bearing, not a convenience** - it
is the control that keeps this "assisted" rather than "blind".

---

## 4. Component map

| # | Component | New/changed | Runs as | Reads raw? | Emits |
|---|---|---|---|---|---|
| 1 | Format adapters | new (`scripts/adapters/`) | local script | yes (behind guard) | normalised JSONL + reconciliation report |
| 2 | Schema-inference profiler | new (`scripts/profile_schema.py`) | local script | yes (behind guard) | draft `masking-schema.yaml` + **non-sensitive** profile report |
| 3 | NER redaction | new role backend in `ingest.py` | local script | yes (behind guard) | masked output (as today) |
| 4 | Auto-validation gate | extend `validate_masking.py` | local script | masked output only | pass/fail + residual-PII report |

Every component is a **local script**. None is an agent. None surfaces a raw value to the model -
only types, counts, pattern-hit tallies, and proposed roles.

---

## 5. Component 1 - schema-inference profiler (`scripts/profile_schema.py`)

**Purpose:** remove the biggest `/prepare-data` friction - the human hand-authoring
`masking-schema.yaml` field by field - by *proposing* a draft the human then confirms or edits.

**Contract:**

```
python -m scripts.profile_schema --in data/raw/<file> [--adapter auto] \
    --out config/<file>.schema.yaml --report artifacts/profile-<file>.json
```

**Inference rules (field → proposed role):**

| Observed property | Proposed role | Rationale |
|---|---|---|
| High-cardinality string, near-unique per record | `token` (domain guessed from name) | likely a direct identifier |
| Matches email / IBAN / phone / national-ID regex | `redact` (free text) or `token` (structured id) | pattern-confirmed PII |
| Parseable as timestamp | `shift` | temporal identifier; preserve deltas |
| Low-cardinality categorical | `keep` (flag as candidate quasi-identifier) | probable signal; may need `generalise` |
| Numeric, wide range | `keep` | probable signal (price/qty) |
| Free-text (long strings, high entropy, spaces) | `redact` **and flag "NER recommended"** | regex alone misses names/orgs (§7) |
| Unmatched | `drop` (via `on_unknown`) | safe default |

**Every proposal carries a confidence and a reason**; the draft schema is a *starting point the
human owns*, and the profiler says so in a header comment it writes into the YAML.

**Safety - the profile report emits STATS, never VALUES:**

- ✅ allowed in the report: field name, inferred type, cardinality, null rate, min/max **length**
  (not value), regex-pattern **hit counts**, proposed role + confidence.
- ❌ forbidden in the report: any field value, any sample row, any example of a matched PII string,
  min/max of a *value* column, top-N frequent values.
- The report is JSON, written to `artifacts/` (git-ignored), and is the only profiler output an
  agent could ever be shown. It must be safe to paste into a prompt. A **unit test asserts no raw
  value leaks** into it (§9, test P-1).

**Reconciliation:** the profiler records the row count it profiled; when chained after an adapter,
that count must tie out to the adapter's output count (house rule).

---

## 6. Component 2 - format adapters (`scripts/adapters/`)

**Purpose:** accept CSV, Parquet, Excel, and nested JSON, normalising each to the internal flat
JSONL record shape `ingest` already consumes. "Throw any structured file at it."

**Contract:** one adapter per format behind a dispatcher:

```
python -m scripts.convert_file <file> --to jsonl [--schema <feed>.yaml]   # existing front door, extended
```

Adapters **reuse the existing `convert_file.py` front door**, not a new parallel path - the house
rule "file conversion goes through the front door, never hand-parse" is absolute. Each adapter:

- is **lossless by default** (zero type inference - the float-mangled account ID and the guessed
  date format are the two classic silent corrupters the existing converter already guards);
- carries the **built-in source-vs-output reconciliation** (row counts + a control total on a
  declared value column; ragged-row and truncation detection) - Excel extraction is the reference
  silent-truncation case (`review-excel-truncation` eval);
- **emits a JSON evidence report every run** - a conversion without its report is not evidence;
- nested-JSON auto-flatten records the flattening map so the reconciliation is meaningful on a
  flattened shape.

**Dependencies stay vendored** (`vendor/`) so the front door works from a bare `git clone` with no
pip access - a Parquet/Excel adapter that needs a new library must vendor it or degrade with a
clear message, never silently require pip.

**PDF stays text-extraction only** - table structure in a PDF is layout, not data; the adapter must
refuse to treat a PDF table as structured data and point at the upstream Excel/CSV (existing rule).

---

## 7. Component 3 - NER redaction (new backend for the `redact` role)

**Purpose:** replace regex-only free-text masking with a PII model (Presidio / spaCy) so
**names, locations, orgs, and obfuscated IDs** are caught - the change that makes **comms/chat**
data viable. Regex misses free-form PII; this is the roadmap's #1-weakness fix.

**Design:**

- Add an NER backend selected by a `redact` field option, e.g. `redact: {engine: ner}` vs the
  current `redact: {engine: regex}` (default stays `regex` for back-compat and no-dependency
  installs). Role name and output contract (typed surrogates, consistent per entity) are unchanged -
  only the *detector* changes.
- **Consistent surrogates:** an NER-detected `PERSON` maps to a keyed-HMAC surrogate in the same
  way `token` does, so linkage is preserved across a conversation (the same person → the same
  surrogate) without exposing the name.
- **Vendoring / degrade path:** the NER model is heavier than the current regex. If the model isn't
  present, `redact: {engine: ner}` must **fail loudly** (not silently fall back to regex - a silent
  downgrade on comms data is exactly the leak this component exists to close). The profiler's
  "NER recommended" flag and this hard-fail together prevent a comms dataset being masked by regex
  alone by accident.
- **Ordering:** lexical/regex redaction is order-sensitive (`docs/house-rules.md`); the NER pass
  runs **before** the regex pass so structured patterns (IBAN, account refs) still get their
  typed surrogates and NER handles the residual free text. Every new pattern needs an overlap test.

---

## 8. Component 4 - auto-validation gate (extend `validate_masking.py`)

**Purpose:** make "auto-masked" *proven* safe. Today `validate_masking --in` scans the masked
output for residual free-text PII and runs k-anonymity. This component **hardens that into a
blocking gate** run automatically after ingest, and adds re-identification risk scoring.

**Additions:**

- **NER over the output:** run the NER scanner (§7) over the masked output's string fields, not
  just regex - catches a name the schema failed to redact. **BLOCK on any residual PII hit.**
- **Re-identification risk scoring:** add l-diversity / t-closeness (finer re-identification measures) on top of the existing
  k-anonymity, over the declared quasi-identifiers. Report the risk; block below a configured
  floor.
- **Gate semantics:** exit non-zero on any residual identifier, any residual PII hit, k-anonymity
  below `k`, or re-id risk below floor. The existing detection-fidelity check (spoofing rule fires
  identically) stays a pass condition - a mask that destroys the signal is a failed mask, not a
  safe one.
- **Runs automatically:** the target pipeline (§3) invokes the gate after ingest; a masked file
  that hasn't passed the gate is not eligible to be shown to an agent. This is enforced by
  convention + the deny list, not by the gate alone (the gate can't stop a human pointing an agent
  at an unvalidated file - document that boundary).

---

## 9. Test plan

Mandatory before any component is considered done (project rule: tests for rule logic, known true-
and false-positive cases, using the project's own framework - pytest here).

| id | Component | Asserts |
|---|---|---|
| P-1 | profiler | profile report contains **no raw value** - fuzz with fields whose values are unique identifiers; assert none appear in the JSON report |
| P-2 | profiler | inference rules: seeded fixture with a known id/email/timestamp/categorical/free-text column → proposed roles match the §5 table |
| P-3 | profiler | reconciliation: profiled row count ties to adapter output count; mismatch fails loudly |
| A-1 | adapters | round-trip losslessness per format (CSV/Parquet/Excel/nested-JSON) - no type inference corruption on a float-like id and an ambiguous date |
| A-2 | adapters | reconciliation report emitted every run; truncated Excel input is caught (mirrors `review-excel-truncation`) |
| A-3 | adapters | vendored-only: adapters run from a bare checkout with no pip; a missing lib degrades with a message, never silently |
| N-1 | NER | names/locations/orgs and an obfuscated id are redacted to consistent surrogates; same entity → same surrogate |
| N-2 | NER | `engine: ner` with no model present **fails loudly** (no silent regex fallback) |
| N-3 | NER | NER-before-regex ordering: overlapping IBAN-in-free-text still gets its typed surrogate |
| G-1 | gate | residual PII in output → non-zero exit (both regex and NER paths) |
| G-2 | gate | k-anonymity below `k` and re-id risk below floor each block independently |
| G-3 | gate | detection fidelity preserved is still required to pass |

Add two **golden eval cases** to `evals/cases/` (the harness pattern): a comms/chat file that only
NER catches (regex-masked version must fail the gate), and a profiler run whose report is checked
for value leakage.

---

## 10. Threat model (what could still leak, and the control)

| Threat | Control in this design | Residual |
|---|---|---|
| Agent reads raw data during profiling | Profiler is a local script behind the guard; emits stats not values | Same Bash-uncovered residual as today (ADR-002 Tier-3) - unchanged, not worsened |
| Profile report leaks a value into a prompt | §5 forbidden-fields list + test P-1 | A new report field added without a test could regress - P-1 must gate CI |
| NER silently downgrades to regex on comms data | Hard-fail on missing model (N-2); profiler flags "NER recommended" | Human ignores the flag and picks `engine: regex` - documented, not preventable |
| Adapter silently truncates a large Excel extract | Built-in reconciliation, fail loudly (A-2) | A value column not declared for the control total → weaker tie-out; require one |
| "Auto-masked" trusted without proof | Gate blocks on residual PII / low k / low l-diversity (§8) | Gate can't stop a human pointing an agent at an unvalidated file - convention + deny list |
| Masked output treated as anonymous | Docs restate masked ≠ anonymous (GDPR); prefer synthetic to leave the env | Cultural, not technical - #4 SDV is the real fix |

**Non-negotiables carried from the roadmap (all preserved):** agents never read `data/raw/`;
`MASKING_KEY` required with no insecure default; `validate_masking` stays the hard gate; masked ≠
anonymous.

---

## 11. Build order

1. **Adapters (#3)** first - lowest risk, pure parsing, immediately useful, and gives the profiler
   real formats to profile. Reuses `convert_file.py`.
2. **Profiler (#1)** next - depends on adapters for input; delivers the biggest friction win.
3. **NER (#2)** + **gate NER hardening (#8)** together - the detector and the check that proves it
   worked ship as a pair (roadmap: #5 ships *alongside* the capability, never after).
4. **Re-id risk scoring (#8)** last of this scope; **SDV (#4)** and **pluggable transforms (#6)**
   are a separate, larger build.

Each step is independently shippable behind the existing safety model and adds its own tests before
merge.
