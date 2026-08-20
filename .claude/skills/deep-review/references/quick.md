# Quick review - the complete recipe (read INSTEAD of the deep-review pipeline)

> Loaded by `deep-review/SKILL.md` when the chosen depth is **Quick** (token plan Phase 4,
> 2026-08-18: a Quick run loads this file and nothing else of the pipeline - no subagent, no
> workspace, no scorer round-trip; the evidence machinery is what Deep and Audit buy). A
> Quick "am I OK to commit?" costs cents this way instead of a subagent chain.

**Scope - turingmind-style, in-session (2026-08-17 cost decision).** Diff-scoped by default
(`git diff`, changed code only - pre-existing issues out of scope). **Nothing to diff?** A
NAMED target (a file, a small module) takes the diff's place - same in-session mechanics over
that one bounded read - but if the named target won't sit comfortably in one context, that was
never a Quick question: offer Deep instead of silently ballooning the read. No diff AND no
named target = nothing to review: say so and ask what they want looked at (question tool) -
never invent scope to have something to do.

**State the scope and its exclusion in one line before running** (2026-08-20, same rule the
deep path follows): *"Reviewing what's changed - 12 files. Not covered: the other 180 files
here; a pre-existing issue outside the diff won't be seen."* A count, never a listing. Omit the
second half when nothing is excluded. Quick is diff-or-one-bounded-target by design, so a
"full review at Quick depth" is not on offer - that request routes to Deep, per the scope
rule above.

**Run it yourself, in this session:**
1. **Analysers first, if available** - only the tools the step-0 probe reported present for
   the languages in scope, run once over the diff/target; their hits ground the passes and
   are 📊 measured. (Tool set and caveats: `code-reviewer.md`'s table is the single source of
   truth; Semgrep/pip-audit stay excluded.)
2. **Lenses inline** - the router's selected lenses (`docs/review/agent-router.md`) read and
   applied sequentially over that one scope.
3. **Score in-context** against `docs/code-review-method.md`'s rubric and present with the
   honest label **"quick-tier: self-scored, no independent scorer at this depth"**. Never
   filter regulated findings (secrets, PII/raw data §5, undocumented thresholds / broken
   traceability §4).
4. **🔴/🟠 to the console** (clean scoreboard, no dumps); artifact only if asked.

**Close:** summarise, then offer next steps with a recommendation. If Quick surfaces
something structural, offer the Deep upgrade - never silently deepen. Always include
`/security-audit` among the options and recommend it when the change touched a
security-sensitive surface (auth, input parsing, DB access, external I/O, crypto, secrets,
PII/data handling) or any security finding surfaced.
