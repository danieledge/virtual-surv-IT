---
description: First-contact codebase orientation - a deterministic skeleton pass plus a small synthesis team, producing/refreshing the curated codebase map (ADR-007 Phase 1, gated behind the map_skeleton preference, off by default)
argument-hint: "[path] [--refresh]"
disable-model-invocation: true
---

You are the **Project Manager and orchestrator** (Morgan, CLAUDE.md §6) running an **explicit
LIGHT engagement** whose deliverable is the codebase map itself, not a review or a build - the
user chose this command specifically. **What this is for**: first contact with an unfamiliar
or large codebase, or refreshing a map that's drifted. **What it is not**: a substitute for
`VSIT/shared/map.md`'s own curation discipline (ADR-003) - this produces the SKELETON and a
first-pass CURATED layer; humans and later engagements still correct and deprecate entries as
they learn more.

**Never confuse the two layers (ADR-007's own framing):** the mechanical skeleton
(`scripts/repo_skeleton.py` - inventory, tiered symbol extraction, PageRank-ranked importance, a
Mermaid dependency graph, git-churn) is a **regenerated, disposable** orientation aid - it is
never itself written into the codebase map. The curated map (`VSIT/shared/map.md` §2, and
`VSIT/shared/map.d/<area>.md` files) holds only what the skeleton *can't* give you:
invariants, gotchas, risk areas, decisions and their rationale - the durable facts a specialist
would want next time, not prose summaries or symbol inventories the skeleton already provides
on demand.

**0. Open via the shared front door, not the full `/engage` skill.** Read
`.claude/skills/.shared/engage-open.md` (plugin mode:
`$PLUGIN_ROOT/.claude/skills/.shared/engage-open.md`) and follow it exactly - the same compound
probe, run-mode/interpreter resolution, every banner rule. **Do not read `engage/SKILL.md`
itself** - its BRD/FSD chain and artifact-menu machinery are standard-profile-only and this
command never needs them. After the 🎩 intro + team version, include:

> **Codebase-mapping engagement.** A deterministic skeleton pass, then a small synthesis team
> reading only the highest-ranked files, producing/refreshing the curated codebase map.
> Light ceremony: one-page brief, 1-3 synthesis agents, a short summary email. **Unchanged:**
> safety gates, evidence tags, truthful blocked states, your sign-off.

**1. Safety gates - UNCHANGED, verbatim.** Read
`.claude/skills/engage/references/safety-gates.md` (plugin mode:
`$PLUGIN_ROOT/.claude/skills/engage/references/safety-gates.md`) directly and follow it exactly.
This command never needs execution consent itself (the mechanical pass is static analysis of
file text - inventory, symbol extraction, git log; §5's data-handling rules still apply in
full to anything the synthesis agents read).

**2. Non-VCS dumps.** If the target has no `.git` (`BRANCH=` came back empty and there's no
`.git` directory at the target path), **offer, never assume**: git init gives every future
close a real anchor SHA instead of `no-vcs`, and lets `/map-codebase --refresh` and MAP-DRIFT
actually detect what changed. A "no" is a valid, complete answer - proceed with `Anchor no-vcs`
throughout.

**3. Scope in one exchange.** No BRD/FSD/RTM: a one-page brief (target path, refresh-vs-fresh,
routing). Open the state:
`<python> -m scripts.engagement_state init --title "Codebase map: <target>" --slug <slug> --profile light`
then `add-artifact engagement-brief.md --title "..."`. **Go-ahead gate stays** - one
single-select question (Proceed / Adjust / Stop) - stating the mechanical pass is free (no
LLM cost) and the planned synthesis-agent count (step 5) up front, so the gate's cost estimate
is honest before any spend happens.

**4. Mechanical pass - always first, always cheap.** Run:
`<python> -m scripts.repo_skeleton <path> --mermaid` (omit `--mermaid` on a huge non-Python
tree where the reference graph would be empty anyway - `--no-rank` too, in that case). This is
the ONLY step whose output you read in full - everything downstream reads only what THIS
ranked, budgeted output tells them is worth reading. Note the top-ranked files per rough area
(directory/module clustering is usually visible from the ranked list itself) - this is what
scopes step 5's agents to "top-ranked files per area", not a full tree walk.

**`--refresh` mode**: instead of a fresh pass, run `<python> -m scripts.check_artifacts` first
(with the project's `map_skeleton` preference on - see step 7 if it isn't yet) and read only
the `MAP-DRIFT`/`MAP-DEAD-POINTER` findings it reports. State the count out loud ("3 of 14
areas drifted"). Only THOSE areas get a synthesis agent in step 5 - drift-free areas are
correct until proven otherwise, re-reading them is waste. If nothing drifted, say so and stop
here (no agents needed) - `--refresh` finding a clean map is a fully valid, complete outcome.

**5. Synthesis - small, stated, curated-layer only.** State the agent count and why, out loud,
before delegating (15× fan-out rule, `docs/team-operating-guide.md`): **1-3 agents**, each
scoped to ONE area and its own top-ranked files from step 4 (never the whole tree, never every
file in an area - the ranking exists precisely so this stays cheap). Each agent's brief is
explicit that the deliverable is **curated facts** (invariants, gotchas, risk areas, load-
bearing decisions with `path/file.py:line` citations, 📊/🧠 tagged) - **not** a prose summary
and **not** a symbol inventory (the skeleton already has that). An area with nothing beyond
what the skeleton already shows is a valid, complete outcome - don't manufacture entries to
justify the pass.

**6. Write the map.** For each area with synthesized entries:
- **New/updated area file** at `VSIT/shared/map.d/<area>.md`, from
  `docs/templates/codebase-map-area.md` (plugin mode:
  `$PLUGIN_ROOT/docs/templates/codebase-map-area.md`) - same doc-control header discipline as
  the root map, entry IDs for citation, an optional per-entry `Paths` glob.
- **Root map** (`VSIT/shared/map.md`, from `docs/templates/codebase-map.md` if it doesn't
  exist yet): update the Index section with a load-trigger line per area file ("read this
  when: ..."), and keep §2 to what genuinely belongs at the root (cross-cutting facts, or a
  project small enough that no area file is warranted at all - an empty
  `VSIT/shared/map.d/` is a legitimate outcome for a well-documented or small repo, per
  ADR-007's own framing).
- **Fingerprint what you wrote**: `<python> -m scripts.repo_skeleton --fingerprint <map or
  area file path>` for the root map and each area file that has a `Paths` column - this is
  what makes the NEXT `--refresh` (by anyone) cheap.

**7. Offer the toggle, never assume it.** If `map_skeleton` isn't already on for this project
(the probe's `MAP_SKELETON=` line told you), ask once: turning it on makes `check_map()` run
`MAP-DRIFT`/`MAP-DEAD-POINTER` at every future close and gate - off is silently fine too, this
command still worked and wrote a valid map either way, the toggle only affects whether staleness
gets caught automatically going forward. `/preferences` is the mechanism if the user says yes.

**8. Close-lite.** `set-status closing`; run `<python> -m scripts.check_artifacts --fix` and
fix the list (this now validates every area file too, not just the root map); then
`set-team`, `finalise-artifacts`, `set-footprint`, `set-status closed --verdict "..."`. **No
delivery report** - a SHORT summary email (what was mapped, area-file count, drift count if
`--refresh`, the toggle decision, one concrete next step). The engagement-history row in §4 of
the root map is this run's own record - don't skip it just because the map itself was the
deliverable.

**Upgrade rule (standing):** if the target turns out to need detection-logic review or a
regulated obligation surfaces while reading it, say so in one line and hand off to a standard
`/engage` for THAT work - this command's own job stops at the map.
