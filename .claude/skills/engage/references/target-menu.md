# Review-target menu - LOCKED construction (read when the target must be asked)

> Use **exactly** these options and descriptions - do not improvise, reword, add or drop
> (2026-08-17 user decision: "it changes nearly every time in some way" - the same drift
> class the locked review menu closed). `scripts/locked_menu_guard.py` mechanically blocks
> a divergent `Target` question - don't rely on it instead of following this file.

**This question fires ONLY when the target is underivable** (`deep-review` step 2): an
uncommitted/branch diff or a path named in the request IS the target and is stated, not
asked. When it does fire, it rides the 0a intake batch in the Work-type slot when that
batch is being asked; standalone only when the batch already ran.

**This menu IS the diff-vs-full coverage choice (2026-08-20)** - the first two options are
"what's changed", **Whole working directory** is the full review, and a named path is a
bounded full review of that path. **Never build a separate "Scope" or "diff vs full"
question beside it**: the axes are identical, `AskUserQuestion` caps at four questions, and a
second screen is the post-gate scope-question defect (incident-log #33). When the target is
derivable, scope is stated in the priced message instead (`review-menu.md`). Cost and
coverage for each option belong in that accompanying chat text, never inside the locked
option wording below. On a clean tree with nothing uncommitted, mark the full option
`Whole working directory (Recommended)` - the guard's `_strip_recommended` already tolerates
that suffix, so it needs no guard change.

**Q - "What should the review cover?"  (header `Target`, single-select):**

| Label | Description (use ~verbatim) |
|---|---|
| **Uncommitted changes** | Everything changed but not yet committed (staged + working tree). *Best for "am I OK to commit?"* |
| **Branch vs main** | Everything this branch changed vs the default branch. *Best before a PR/merge.* |
| **Whole working directory** | ALL code under the project folder - not just changes, tracked or not. *Best for a first look at a dropped-in codebase, or an audit.* |
| **A file or folder I'll name** | One part of the codebase - reply with the path ("Other" also takes it directly). |

**The ONE permitted variation:** in a working directory that is **not a git repo**, the
first two options are meaningless - the menu is the last two only. No other variation
exists; exotic targets ("changes since tag X", "the files I attached") go through the
question's automatic **Other**, never an invented option.

**Rules:**
- **Empty pick** (e.g. Uncommitted chosen but the tree is clean): say "nothing
  uncommitted here" and re-ask the same menu - never invent scope to have something to do.
- **Whole working directory** inherits map-first scoping (`deep-review` step 3): the
  inventory comes from `docs/codebase-map.md` or `git ls-files`, never a breadth-first
  crawl, and the sizing line prices the whole-repo pass honestly before the gate.
- The chosen target is restated in the priced review-menu message ("Target: whole working
  directory, ~120 files") - corrections happen there, not on a new screen.
