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
1. Detect languages   → review-scorer's own procedure: file extensions in the target / git
                        diff. code-reviewer/compliance-reviewer reuse review-scorer's already-
                        detected file list/language breakdown when their dispatch brief already
                        has it (the standard pipeline's step 1, see deep-review/SKILL.md) rather
                        than re-deriving it themselves via their own git diff (2026-08-12)
2. Pick depth/mode    → depth (quick vs deep, +architecture) and mode (change vs audit, keep
                        pre-existing) are independent axes - typically quick+change and
                        deep+audit, but not fixed pairs (`docs/code-review-method.md`)
3. Load minimum lenses→ core (bugs+security) + per-language + architecture (deep)
4. Run analysers      → ONCE, up front, inside code-reviewer - only the tools the step-0
                        probe reported available (code-reviewer.md's table is the single
                        source of truth); their output grounds every lens pass, so a tool
                        hit is cited 📊 measured rather than rediscovered 🧠 inferred
5. Run lenses         → SEQUENTIAL focused passes inside code-reviewer, one lens at a time
                        (full attention per lens), each grounded in step 4's analyser
                        output, then merge + dedupe
6. Score & filter     → DELEGATE to review-scorer (haiku), rubric in
                        docs/code-review-method.md - a reviewer self-scoring its own
                        pack is a pipeline defect, not a fallback
7. Morgan challenges  → spot-checks, not re-scores (every Critical, anything regulated,
                        anything with a thin evidence basis, plus a sample of the rest),
                        downgrades/drops what fails, then presents the scoreboard
                        (console) + the clean artifact
```

## Model tiering (per `code-review-method.md` / CLAUDE.md §8)

- **Haiku** - `review-scorer` does the rote steps: language/context detection, lens selection,
  confidence arithmetic, and the Found/Reported/Filtered bookkeeping.
- **Opus** - `code-reviewer`, end to end: the lens passes run inside it (topology below), so
  they ride its tier along with its judgement on findings and the §4/§5 regulated calls.
- **Morgan's challenge pass** - the orchestrator's own tier: sonnet by default, opus when
  configured for the engagement (operating guide §Orchestration discipline).

So the rote, high-volume steps run cheap and the genuine judgement pays the top tier.

**Execution topology as shipped (the canonical statement, revised 2026-09-13).** At **Deep and
Audit** depth the review fans out into **parallel per-facet `code-reviewer` passes** - security,
correctness & bugs, and (Deep/Audit only) architecture - each a FRESH context over the whole
in-scope files, running only its facet's lens(es), then merged and deduped. This is the real
independence that makes parallel review catch more: separate agents are not blind to each other's
passes, which is exactly the property a single sequential pass could not have. A **verification
pass** then adversarially re-tests each surviving Critical/High finding - the false-positive
filter the scorer + PM-challenge lacked. At **Quick** depth the lenses still run **sequentially
inside one `code-reviewer`** (references/quick.md), right for a fast diff-scoped check. The
mechanical work - context detection, lens selection, scoring - goes to `review-scorer` (haiku)
throughout.

**Adaptive scaling, not silent fan-out (revised 2026-09-13).** The facet count scales with the
change: a small diff folds correctness+security into one pass; a module-or-wider scope runs all
facets. **State the facet count and why before dispatching** - a live 2026-08-16/17 run sent 6
passes where 3 were priced, and the fix is a STATED, right-sized count, not a ban on parallelism
(opus is now ~1.67x sonnet, so the depth parallel passes buy is cheap). The per-COMPONENT split
(by file/module) still applies ON TOP when `large_context_review_split` is on, the target exceeds
one context, or corporate-proxy timeouts have bitten.

**Briefs carry scope, never invite discovery (2026-08-17).** Every dispatch brief names the
in-scope FILE LIST, and - when the project has one - `VSIT/shared/map.md`'s **path** with
"read it for wider context; do not enumerate the repo" (a live run had three parallel
reviewers each re-crawl a repo whose map already existed). **Point, never paste**: the map
body copied into N briefs is N times orchestrator output tokens, where an agent-side Read of
the same file is cheap input - and a diff-scoped pass needs no map read at all.

**Sequential means the lens order inside one call, not the dispatch across calls.** When a large
target is split into multiple component-scoped `code-reviewer` calls (operating guide
§Orchestration discipline), those calls are independent and dispatch **concurrently, in one
message** - the per-call lens order stays sequential within each. Serialising independent calls
across turns buys nothing (same tokens either way) and multiplies wall-clock time (live failure
2026-08-07: a 4-pass split dispatched one call per turn).

## Adding a lens
Create `docs/review/lenses/language-<name>.md` (same shape as the others: frontmatter with
`applies_to`, a Checks list, and "use the shared `docs/review/output-format.md`"), then add a
row to the matrix above. Don't duplicate the output format in the lens - reference it.
