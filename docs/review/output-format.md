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

## Console scoreboard (the ONLY thing shown by default)

By default the console shows **just the scoreboard** — nothing else. Full findings, diffs and
evidence go to the artifact; the terminal can't collapse our own prose, so we keep it minimal
and let the user choose to expand. (The harness already collapses noisy *tool* output itself.)

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

Then **offer to expand, don't dump** — via the question tool: *"Show full findings inline, the
🔴 criticals only, or just open the artifact?"* Only print detail to the console if the user
asks. Default = scoreboard + the pointer.

**Console cleanliness (hard rule).** Never print **code blocks, `diff` fixes, or large tables**
to the console — they're noise in a terminal and belong in the artifact. The console gets the
scoreboard and, at most, one-line finding titles (`🔴 file:line — short title`). Clean and
readable over complete; completeness lives in the file.

**In the `.html` artifact, make heavy sections collapsible** with `<details><summary>…</summary>`
(filtered issues, architectural notes, per-finding diffs) so a browser reader gets true
hide-by-default / click-to-expand. (These render as plain text in the terminal — that's fine,
the terminal only ever sees the scoreboard.)

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

### 🔵 Style & form — non-blocking, **for future consideration** *(ALWAYS include this section)*
Meaningful idiom / readability / naming / decomposition / documentation a senior engineer
would raise — **never blocks a verdict, never inflated into a Warning.** Distinct from 🔇.
Per-item:
```markdown
### 🔵 {{title}}  ·  `{{file}}:{{line}}`
{{suggestion}} — *consider in future work.*
```
**This section is mandatory even on a clean review.** Always end it with a short
**"General considerations for future code"** — 2–4 sentences of constructive, developer-friendly
guidance on the *original coding style overall* (patterns, structure, naming, testing/docs
habits) and how the author could improve next time. If the code is genuinely strong, say so and
name what's done well. The point is the developer always leaves with something to learn, not just
a pass/fail.

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
