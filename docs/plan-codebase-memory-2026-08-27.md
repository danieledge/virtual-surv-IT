# Plan: consolidate codebase memory into two things, not six

**Status:** proposed, 2026-08-27 (rewritten the same day, after the owner's consolidation
point). Extends ADR-003 / ADR-007.

## The real problem is naming, not caching

The first draft of this plan proposed a new standalone skeleton file. That was wrong, and
the owner said why: *"we have code skeleton, code map... all sound similar and store
different things. We need to consolidate."*

📊 What exists today, all of it describing "what we know about this codebase":

| Thing | Where | Committed? | Holds |
|---|---|---|---|
| `docs/codebase-map.md` | project | yes | curated prose: what an area is FOR |
| `docs/codebase-map.d/<area>.md` | project | yes | more of the same, when §2 overflows |
| `docs/codebase-map.fingerprints.json` | project | yes | a content hash per mapped area |
| the map-fingerprint probe cache | project `.claude/` | no | a speed-up for computing those hashes |
| `repo_skeleton` output | nowhere | n/a | symbols, ranges, ranking - discarded every run |

Five names, four containing "map" or "skeleton", and a reader cannot tell from any of them
which is authored, which is derived, or which is safe to delete. A sixth would have made the
plugin's own memory harder to reason about than the codebases it maps.

## First, the two things - because the file count follows from them

The owner's framing, and the right one: *"we have two things, don't we - the tree, and some
helpful info the LLM discovers."* Yes. Everything below is storage; these are the concepts.

| | What it is | Derivable? |
|---|---|---|
| **The tree** | files, symbols, line ranges, the import graph, importance ranking | YES - a parser produces it, nobody has to know anything |
| **What was learned** | what an area is FOR, why it is shaped that way, what bit someone last time, which parts are generated boilerplate not worth reading | NO - it comes from a human or an LLM working through the code |

📊 The second already has a home and a discipline: `docs/codebase-map.md`, with ADR-003
making its update mandatory at every close in BOTH directions - add what is new, correct
what is now wrong. The first has no home at all and is recomputed from scratch every run.

That asymmetry is the whole problem, and it is worth stating the right way round. Keeping the
learned half is CORRECT - it is irreplaceable, because reproducing it means redoing the
thinking. The tree is the opposite kind of thing: fully reproducible from source, and
therefore safe to discard in principle - but it is also the half that costs real time to
rebuild, and it is rebuilt from scratch on every single run.

So the tree is being thrown away not because keeping it would be unsafe, but because until
now there was no way to know whether a kept copy was still valid. There is: the key is
already computed and stored beside the map, for the map's own drift check.

An earlier draft asked "can we consolidate to two files?" That was the wrong question: two is
the CONCEPT count, and it is already right. The file count follows from how each concept has
to be stored.

## How the two concepts are stored: three files, named by LIFECYCLE

Two concepts, three files - and the third is an implementation detail OF the tree, not a
third concept. They split because they have genuinely different lifecycles and one of them
cannot be shared:

| | Artefact | Lifecycle |
|---|---|---|
| **Authored** | `codebase-map.md` (+ `codebase-map.d/` when §2 overflows) | written by a human, reviewed, committed, merged like code |
| **Derived, shareable** | codebase-map dot derived dot json | computed from source content; identical on every machine, so worth committing |
| **Derived, machine-local** | codebase-map dot local dot json, under `.claude/` | computed from file timestamps; wrong on any other checkout, so never committed |

The third exists because that shortcut is what avoids re-hashing every mapped file on every
open - real work, worth keeping.

Why it cannot be shared, concretely: it stores entries of the form *"scripts/foo.py, last
modified 2026-08-25 08:51:51, 4,210 bytes -> I hashed this already, here is the answer."*
**Git does not preserve modification times.** A fresh clone stamps every file with the moment
it was cloned - measured: the same file, byte-identical, reads 2026-08-25 08:51:51 in one
checkout and 2026-08-27 21:38:34 in a clone made from it. So every cached timestamp is wrong
on anyone else's machine, every entry misses, and the file is dead weight that also produces
a merge conflict every time two people regenerate it.

The content hash in the shareable tier has the opposite property: same bytes, same hash,
everywhere. That difference is the entire reason these are two files and not one.

**The consolidation is the naming, not the count.** One prefix, three suffixes, each saying
exactly what the file is and what may be done to it: a `.md` suffix means authored, a
`.derived` infix means computed-and-shared, a `.local` infix means computed-and-private. Today the same three concepts
are called the map, the fingerprints sidecar and the
map-fingerprint probe cache - three names that share no scheme and describe
implementation details rather than lifecycle, which is exactly why nobody can tell them
apart. A reader who learns the suffix rule once never has to ask again which file is safe to
delete, which to hand-edit, or which to expect in a diff.

**Could it be two?** Only by folding the derived data into the committed markdown, which
reintroduces exactly what makes derived data dangerous: a generated block someone can
hand-edit, and a merge conflict on every regeneration. One file would look tidier and be
worse. Three tiers whose names explain themselves is the honest floor.

The derived file is **not new**. It is today's `codebase-map.fingerprints.json`, extended in
place and eventually renamed for what it becomes. It already has exactly the right shape:
one entry per mapped area, each holding that area's `paths` and `fingerprint`. The skeleton
belongs in those same entries, because it derives from the same globs and is invalidated by
the same key. A separate file would have duplicated that key and invited the two to disagree.

```json
{
  "generated_by": "repo_skeleton",
  "generated_at": "<iso8601>",
  "entries": {
    "<area>": {
      "paths": ["scripts/**"],
      "fingerprint": "sha256:...",
      "files_hashed": 42,
      "tier": "tree-sitter",
      "tool_version": "0.37.0",
      "skeleton": "<the rendered block>",
      "symbols": {"<file>": [["<name>", 12, 48]]}
    }
  }
}
```

The machine-local tier keeps its current behaviour exactly - gitignored, described in
`.gitignore` as *"a pure performance aid, safe to delete any time"*, never authoritative -
and gains only the naming scheme.

### The rename, and its cost

The sidecar is read by `check_artifacts` and `engage_probe`, and is committed in consuming
projects. So: **read either name, write only the new one.** A project carrying the old file
keeps working and migrates the first time anything regenerates - no flag day, and upgrading
the plugin breaks nobody. If the churn proves not worth it, the fallback is to keep the
current filename and accept that it under-describes its contents. The consolidation is what
matters; the spelling is negotiable.

## Why keeping derived data is safe here: the key, not a clock

Derived memory is only worth keeping if it cannot be silently stale. ADR-003/ADR-007
rejected index-based memory for exactly that reason, and the objection was never "caching is
slow" but *"a stale index corrupts a review and nothing announces it."*

So an entry is served only when its key matches, and the key is everything that changes the
output:

```
key = sha256(source_fingerprint + tier + tool_version)
```

- Key matches → verifiably current. Serve it.
- Key differs → verifiably stale. Regenerate or ignore it; never serve it.
- No key → no memory. Behave exactly as today.

**No TTL, deliberately.** "If it is a day old do we force a rebuild?" - no. Age is a proxy
for change; the key measures change directly. A day-old entry whose key matches is current,
and rebuilding it discards valid work; a one-minute-old entry whose key differs is stale, and
a TTL would serve it. Having both is worse than having either. The probe cache needs a TTL
because it carries facts with no content to hash - plugin version, branch, preferences - and
this has a better handle available.

The fingerprint alone is not enough, which is why the key is a composite. Two things change
the output from unchanged input: the **tier** (tree-sitter appears, and a file that yielded a
regex guess now yields exact ranges) and the **extractor** (`repo_skeleton` itself changes).
A source hash sees neither. One consequence worth naming as a feature: installing
tree-sitter invalidates every area at once, which is correct - the same reasoning that made
`--code-intel` clear the tool-availability cache.

## Generated where the human is already waiting

`_write_probe_cache` set the precedent and the reasoning: *"Run the engage probe ENTIRELY
OUTSIDE Claude Code - corp boxes take minutes per in-session probe - go is where a human is
already watching a terminal."* It applies harder here, because `repo_skeleton` is a zero-LLM
deterministic script and paying a model turn to invoke it is pure waste.

One more step in the `(_remember_project, _prewarm_guard_interpreter, _write_probe_cache)`
tuple at `go`, tty-gated as those are but **keyed, not time-gated** - a `go` on an unchanged
tree does no work at all. Best-effort throughout: memory that will not build costs memory,
never a launch.

## What the session then does

1. Orientation reads the curated map, and an area's derived entry when its key matches -
   zero tool calls.
2. On a miss, `repo_skeleton` runs exactly as today. The derived half is an optimisation,
   never a dependency; nothing downstream may require it.
3. `--slice` uses stored symbol ranges when present, so a slice becomes a read of known
   lines rather than a parse.

## Honesty rules, non-negotiable

The tier label already travels with skeleton output. Stored memory must not launder it.

- A served entry says it was stored, and when.
- An entry generated on a machine WITH tree-sitter, served on one without, still reports the
  tier that produced it. It is not less true for having been computed elsewhere - but a
  reader must be able to tell.
- Partial memory serves only the areas whose keys match, and says which it could not.

## Sequencing

1. **Extend the derived sidecar in place** (current filename) with `tier`, `tool_version`,
   `skeleton`, `symbols`, plus keyed read/write. Everything depends on this.
2. **`--slice` served from stored ranges.**
3. **`go`-time generation**, behind a preference, default ON once step 1 has proven itself.
4. **The renames**, read-either / write-new - last, because this is the only step that
   touches consuming projects. Both files move to the suffix scheme in one change, since
   half a scheme is worse than none.

## What would make this wrong

- A sixth artefact. If a change needs a new file with "map" or "skeleton" in its name, it is
  going the wrong way.
- Serving an entry whose key was not checked, for any reason including speed.
- A TTL "just in case". If the key is right it is unnecessary; if the key is wrong, a TTL
  hides that rather than fixing it.
- Hand-editable derived data. Curated and derived must stay distinguishable at a glance, or
  someone eventually merges a generated file and nobody notices.
- Anything downstream that *requires* the derived half. The moment something breaks without
  it, it has stopped being an optimisation.

## The smaller thing worth doing regardless

📊 This repo has no `docs/codebase-map.md` at all - `/map-codebase` has never been run on it.
The team recommends a curated map to every project it touches and keeps none for itself. That
is one command, needs none of the above, and would let the project eat its own cooking.
