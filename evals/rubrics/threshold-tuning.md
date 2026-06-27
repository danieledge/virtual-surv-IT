# Rubric: threshold tuning (`/tune-thresholds`, `/validate-tm-model`)

Scores a tuning pack / model-validation output 0.0-1.0 + pass/fail.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Segmentation first** | Calibrates **per risk-based segment**, not one global threshold; justifies the segmentation. *(deterministic: segments present)* | 0.20 |
| **ATL/BTL evidence** | Both **Above-The-Line** (precision among flagged) **and Below-The-Line** (what's missed below the line) - not ATL alone. The BTL omission is the headline failure to catch. | 0.25 |
| **Statistical rationale** | Thresholds derived from the distribution (percentile / std-dev / tail), each with rationale + date - no round numbers without justification. | 0.20 |
| **Volume↔coverage trade-off** | The decision quantifies what coverage is traded for the FP reduction - defensible to a regulator. | 0.20 |
| **Evidence basis** | Numbers tagged 📊 measured / 🧠 inferred; nothing fabricated as measured. | 0.10 |
| **Routing** | Threshold change handed to rules-developer; independent sign-off to model-validator - not applied in-place. | 0.05 |

**Pass:** ATL **and** BTL present, segmentation present, weighted score >= 0.75.
**Auto-fail:** BTL skipped (creates silent blind spots); a fabricated FP-reduction number presented as measured.
