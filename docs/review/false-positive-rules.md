---
name: False Positive Filtering Rules
---

> **Source & licence.** The filtering approach is adapted from **turingmind-code-review**
> (MIT, © 2026 TuringMind) — <https://github.com/turingmindai/turingmind-code-review>. The
> regulated exceptions (§4/§5), the evidence-basis requirement and the 🔵 style-&-form lane are
> ours. See `THIRD-PARTY-LICENSES.md`.

**Canonical content lives in [`docs/code-review-method.md`](../code-review-method.md)** — the
confidence-scoring rubric, the report/filter thresholds, the "always filter out" list, the
"never filter (regulated §4/§5)" exceptions, the 🔵 style-vs-filter distinction, and the
evidence-basis rule are all defined there in one place. This file is kept only so existing
references resolve and the turingmind attribution is recorded; **don't restate the rules here** —
read the method doc. The three things that most often trip people up:

- **Never filter** secrets, real PII/MNPI/raw data (§5), or an undocumented threshold / broken
  alert→logic→obligation trace (§4) — even if pre-existing or silenced.
- **🔵 style & form is not a filter** — meaningful suggestions are *reported* (non-blocking,
  "consider in future"), not hidden in the filtered count.
- **Evidence basis** — an unverified finding is reported and labelled 🧠 inferred, never dropped
  for lacking a measurement and never dressed up as 📊 measured.
