---
name: Review Output Format
---

> **Source & licence.** Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) —
> <https://github.com/turingmindai/turingmind-code-review>. The scoreboard / filter-transparency
> / diff-fix format is theirs; the regulated-domain additions (evidence basis, the style-&-form
> lane, the §4/§5 never-filter rule, artifact-first output) are ours. See `THIRD-PARTY-LICENSES.md`.

The single canonical format for every team review (`code-reviewer`, the dimension lenses,
`/deep-review`, `/audit-review`). Scoring and filtering live in `docs/code-review-method.md`;
this file defines **what the user sees**. Two surfaces:

- **Console** → a clean, glanceable **scoreboard** (below). Never a wall of tables.
- **Artifact** → the full findings, diffs and evidence, written to
  `artifacts/REVIEW-<slug>.md` and rendered to `.html`. **Artifact-first**: detail goes to the
  file, the terminal gets the scoreboard + a pointer.

## Console scoreboard (always)

```
Review — <target>            (deep · audit mode)
🔴 Critical    2
🟠 Warning     5
🟡 Medium      3
🔵 Style/form  4   (non-blocking — for future consideration)
🔇 Filtered    7
Found 21 · Reported 14 · Filtered 7
→ Full findings + fixes: artifacts/REVIEW-<slug>.md  (.html rendered)
```

Optionally list 🔴/🟠 titles one line each beneath it. Keep tables, diffs and evidence in the
artifact.

## Artifact sections

Every reported finding carries: `file:line`, a **confidence** score (`docs/code-review-method.md`),
the **standard/tool** cited, an **evidence basis** (📊 measured / 🧠 inferred — never conflate),
and a concrete **`diff`-style fix + "why this works."**

### 🔴 Critical (95–100) — must fix
```markdown
### 🔴 {{title}}
**Location:** `{{file}}:{{line}}`  ·  **Confidence:** {{score}}/100  ·  **Basis:** 📊 measured / 🧠 inferred
**Standard:** {{CWE / OWASP ASVS / CLAUDE.md §}}

**Problem:** {{reason}}  (if inferred: the measurement that would confirm it)

**Fix:**
```diff
- {{old}}
+ {{new}}
```
*Why this works:* {{explanation}}
```

### 🟠 Warning (80–94) — should fix
Same shape as Critical.

### 🟡 Medium (70–79) — *deep / audit only*
Same shape; lighter.

### 🔵 Style & form — non-blocking, **for future consideration**
Meaningful idiom / readability / naming / decomposition / documentation a senior engineer
would raise — **never blocks a verdict, never inflated into a Warning.** Distinct from 🔇.
```markdown
### 🔵 {{title}}  ·  `{{file}}:{{line}}`
{{suggestion}} — *consider in future work.*
```

### 🔇 Filtered (transparency — counts, not findings)
| Reason | Count |
|--------|-------|
| Pre-existing (not in diff) | |
| Below confidence threshold | |
| Linter/formatter territory | |
| Silenced by comment | |

> **Never filtered (regulated):** secrets, real PII/MNPI/raw data (§5), an undocumented
> threshold or a broken alert→logic→obligation trace (§4) — reported even if pre-existing or
> silenced. See `docs/code-review-method.md`.

### 📐 Architectural notes — *deep only*
Pattern consistency · coupling · test coverage · dependencies (✅ / ⚠️ / ❌ each).

### 💥 Impact analysis — *deep only*
Affected files · blast radius · breaking changes.

### 🔬 Tooling coverage
Which analysers/profilers ran, which couldn't (and why) — so the review's confidence is
honest. A claim with no executed evidence is 🧠 inferred; say so here rather than implying it
was measured.

## Icons
✅ good · ⚠️ needs attention · ❌ problem · 📊 measured · 🧠 inferred · 🔇 filtered

## No issues found
State it plainly — *"✅ No significant issues; clean for commit."* — and **still show the
filtered counts and the tooling-coverage line** so "clean" is evidenced, not assumed.
