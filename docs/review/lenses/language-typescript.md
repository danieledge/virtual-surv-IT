---
name: TypeScript/JavaScript Issues
model: sonnet
applies_to: ["*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs"]
---

> Vendored from **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Language-specific checks for TypeScript and JavaScript (review tooling, dashboards, Node glue).

## Checks

### Type safety
- Implicit `any`; type assertions without validation (`as Type`); missing null checks before
  access; non-null assertions (`!`) without justification.

### Async / await
- Missing try-catch around `await`; unhandled promise rejections; floating promises (missing
  `await`); `async` function with no `await`.

### Common pitfalls
- `==` instead of `===`; mutable default parameters; modifying objects during iteration;
  missing dependency arrays in hooks.

### Performance
- Creating functions/objects in render; missing memoisation for expensive computations; N+1
  queries in loops.

## Output

Use the shared format in `docs/review/output-format.md`: `file:line`, confidence, evidence
basis (📊 measured / 🧠 inferred), and a `diff`-style fix + "why this works". Drive
ESLint/`tsc`/`semgrep` where available. Defer §4/§5 to `compliance-reviewer`.
