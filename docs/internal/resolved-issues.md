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
