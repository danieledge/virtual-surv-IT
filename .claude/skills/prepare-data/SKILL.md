---
description: Guided data onboarding — get safe, governed data (synthetic or masked) ready before any agent sees it
argument-hint: <what you want to analyse / the data you have, if any>
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(python -m scripts.gen_synthetic:*), Bash(python -m scripts.ingest:*), Bash(python -m scripts.validate_masking:*), Bash(python -m scripts.synthesise:*), Bash(test -n "$MASKING_KEY"), Bash(ls:*)
---

Under the PM (CLAUDE.md §6), get **safe, governed data** ready so the team can work without
ever exposing real PII/MNPI (CLAUDE.md §5). This is the sanctioned on-ramp that sits *upstream*
of every other workflow: **$ARGUMENTS**

This skill is **guided** — walk the user through each step in plain English, confirm before
running anything, and never read raw data yourself (the `data/raw/` guard blocks it by design).

## 1. Gather inputs first — ask, don't assume
Establish via the question tool, and **wait for answers**:
- **What are you trying to do?** (free-text ask with an "Other" path — e.g. "find anomalies in
  order flow", "test a spoofing rule".)
- **What data do you have?** — **`multiSelect: false`** (exactly one); route accordingly:
  - **No data / don't want to use real data** → **synthetic** (§3). Recommended default —
    lowest risk, fully automatable.
  - **Real data I need the behavioural fidelity of** → **masking** (§4). Confirm they understand
    masked output is still personal data (pseudonymised ≠ anonymous, GDPR) and must stay governed.
  - **Already masked / already synthetic** → skip to validation (§5) / straight to analysis.

## 2. Recommend the safe default
Unless real-data fidelity genuinely matters, **recommend synthetic.** State the trade-off
plainly so the user chooses with eyes open, then proceed with their decision.

## 3. Synthetic path (automatable)
- **Built-in generator:** `python -m scripts.gen_synthetic --kind <kind> --out data/synthetic/<name>.jsonl`.
  Check `--kind` choices first; if the user's scenario isn't covered, this is a small build
  task — route to **platform-engineer** / **data-analyst** to extend the generator, *then* run it.
- **Fit-and-sample:** for data shaped like an existing non-raw corpus, use `scripts.synthesise`
  (`fit → sample`). The `fit` step reads its input corpus, so only fit on synthetic or
  already-governed data — **never** point it at `data/raw/`.

## 4. Masking path (run is automatic; config needs a human)
The mechanics auto-run, but three prerequisites are the user's to supply — confirm each:
1. **Raw file placed in `data/raw/`** — agents are walled off from it; that's deliberate.
2. **`MASKING_KEY` set** — check **presence only**, never print the value:
   `test -n "$MASKING_KEY" && echo "MASKING_KEY: set" || echo "MASKING_KEY: unset"`. If unset,
   ask the user to source it from `~/.secrets`. There is **no insecure default** — ingest
   refuses to run without it.
3. **`config/masking-schema.yaml` mapped to the user's fields.** You cannot derive this by
   reading the raw data (the guard blocks it). Instead **ask the user for their column/field
   list** and, for each field, ask: tokenise (ID), shift (timestamp), redact (free text),
   generalise, or keep? Draft the schema with `Write`/`Edit` from their answers, recording a
   one-line rationale per field. Declare any direct identifier explicitly under
   `direct_identifiers:` so validation can enforce it.

Then run:
```
python -m scripts.ingest --in data/raw/<file>.jsonl --out data/masked/<file>.jsonl
```
Per-record failures are reported by **row index only** (never record content — §5).

## 5. Validate — the gate before any agent sees the data
Always run `python -m scripts.validate_masking`. It must show **no residual identifiers/PII in
any output field** and **identical detection results on masked vs. original**. If it fails,
fix the schema and re-run — do **not** hand the data on until it passes.

> ⚠️ Lexical/regex redaction is best-effort and order-sensitive; free-text comms needs NER
> before real data. String-matching guards are advisory for `Bash` — the real boundary is the
> `permissions.deny` list, `data/raw/` in `.gitignore`, and masking-at-source (see
> `docs/house-rules.md`).

## 6. Close — don't dead-end (CLAUDE.md §6)
Confirm what's ready (the governed dataset path + validation result), then offer the next step
with a recommendation — typically straight into the analysis the user wanted (`/engage`,
`/new-scenario`, or `data-analyst`/`ml-engineer` for anomaly work) **pointed at the governed
data**, never the raw file. Offer to carry it out and wait for the go-ahead.
