# Review-target menu - LOCKED construction (read when the target must be asked)

> Use **exactly** these options and descriptions - do not improvise, reword, add or drop
> (2026-08-17 user decision: "it changes nearly every time in some way" - the same drift
> class the locked review menu closed). `scripts/locked_menu_guard.py` mechanically blocks
> a divergent `Target` question - don't rely on it instead of following this file.

**This question fires ONLY when the target is underivable** (`deep-review` step 2): an
uncommitted/branch diff or a path named in the request IS the target and is stated, not
asked. When it does fire, it rides the 0a intake batch in the Work-type slot when that
batch is being asked; standalone only when the batch already ran.

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
