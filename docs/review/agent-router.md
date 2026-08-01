---
name: Review Lens Router
---

> **Source & licence.** Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) -
> <https://github.com/turingmindai/turingmind-code-review>. The progressive-loading router
> pattern is theirs; the regulated lenses and language set are ours. See `THIRD-PARTY-LICENSES.md`.

Selects which **review lenses** (`docs/review/lenses/*`) to load for a given target. Loading
*only* the relevant lenses keeps signal high and cost low - don't run the Java lens on a Python
diff. The review skills (`/deep-review`, `/audit-review`, `/security-audit`) and `code-reviewer`
use this. `/security-audit` loads the **security + per-language + architecture** lenses and drives
them hard (it skips the general bugs/style breadth - that is `/deep-review`'s job).

> **This file is canonical for the review pipeline's shape**: which lenses load, and **how they
> execute**. `docs/code-review-method.md` is canonical for *how findings are scored and filtered*;
> `docs/review/output-format.md` is canonical for *what the user sees*. Don't restate the pipeline
> topology elsewhere - link here.

## Two words that look alike: **lens file** vs **review dimension**

They are not the same thing, and the counts differ, so name them precisely:

- A **lens file** is one of the ten reference files in `docs/review/lenses/`: `bugs.md`,
  `security.md`, `architecture.md`, and seven `language-*.md`. These are what the router
  *loads* - reference material, selected by the matrix below.
- A **review dimension** is one of the seven scope axes the user picks in `/deep-review`'s
  Dimensions question: bugs & logic · security · architecture · language-specific ·
  docs/comments · style & form · compliance/audit. These are what the review *covers*.

The mapping is not one-to-one: bugs, security and architecture each have their own lens file;
"language-specific" resolves to whichever of the seven `language-*.md` files the target needs;
and docs/comments, style & form and compliance/audit have **no lens file** - they come from
`docs/code-review-method.md` (scoring, the 🔵 style-and-form band) and from `compliance-reviewer`
for the §4/§5 trail.

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
4. Run lenses      → SEQUENTIAL focused passes inside code-reviewer, one lens at a time
                        (full attention per lens), then merge + dedupe
5. Score & filter     → docs/code-review-method.md  (mechanical; cheap tier)
6. Morgan challenges  → spot-checks, not re-scores (every Critical, anything regulated,
                        anything with a thin evidence basis, plus a sample of the rest),
                        downgrades/drops what fails, then presents the scoreboard
                        (console) + the clean artifact
```

## Model tiering (per `code-review-method.md` / CLAUDE.md §8)

- **Haiku** - `review-scorer` does the rote steps: language/context detection, lens selection,
  confidence arithmetic, and the Found/Reported/Filtered bookkeeping.
- **Sonnet** - the lens passes themselves (per-language / per-dimension), as run by
  `code-reviewer`.
- **Opus** - `code-reviewer`'s judgement on findings + **Morgan's** challenge pass and the
  §4/§5 regulated calls.

So the cheap, high-volume steps run cheap and only the genuine judgement pays opus.

**Execution topology as shipped (the canonical statement).** The lens passes run **inside
`code-reviewer`, sequentially**: one lens at a time, so each gets full attention. They are **not**
fanned out to parallel sub-agents today. The consequence is stated rather than glossed: a single
agent cannot be blind to its own earlier passes, so the "each lens is independent, therefore it
catches more" property does **not** hold here - real independence would need separate agents, which
this pipeline deliberately does not spend. Running the lenses as separate **sonnet** sub-agents
remains an optional next step, not current behaviour. What *is* delegated today is the mechanical
work: context detection, lens selection and scoring go to `review-scorer` (haiku).

## Adding a lens
Create `docs/review/lenses/language-<name>.md` (same shape as the others: frontmatter with
`applies_to`, a Checks list, and "use the shared `docs/review/output-format.md`"), then add a
row to the matrix above. Don't duplicate the output format in the lens - reference it.
