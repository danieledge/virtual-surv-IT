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

> **This is a map of the CODE, not a log of what the team did.** Each entry is a **durable
> fact about how the codebase is built** - one that will still be true next month, after this
> engagement's findings are fixed. Architecture, data flow, key decisions, quirks, sharp
> edges. The test: *would this help a specialist who opens the project cold next time?*
>
> **What belongs here** (durable): "parsing is fail-closed - a bad row raises a row-numbered
> error, no partial output (`parse.py:40`)"; "thresholds are hardcoded, not config-driven
> (`rules.py:22`)"; "detection groups by (trader, qty, price) then pairs within a 5s window".
>
> **What does NOT belong here** (engagement activity - it goes to §3 history + the review
> artifacts): ✅ *"thresholds are hardcoded in `rules.py:22`"* (a fact) — ❌ *"we reviewed the
> thresholds and reported a 🟠 finding this engagement"* (activity). Do **not** carry finding
> IDs, severities, review dispositions ("reported/open/fixed"), or "what we did this time"
> into an entry. A finding that gets fixed leaves the map; the durable fact it revealed (e.g.
> "thresholds are config-driven now, since 2026-07-22") stays.
>
> **Reviews & audits especially:** the engagement's output is *findings*, so it is tempting to
> write the map as a findings summary - don't. Capture the **architecture you learned by
> reading the code** (how it is built, its load-bearing decisions, its sharp edges); the
> findings live in the review artifact and their one-line trace in §3.

| # | Area | Entry (a durable code fact - NOT a finding or an activity note) | Basis | As-of | Anchor |
|---|------|-------|-------|-------|--------|
| 1 | <e.g. detection rules> | <how the code is built - fact, decision or quirk in one or two sentences, with `path/file.py:line` pointers; no finding IDs/severities/dispositions> | 📊 <where seen> / 🧠 <assumption> | <YYYY-MM-DD> | `<sha>` |

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
