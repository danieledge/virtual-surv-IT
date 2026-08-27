# Plan: keep what we learn about a codebase - without inventing a stale index

**Status:** proposed, 2026-08-27. Extends ADR-003 / ADR-007; supersedes nothing.

## The gap, stated precisely

Two kinds of knowledge come out of an engagement, and today the project keeps exactly one
of them.

| | What it is | Where it lives | Survives? |
|---|---|---|---|
| **Curated** | why an area exists, what it is for, what bit us last time | `docs/codebase-map.md`, committed | yes |
| **Derived** | symbols, line ranges, import graph, importance ranking | nowhere | **no** |

📊 `repo_skeleton` recomputes every symbol, range and PageRank score on every call and
throws the lot away. `--out` exists; nothing invokes it, nothing caches it. So the CHEAP
curated part is preserved and the EXPENSIVE mechanical part is rebuilt from scratch, which
is the wrong way round.

The gap is sharper than it looks, because the derived half is what the owner already asked
to move off the session's clock: *"why while we give the option of running tree sitter first
outside the Claude session?"* Running it outside is only worth doing if the result is kept.

## Why this has not been built yet, and the constraint that follows

ADR-003/ADR-007 rejected embedding and index-based memory for one reason worth keeping:
**a stale index is worse than no index.** An index that quietly describes code as it was
three commits ago does not degrade a review, it corrupts it - and unlike a missing index,
nothing announces the problem.

So the design constraint is not "add a cache". It is: **any derived memory must be
incapable of being silently stale.** Everything below follows from that.

## The idea: fingerprint-keyed derived memory, not a new artefact

The project already has the exact mechanism required, built for the map and unused for
anything else. `map_fingerprint.compute_fingerprint` hashes **paths + file bytes** per
mapped area, and `codebase-map.fingerprints.json` stores one per area. `map_drift_summary`
already reports drift at engagement open.

That is a content-addressed key. So: **store the skeleton against the fingerprint it was
generated from, and treat a fingerprint mismatch as "regenerate", not as "warn".**

- Fingerprint matches → the cached skeleton is provably current. Serve it.
- Fingerprint differs → it is provably stale. Regenerate or ignore it; never serve it.
- No fingerprint → no cache. Behave exactly as today.

Staleness stops being a risk to manage and becomes a state the data cannot occupy. Nothing
new has to be invented, and nothing new has to be trusted.

### Where each half lives, and why the split matters

- **`docs/codebase-map.md`** - curated, committed, human-owned. Unchanged.
- **A derived cache under the project's `.claude/`** (proposed; named
  codebase-skeleton dot json, written without link formatting here because it does not
  exist yet and the reference checker rightly refuses to resolve it) - gitignored,
  machine-owned, regenerated, never merged, never reviewed, safe to delete at any
  moment.

That boundary is the same one ADR-010 draws for artifacts and the same one
`.claude/engage-probe.json` already occupies. Putting derived output in `docs/` would invite
someone to hand-edit it, and a hand-edited derived file is a stale index wearing a costume.

### What the cache holds

```json
{
  "generated_by": "repo_skeleton",
  "generated_at": "<iso8601>",
  "areas": {
    "<area or ':root:'>": {
      "fingerprint": "sha256:...",
      "skeleton": "<the rendered block>",
      "symbols": {"<file>": [["<name>", 12, 48], ...]}
    }
  }
}
```

The `symbols` map is what makes `--slice` free on a cache hit, and it is the part that
cannot be reconstructed from the rendered text.

## Generated where the human is already waiting

`_write_probe_cache` established the pattern and the reasoning: *"Run the engage probe
ENTIRELY OUTSIDE Claude Code - corp boxes take minutes per in-session probe - go is where a
human is already watching a terminal."* Every word applies here, and more so: `repo_skeleton`
is a zero-LLM deterministic script, so paying a model turn to invoke it is pure waste.

So: one more step in the `(_remember_project, _prewarm_guard_interpreter, _write_probe_cache)`
tuple at `go`, tty-gated and freshness-gated exactly as the probe cache is, and **best-effort
throughout** - a skeleton that will not build costs a cache, never a launch.

## What the session then does

1. Orientation reads that cache if its fingerprint matches. Zero tool
   calls, zero wall-clock.
2. On a miss it runs `repo_skeleton` exactly as today. The cache is an optimisation, never a
   dependency, and nothing downstream may assume it exists.
3. `--slice` checks the cached `symbols` map before parsing. On a hit, a slice becomes a
   file read of a known line range.

## Honesty rules, non-negotiable

The tier label already travels with skeleton output (`ast` / `tree-sitter` / `regex`). A
cache must not launder that.

- A served cache says so, and says when it was generated.
- A cache generated on a machine WITH tree-sitter, served on one without, still reports the
  tier that produced it. It is not less true for having been computed elsewhere - but a
  reader must be able to tell.
- A partial cache (some areas fingerprinted, some not) serves only the areas it can prove
  current, and says which it could not.

## Sequencing

1. **Fingerprint-keyed cache read/write in `repo_skeleton`** - `--cache` to write,
   automatic use on a fingerprint match. Everything else depends on it.
2. **`go`-time generation**, behind a `skeleton_cache` preference, defaulting ON only once
   (1) has proven itself on a real repo.
3. **`--slice` served from the cached symbol map.**
4. **Map integration** - a §2 area whose fingerprint is current can carry its derived
   skeleton alongside its curated prose, so the two halves of "what we know" are read
   together instead of separately.

## What would make this wrong

- Serving a cache whose fingerprint was not checked, for any reason, including speed.
- Putting derived output in `docs/` where a human might edit it.
- Letting a cache miss, a corrupt file, or a missing fingerprint do anything except fall
  through to today's behaviour.
- Reporting a cached tier as if it had been computed on this machine.
- Making any downstream step *require* the cache. The moment something breaks without it,
  it has stopped being an optimisation.

## The smaller thing worth doing regardless

📊 This repo has no `docs/codebase-map.md` at all - `/map-codebase` has never been run on
it. The team recommends a curated map to every project it touches and does not keep one for
itself. That is a one-off command, it needs none of the above, and it would give this
project the durable memory it currently only advises others to have.
