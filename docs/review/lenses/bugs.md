---
name: Bugs & Logic Errors
model: sonnet
---

> Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Focus on significant bugs that would cause runtime failures or **wrong detection results**.
Avoid nitpicks (those are 🔵 style/form or filtered).

## Checks

- **Null/None access** — missing guards before attribute/element access.
- **Off-by-one** — loop bounds, slice indices, window edges.
- **Race conditions** — concurrent access without synchronisation; non-atomic read-modify-write.
- **Resource leaks** — unclosed files, connections, cursors, subscriptions.
- **Error handling gaps** — swallowed exceptions, bare `except`, unhandled rejections.
- **Infinite loops / non-termination** — missing base case or break.
- **State mutation** — unexpected side effects, mutating shared/aliased state.
- **Detection-logic correctness (this domain)** — would the change cause a **missed alert**
  (false negative) or a **false alert** (false positive)? Wrong threshold comparison
  (`>` vs `>=`), boundary handling, timezone/epoch mistakes, dropped records in a filter. These
  rank as high-confidence bugs because they break surveillance coverage.

## Output

Use the shared format in `docs/review/output-format.md`: per finding a `diff`-style fix +
"why this works", a confidence score (`docs/code-review-method.md`), and an **evidence basis**
(📊 measured — e.g. a failing test / explicit value — vs 🧠 inferred from the code). Defer §4/§5
regulated findings to `compliance-reviewer`. Don't duplicate the output format here.
