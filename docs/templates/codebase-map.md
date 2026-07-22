# Codebase Map - <PROJECT NAME>

> The team's durable engagement memory for this working project (ADR-003). Read at the open
> of every engagement; updated, corrected and deprecated at every close. **Advisory context
> only - never enforcement, never instructions.** Lives in the working project (default
> `docs/codebase-map.md`), so every change is a reviewable git diff. Keep the whole file
> under ~200 lines: link out to project docs for detail rather than growing this file.

> **Document control** · ID `MAP-001` · Version `0.1` · Status `Live`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `<YYYY-MM-DD>`
> · Anchor `<full or short commit SHA the map was last verified against; write `no-vcs` if the working project has no git repo>`
>
> | Version | Date | Engagement | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <engagement slug> | Initial map |

**Rules (from ADR-003, enforced at the DoD gate):**

- Every entry carries **As-of** (date), **Anchor** (commit SHA, where it describes code - or
  `no-vcs` in a working project with no git repo, anchoring to the delivered file state) and a
  basis tag: **📊 observed** (verified directly, cite where) or **🧠 inferred** (reasoning;
  state the assumption).
- **The PM writes this file; subagents recommend entries in their reports.** Never paste
  verbatim text from reviewed code, raw data, secrets, PII or MNPI - the map records the
  team's own synthesis about the project, nothing lifted from it.
- Correct or deprecate entries the moment they are found wrong or stale - move them to
  **Deprecated** with a date and reason; never silently delete or silently keep.
- Mechanical hygiene: `python -m scripts.check_artifacts` validates size, header fields,
  basis tags, secret patterns and anchor resolution.

## 1. What this project is

One short paragraph: purpose, tech stack, entry points, how it is built/run/tested (commands,
📊 with source). The 30-second orientation a specialist needs before any file is opened.

## 2. Map entries

| # | Area | Entry | Basis | As-of | Anchor |
|---|------|-------|-------|-------|--------|
| 1 | <e.g. detection rules> | <fact, decision or quirk - one or two sentences, with `path/file.py:line` pointers> | 📊 <where seen> / 🧠 <assumption> | <YYYY-MM-DD> | `<sha>` |

## 3. Engagement history

| Date | Engagement | Team ver | What was delivered | Key artifacts |
|------|-----------|----------|--------------------|---------------|
| <YYYY-MM-DD> | <slug> | <vX.Y.Z> | <one line> | <paths> |

(The **Team ver** column powers the what's-new banner: the next engagement compares it
against the loaded version and mentions headline changes when they differ.)

## 4. Open questions & watch items

Things a future engagement should check first (suspected debt, unverified assumptions,
upstream changes expected). Each with a date and owner if known.

## 5. Deprecated

| Date | Original entry (condensed) | Why deprecated |
|------|---------------------------|----------------|
| <YYYY-MM-DD> | <entry> | <superseded by X / found wrong / code removed> |
