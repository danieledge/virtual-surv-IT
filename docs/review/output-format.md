---
name: Review Output Format
---

> **Source & licence.** Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind) -
> <https://github.com/turingmindai/turingmind-code-review>. The scoreboard / filter-transparency
> / diff-fix format is theirs; the regulated-domain additions (evidence basis, the style-&-form
> lane, the §4/§5 never-filter rule, artifact-first output) are ours. See `THIRD-PARTY-LICENSES.md`.

The single canonical format for every team review (`code-reviewer`, the dimension lenses,
`/deep-review`, `/audit-review`, `/security-audit`). Scoring and filtering live in
`docs/code-review-method.md`; this file defines **what the user sees**. Two surfaces:

- **Console** → a clean, glanceable **scoreboard** (below). Never a wall of tables.
- **Artifact** → the full findings, diffs and evidence, written to
  `artifacts/REVIEW-<slug>.md` and rendered to `.html`. **Artifact-first**: detail goes to the
  file, the terminal gets the scoreboard + a pointer.

## Console scoreboard (the ONLY thing shown by default)

By default the console shows **just the scoreboard** - nothing else. Full findings, diffs and
evidence go to the artifact; the terminal can't collapse our own prose, so we keep it minimal
and let the user choose to expand. (The harness already collapses noisy *tool* output itself.)

```
Review - <target>            (deep · audit mode)
🔴 Critical    2
🟠 Warning     5
🟡 Medium      3
🔵 Style/form  4   (non-blocking - for future consideration)
🔇 Filtered    7
Found 21 · Reported 14 · Filtered 7
Disposition: ✅ 4 fixed · 🔴 2 open · ⚖️ 1 accepted    ← only after a fix/re-review loop
Verdict: ❌ not yet - 2 criticals still OPEN (see artifact)
→ Full findings + fixes: artifacts/REVIEW-<slug>.md  (.html rendered)
```

Then **offer to expand, don't dump** - via the question tool: *"Show full findings inline, the
🔴 criticals only, or just open the artifact?"* Only print detail to the console if the user
asks. Default = scoreboard + the pointer.

## Finding status (disposition) - never leave it ambiguous

A Pass/Fail verdict alone is not enough - the user must always be able to see **what was done
about each finding.** Every finding carries a **status**, and after any fix→re-review loop the
artifact shows a **disposition summary** (the tally above) and the verdict states **what remains
open**:

| Status | Meaning |
|---|---|
| 🔴 **Open** | not addressed - still stands |
| ✅ **Fixed** | resolved - say *what changed* (commit/diff/file) and that re-review confirms it |
| ⚖️ **Accepted** | risk-accepted / won't-fix - **with rationale and who accepted it** |
| ⏭️ **Deferred** | last resort only - can't be done now for a stated reason, with a tracking reference. **Not** for work you could fix in this pass |

**Fix-now is the default.** When fixes are in scope, fix everything you safely can *now* - don't
punt fixable items to a "next sprint". Use ⏭️ Deferred sparingly and only with a concrete reason
it can't be done in this pass; anything needing a human call is 🔴 Open (needs human review), not
deferred.

A **❌ Fail** must explicitly list the **Open** items (what's left to do), not just declare
failure. If findings were fixed during the engagement, say so per finding - don't make the user
guess whether anything was actioned.

**No straightforward fix? Say so - don't fudge.** If a finding has no safe, obvious fix (it
needs a design decision, domain knowledge, or a risky change), **do not invent or hand-wave
one.** Mark it **🔴 Open - needs human developer review**, state plainly *why* it's not
auto-fixable and what the options/trade-offs are, and leave it for a human. A plain "this one
needs a person" beats a confident wrong fix.

**Console cleanliness (hard rule).** Never print **code blocks, `diff` fixes, or large tables**
to the console - they're noise in a terminal and belong in the artifact. The console gets the
scoreboard and, at most, one-line finding titles (`🔴 file:line - short title`). Clean and
readable over complete; completeness lives in the file.

**In the `.html` artifact, make heavy sections collapsible** with `<details><summary>…</summary>`
(filtered issues, architectural notes, per-finding diffs) so a browser reader gets true
hide-by-default / click-to-expand. (These render as plain text in the terminal - that's fine,
the terminal only ever sees the scoreboard.)

## Artifact sections

Every reported finding carries: `file:line`, a **confidence** score (`docs/code-review-method.md`),
the **standard/tool** cited, an **evidence basis** (📊 measured / 🧠 inferred - never conflate),
a plain-language **Problem** explanation, a one-line **Impact if unaddressed**, and a concrete
**`diff`-style fix + "why this works."**

> **Problem and Impact are written for a reader who did not build the code and was not in the
> session** - a finding that only *names* the defect forces the reader to re-derive why it
> matters (a live engagement had to iterate the document for exactly this). **Problem** says
> what is wrong and how we know, in plain language. **Impact** states the consequence in the
> domain's terms - missed detections / false negatives, alert-volume or tuning effects,
> audit/regulatory exposure, data-integrity or operational cost - and carries its own 📊/🧠
> basis when the consequence is projected rather than observed. No finding ships without both.
> Together with **Likely cause** and the fix, the shape covers the audit profession's **5 C's**
> (criteria · condition · cause · consequence · corrective action): the standard-cited line is
> the criteria, Problem the condition, Likely cause the cause, Impact the consequence, and the diff
> the corrective action.
> **Present them as the five named fields above, each on its own line - the same five, every
> finding.** Do **not** collapse them into a dense inline "5-C summary" (less neat, harder to scan),
> and **never label a block "5C" while showing fewer than five.** A live report labelled every
> finding "5C Summary" yet the count **varied finding-to-finding** - some had all five, some four,
> some only three (Condition / Consequence / Correction, dropping criteria (the Standard) and cause
> (Likely cause)) - inconsistent, mislabelled, and run inline. Consistency is the point: the five
> fields appear, in order, on their own lines, for **every** finding. If you write a one-line recap,
> don't call it "5C" unless all five are present. Criteria = the **Standard** line; Cause =
> **Likely cause** (mandatory, never silent).
> **Worked exemplars to anchor on: [`gold-findings.md`](gold-findings.md).**

### 🔴 Critical (95-100) - must fix
```markdown
### 🔴 {{title}}
**Location:** `{{file}}:{{line}}`  ·  **Confidence:** {{score}}/100  ·  **Basis:** 📊 measured / 🧠 inferred
**Standard:** {{CWE / OWASP ASVS / CLAUDE.md §}}

**Problem:** {{what is wrong and how we know - plain language}}  (if inferred: the measurement that would confirm it)

**Likely cause:** {{why the gap exists - spec drift / config error / misunderstanding / regression; "undetermined - needs investigation" is allowed, silence is not}}

**Impact if unaddressed:** {{consequence in domain terms - detection gap / false negatives / alert volume / audit exposure / operational}}

**Fix:**
```diff
- {{old}}
+ {{new}}
```
*Why this works:* {{explanation}}
```

### 🟠 Warning (80-94) - should fix
Same shape as Critical.

### 🟡 Medium (70-79) - *deep / audit only*
Same shape; lighter.

### 🔵 Style & form - non-blocking, **for future consideration** *(ALWAYS include this section)*
Meaningful idiom / readability / naming / decomposition / documentation a senior engineer
would raise - **never blocks a verdict, never inflated into a Warning.** Distinct from 🔇.
Per-item:
```markdown
### 🔵 {{title}}  ·  `{{file}}:{{line}}`
{{suggestion}} - *consider in future work.*
```
**This section is mandatory even on a clean review.** Always follow it with the closing
guidance block under the exact heading `## 🔵 Developer guidance - improving future code`
(verbatim - the review skills mechanically check the artifact for it) - constructive,
developer-friendly guidance on the *original coding style overall* (patterns, structure,
naming, testing/docs habits) and how the author could improve next time. **Scale it to the change:** 2-4 points for a substantial review,
but a single plain sentence is fine on a trivial diff - don't manufacture filler. If the code is
genuinely strong, say so and name what's done well. The point is the developer always leaves with
something to learn, not just a pass/fail.

### 🧑‍💻 Prompting guidance - *only when AI-assisted / "vibe-coded" AND findings were raised*
Include this section **only if** (a) the author said at intake the code was AI-generated/vibe-coded,
**or** the findings plainly show it (no tests, hallucinated/non-existent APIs, inconsistent patterns,
missing error handling, plausible-but-wrong logic) - **and** (b) the review actually raised at least
one finding. On a clean pass, **skip it** (there's nothing to coach). Keep it constructive, not
preachy - the aim is a better *first draft* from the model next time, not just a fixed diff.

**Map the findings to the prompt (findings-driven, not generic).** Take the significant findings this
review raised, group near-duplicates into one row, and for each show the prompt change that would
have **closed** it:

| Finding (or cluster) | Why the prompt let it through | Prompt clause that would have closed it |
|---|---|---|
| *(example)* no false-positive test | the prompt never asked for one | "…include a true-positive AND a false-positive test." |
| *(example)* hard-coded threshold | no rationale/tuning date requested | "…comment each threshold with its rationale + tuning date." |
| *(example)* hallucinated API | model wasn't told to verify APIs exist | "…don't invent APIs; if unsure a function exists, say so and show how you'd verify it." |

Only include rows for findings the review **actually raised** - omit examples that don't apply.

**Reusable prompts.** Distil the rows into 2-3 prompts the author can keep and reuse on this kind of
work next time, e.g.:
- *"Implement <rule>; include a true-positive AND a false-positive test, and a comment giving each threshold's rationale + tuning date."*
- *"Before coding, list the edge cases (empty input, malformed row, ties, same-timestamp events) and handle each explicitly."*
- *"Cite the specific regulatory obligation this serves and carry it as a field on the alert record, not just in free-text."*

### 🔇 Filtered (transparency - counts, not findings)
| Reason | Count |
|--------|-------|
| Pre-existing (not in diff) | |
| Below confidence threshold | |
| Linter/formatter territory | |
| Silenced by comment | |

> **Never filtered (regulated):** secrets, real PII/MNPI/raw data (§5), an undocumented
> threshold or a broken alert→logic→obligation trace (§4) - reported even if pre-existing or
> silenced. See `docs/code-review-method.md`.

### 📐 Architectural notes - *deep only*
Pattern consistency · coupling · test coverage · dependencies (✅ / ⚠️ / ❌ each).

### 💥 Impact analysis - *deep only*
Affected files · blast radius · breaking changes.

### 🔬 Tooling coverage
Which analysers/profilers ran, which couldn't (and why) - so the review's confidence is
accurate. A claim with no executed evidence is 🧠 inferred; say so here rather than implying it
was measured.

### 🧾 Limitations & residual risk *(ALWAYS include - the audit skeleton's load-bearing section)*
What this review did **not** do, stated plainly: paths/modules out of scope, static-only basis
(nothing executed) and what that leaves unverified, analysers unavailable, assumptions made,
and any residual risk the reader accepts by relying on this review. A governance or audit
reviewer reads this section first; a review with an empty limitations section reads as
overclaiming, not as thorough.

## Icons
✅ good · ⚠️ needs attention · ❌ problem · 📊 measured · 🧠 inferred · 🔇 filtered

## No issues found
State it plainly - *"✅ No significant issues; clean for commit."* - and **still show the
filtered counts and the tooling-coverage line** so "clean" is evidenced, not assumed.
