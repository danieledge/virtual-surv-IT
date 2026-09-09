# Resolved known issues - the archive

Previously reported issues that are resolved or fully mitigated, moved out of the README's
Known issues section (which keeps only genuinely open items). Each entry is preserved
verbatim as it stood in the README, with a resolution note on top. Partially-mitigated
items stay in the README with their open part stated.

---

## Persona / soft-discipline fade on long sessions

> **Resolution:** fully mitigated in **0.27.0** (ADR-005) by the dormancy-aware per-turn
> re-anchor hook (`scripts/persona_anchor.py`), which ships wired in both hook files;
> archived from the README 2026-07-30. The residual cosmetic name-drift quirk remains
> listed in the README's display-only quirks.

**The persona and soft discipline can fade on a long session (mitigated since 0.27.0 by the re-anchor hook).** The
`/engage` persona - Morgan's voice, the 🎩 marker, the named specialists, the prompt-enforced
discipline (question-tool, the fix-list gate) - loads **once** when you type `/engage` and is
**never re-asserted**; it lives only in the conversation history. On a long engagement, or after
Claude Code **compacts/summarises** the context, that history erodes and the model drifts back
toward default Claude Code: plain voice, generic "Agent A/B/C" subagent labels, the wrong-name
drift below. **What is NOT affected:** the hard controls - the raw-data block, the execution-
consent gate and the consent-write gate - are enforced by Claude Code **hooks**, independent of
the model's persona, so they hold regardless of how faded Morgan is (the critical rails were put
in hooks precisely for this). What decays is *presentation* and *soft* discipline. **Mitigation
now:** re-invoke `/engage` (or `/meet-the-team`) to reload the persona, and don't let a single
engagement run excessively long. **Fix implemented (0.27.0, ADR-005):** a dormancy-aware
re-anchoring hook - `scripts/persona_anchor.py`, a per-turn `UserPromptSubmit` hook that re-injects
a tiny (≤8-line) persona+discipline anchor **only while an engagement is live** (open/blocked
START-HERE), so it survives compaction yet stays silent in ordinary sessions. It ships wired
in both hook files - no setup needed. Same root cause as the
name-drift quirk below, which the anchor also mitigates.

*("below" in the verbatim text refers to the README's display-only quirks fold, where the
cosmetic name-drift entry still lives.)*

---

## Two escape paths from the 2026-08-01 audit (closed; moved out of the README 2026-09-10)

Hook and guard files are model-blocked by design, so a fix the team writes sits staged until
the user installs it. Both were found by the audit on 2026-08-01, both were applied, and the
live hooks in `.claude/hooks/` are byte-identical to their staged counterparts (verified
2026-09-09, with `tests/test_guard_git_config.py` and `tests/test_guard_raw_coverage.py`
passing, 112 tests).

They sat in the README as "staged, pending, not done" for some time after they were in fact
live, with the git-config one saying its regression net "fails until applied". That is the
wrong direction for an error to run in a security-sensitive product: it understated the
shipped posture. Kept here because the paths themselves are worth knowing about.

- **The git config file was an unguarded consent-equivalent execution path.** Pointing the
  hooks path at a directory of your own, or setting an external diff/merge driver, hands the
  next plain `git commit` or `git diff` arbitrary execution with no consent marker written
  and no gate consulted. The improved consent-write guard covers it, with a regression net in
  `tests/test_guard_git_config.py`. Applied via `bash scripts/apply-guard-git-config.sh`.
- **Raw-data guard coverage gaps.** `WebFetch` resolves `file://` URLs against the local
  filesystem but sat outside the guard's fixed tool set (ADR-002 rec 22 rated that gap
  architectural rather than live: with `WebFetch` present, it was live), and a `Grep` rooted
  at a parent directory or with no path at all descends into the raw-data directory while
  naming a path that does not resolve under it (recs 7 and 15). Both are covered by the live
  raw-data guard, with `tests/test_guard_raw_coverage.py` as the regression net. Applied via
  `bash scripts/apply-guard-raw-coverage.sh`; `WebFetch` is wired into both hook files.
