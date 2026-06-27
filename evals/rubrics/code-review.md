# Rubric: code review (`/deep-review`, `/audit-review`)

The judge scores a code-review output 0.0-1.0 + pass/fail across the dimensions below. The
deterministic scorer (`eval_score.py`) handles **recall / must-find / FP-traps** from the case
manifest; this rubric covers what it can't.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Detection** | Every planted 🔴 Critical surfaced at the right severity; criticals not buried under nits. *(deterministic: recall + must-find)* | 0.35 |
| **No false alarms** | No false-positive trap flagged; correct, documented code not called a bug. *(deterministic: FP-traps)* | 0.15 |
| **Evidence basis** | Each finding tagged 📊 measured / 🧠 inferred; no inference presented as fact; file:line cited. | 0.15 |
| **Actionability** | Each finding has a concrete, correct fix - not just "this is bad". | 0.15 |
| **Severity discipline** | Severities are defensible (a hardcoded secret is Critical, a naming nit is Style); the scoreboard isn't inflated. | 0.10 |
| **Developer guidance** | The mandatory "improving future code" section is present and substantive. | 0.10 |

**Pass:** all planted criticals found, zero FP-traps triggered, and weighted score >= 0.75.
**Auto-fail:** any inference presented as measured fact; any planted critical missed; a real
secret/PII in the output.
