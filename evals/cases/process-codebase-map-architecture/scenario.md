# Scenario (synthetic): closing a review - what goes in the codebase map?

You are Morgan, closing a **Deep code review** of an existing single-file transaction-
monitoring detector, `structuring.py`, in a client working project. What the review
established about the code:

- It reads a day's transactions from a CSV, **groups them per customer per day**, sums the
  amounts, and flags any customer whose daily total crosses a threshold (a structuring /
  smurfing pattern).
- The threshold is a **hardcoded `9000`** in the code (`structuring.py:31`), no config, no
  rationale recorded.
- Aggregation is a **naive per-customer Python loop** (`structuring.py:44`) - fine for the
  sample, but it re-scans the full list per customer.

The review raised two 🟠 Warnings (the hardcoded threshold; the loop's scalability) and one
🔵 developer-guidance note. Those are written up in the review artifact.

You are now at close and must update the working project's **codebase map**. Describe the
**map entries** (§2) you will write, and state clearly what belongs in those entries and what
does not.

*(Synthetic scenario - the file, lines and figures are invented for this eval.)*
