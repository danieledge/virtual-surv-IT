---
name: Review Lens Router
---

> **Source & licence.** Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) —
> <https://github.com/turingmindai/turingmind-code-review>. The progressive-loading router
> pattern is theirs; the regulated lenses and language set are ours. See `THIRD-PARTY-LICENSES.md`.

Selects which **review lenses** (`docs/review/lenses/*`) to load for a given target. Loading
*only* the relevant lenses keeps signal high and cost low — don't run the Java lens on a Python
diff. The review skills (`/deep-review`, `/audit-review`) and `code-reviewer` use this.

## Selection matrix

| Detected in the target | Load lens |
|---|---|
| Any code (always) | `lenses/bugs.md`, `lenses/security.md` |
| `.py` | `lenses/language-python.md` |
| `.ts .tsx .js .jsx .mjs .cjs` | `lenses/language-typescript.md` |
| `.scala .sc` | `lenses/language-scala.md` |
| `.sql` (or embedded SQL) | `lenses/language-sql.md` |
| `.java` | `lenses/language-java.md` |
| `.ps1 .psm1 .psd1` | `lenses/language-powershell.md` |
| `.sh .bash` | `lenses/language-bash.md` |
| Deep / audit mode | `lenses/architecture.md` (adds Medium findings + arch notes + impact) |
| Detection logic / thresholds touched | hand to `compliance-reviewer` for the §4/§5 trail |

## Progressive loading

```
1. Detect languages   → file extensions in the target / git diff
2. Pick depth/mode    → quick (change) vs deep/audit (keep pre-existing, +architecture)
3. Load minimum lenses→ core (bugs+security) + per-language + architecture (deep)
4. Run lenses in parallel (each blind to the others → catches more), then merge + dedupe
5. Score & filter     → docs/code-review-method.md  (mechanical; cheap tier)
6. Morgan challenges  → independently re-scores, downgrades/filters, then presents
                        the scoreboard (console) + the clean artifact
```

## Model tiering (per `code-review-method.md` / CLAUDE.md §8)

**Today (as wired):** `code-reviewer` (opus) runs the lens passes, scoring and filtering in one
agent; **Morgan** (opus) does the challenge pass. The mechanical steps are kept lightweight, but
they are *not* yet on a separate cheap tier.

**Target (the real saving — not yet wired):** route the rote steps — language/context detection,
confidence arithmetic, count/filter bookkeeping — to a dedicated **haiku** context/scorer agent,
run the dimension lenses as **sonnet** sub-agents, and reserve **opus** for Morgan's challenge
and the §4/§5 judgement. Until that agent exists, don't claim the split is active — see the
roadmap note in `code-review-method.md`.

## Adding a lens
Create `docs/review/lenses/language-<name>.md` (same shape as the others: frontmatter with
`applies_to`, a Checks list, and "use the shared `docs/review/output-format.md`"), then add a
row to the matrix above. Don't duplicate the output format in the lens — reference it.
