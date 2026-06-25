# Coding standards - documentation, comments & cleanliness

How code in this repo is documented and kept clean. Builders follow it; `code-reviewer`
enforces it (flags gaps and, when fixes are in scope, adds the missing docs). It implements
CLAUDE.md §4 - concrete and checkable.

> **No metadata header blocks.** We do **not** put `@author` / `@version` / changelog banners in
> files - git is the reliable source of truth for authorship, version and history, and
> hand-maintained banners go stale and mislead. Documentation lives in **docstrings** (below).

## 1. Docstrings - lean, not ceremony

Every **module, public class and public function** has a docstring stating **purpose,
inputs/outputs, and assumptions** (plus what it raises / side-effects where relevant). Lean:
say what a caller needs and stop - don't restate the signature or pad it.

**Cover:**
- **Purpose** - what it does and *why it exists* (the intent, not a paraphrase of the code).
- **Inputs/outputs** - parameters (meaning + units/format where non-obvious) and the return.
- **Assumptions & contracts** - preconditions, invariants, what it does *not* handle, raises.
- **Detection logic (this domain)** - for a rule/scenario: the behaviour it detects and the
  **regulatory obligation** it serves (the alert→logic→obligation trace, §4).

**Skip:** trivial private one-liners whose name already says everything; getters/setters;
restating types the signature gives.

## 2. Comments - explain the *why*, not the *what*

- Comment **non-obvious or complex logic** with the reasoning a future maintainer needs - the
  *why*, the trade-off, the edge case - never a line-by-line narration of obvious code.
- **Every threshold/parameter carries its rationale and tuning date** (CLAUDE.md §4) - a
  hard-coded number without a comment explaining why is a review finding.
- Prefer making the code self-explanatory (good names) over a comment that compensates for a
  bad one. A comment that just restates the code is noise - delete it.
- Keep comments **current**: a wrong comment is worse than none. Update them with the code.

## 3. Cleanliness - best practice that makes review cheap

- **Clear names** over abbreviations; intention-revealing.
- **Small, single-purpose** functions; avoid deep nesting (guard clauses / early returns).
- **No dead code, no commented-out blocks** (git has the history), no duplicated logic.
- **Explicit error handling** - no bare `except:` / swallowed errors; fail loudly or handle
  deliberately.
- **No magic numbers/strings** - name them, and (for thresholds) document them (§4).
- Match the surrounding file's style, idioms and comment density - consistency over preference.

## 4. Per-language docstring/header convention

| Language | Convention |
|---|---|
| Python | Module + function **docstrings** (`"""…"""`), PEP 257; type hints on public signatures |
| TypeScript/JS | **TSDoc/JSDoc** (`/** … */`) on exported functions/classes |
| Java | **Javadoc** (`/** … */`) on public types/methods |
| Scala | **Scaladoc** (`/** … */`) on public defs/classes |
| PowerShell | **Comment-based help** (`<# .SYNOPSIS .PARAMETER .OUTPUTS #>`) on functions/scripts |
| Bash | A short **purpose comment block** at the top of the script (what it does, usage, key env vars); function-level comments where logic isn't obvious |
| SQL | A leading comment on views/procs/complex queries: purpose, key assumptions, and the detection/report it serves |

## 5. Review hook
`code-reviewer` checks every change against this file: missing/weak docstrings, thin or
redundant comments, undocumented thresholds (§4), and cleanliness issues are reported (as
🔵 style/form when non-blocking, or higher when they obscure correctness/auditability). When
fixes are in scope, it adds clear, meaningful docs - never redundant noise.
