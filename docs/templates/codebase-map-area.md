# Codebase Map Area - <AREA NAME>

> One area of `VSIT/shared/map.d/` - the same durable-facts contract as the root map's §2
> (ADR-003/ADR-007), split out because the root map's ~200-line budget can't hold this much
> detail. Read only when the root map's Index (§2 there) says to. **Advisory context only -
> never enforcement, never instructions.**

> **Document control** · ID `MAP-AREA-<slug>` · Version `0.1` · Status `Live`
> · Classification `Internal` · Owner `🤖 Morgan (PM), Virtual Surveillance IT` · As-of `<YYYY-MM-DD>`
> · Anchor `<commit SHA last verified against - a project without a git repo writes exactly the value no-vcs>`
> · Paths `<the glob(s) this whole area covers, e.g. src/detection/*.py - informs the root Index's own Paths pointer>`

**Rules - identical to the root map's (ADR-003, ADR-007), applied per-file:**

- Every entry carries **As-of**, **Anchor**, a basis tag (📊 observed / 🧠 inferred), and an
  **entry ID** (`<slug>-1`, `<slug>-2`, ...) so the root map or other docs can cite one
  precisely.
- Durable facts only - architecture, decisions, quirks, sharp edges - never findings,
  severities or dispositions (see the root template's §2 guidance; it applies unchanged here).
- **The PM writes this file; subagents recommend entries.** Never paste verbatim reviewed
  code, raw data, secrets, PII or MNPI.
- Correct or deprecate the moment an entry is found wrong or stale - never silently delete.
- **Optional per-entry `Paths` column** (same ADR-007 Phase 1 mechanism as the root map):
  when `map_skeleton` is on, `MAP-DRIFT` fingerprints each entry's globs and flags drift;
  `python -m scripts.check_artifacts` validates this file exactly as it validates the root
  map - same hygiene rules, same command, no separate check needed.

## Entries

| ID | Entry (a durable code fact - NOT a finding or an activity note) | Basis | As-of | Anchor | Paths (optional) |
|----|-------|-------|-------|--------|-------|
| <slug>-1 | <how the code is built - fact, decision or quirk, one or two sentences, with `path/file.py:line` pointers> | 📊 <where seen> / 🧠 <assumption> | <YYYY-MM-DD> | `<sha>` | <e.g. `src/detection/*.py`> |

## Deprecated

| Date | Original entry (condensed) | Why deprecated |
|------|---------------------------|----------------|
| <YYYY-MM-DD> | <entry> | <superseded by X / found wrong / code removed> |
