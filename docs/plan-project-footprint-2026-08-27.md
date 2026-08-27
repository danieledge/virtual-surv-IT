# Plan: stop colonising the host project's directories

**Status:** proposed, 2026-08-27. Touches ADR-003 (map location) and ADR-010 (artifact
placement).

## The problem

The team is a guest in someone else's repository, and currently behaves like a tenant who
redecorates. 📊 What it creates in a working project today:

| What | Where | Whose directory that is |
|---|---|---|
| `codebase-map.md`, its `.d/` overflow, its fingerprints sidecar | `docs/` | the host project's |
| `team-extensions.md` | `docs/` | the host project's |
| engagement workspaces | `artifacts/<slug>/` at the **project root** | the host project's |
| preferences, caches, consent marker | `.claude/` | Claude Code's, legitimately |

Only the last row is defensible without argument: `.claude/` already belongs to the harness,
and every tool that integrates with Claude Code writes there.

The rest is the team deciding that a client's `docs/` is a good place for its own files, and
that a client's repository root wants a new top-level directory.

### `artifacts/` is the worst of it

A generic, unqualified, top-level `artifacts/` is close to the most collision-prone name
available in a build repository - it is standard output-directory vocabulary for CI systems,
packaging tooling and release pipelines. Dropping it into a bank's Scala monorepo invites a
name clash with something that already exists and is already gitignored for a different
reason, and a clash there is not cosmetic: the team's evidence and a build system's output
would share a directory, and `check_artifacts`' discovery scan would sweep whatever the build
left behind.

📊 It is also the most entrenched: `artifacts/<slug>/` is referenced in 40 files. That does
not make it right; it makes it expensive, which is a reason to plan the change carefully
rather than a reason to keep it.

## The rule this should follow

**Everything the team creates lives in one visible folder, `VSIT/`, with subfolders inside
it. Nothing else is added to the host project.**

Owner's call, and it is better than the dot-directory this plan first proposed - for the
same reason already given about machine-level config: *"if we put it in AppData it's not
discoverable, isn't logical."* A hidden `.virt-surv/` would have been tidy and slightly
dishonest: it hides a folder the project's own engineers should be able to find, read and
reason about.

Making the container VISIBLE also settles the question the first draft left open. That draft
argued the codebase map had to stay in `docs/` to remain discoverable, and would have split
the team's files across two locations to achieve it. With a clearly-named visible folder,
that argument evaporates: the map inside VSIT/ is at least as findable as one in the
host project's docs/, and better, because it sits beside the material it belongs with
rather than among the host project's own documentation.

`VSIT` also says what it is - the product's initials, matching the tool the user runs - and
is specific enough that nothing else in a build repository will want the name. That last
point is not incidental: it is exactly what `artifacts/` failed.

## The full layout

`VSIT/` sits at the root of whatever directory the project was started in - the same
directory the user runs `virt-surv` from, and the one `CLAUDE_PROJECT_DIR` resolves to. One
root, four subfolders, and the split between them answers the question that actually matters:
**what is shared across every engagement on this codebase, and what belongs to one piece of
work?**

```
<project>/
  VSIT/
    README.md                     # what this folder is, for whoever finds it
    subject/                      # SHARED - what we know about whatever is under review
      map.md                      #   curated: what an area/document is FOR   (committed)
      map.d/<area>.md             #   overflow when map.md's section 2 grows  (committed)
      derived.json                #   the tree + fingerprints, generated      (committed)
    engagements/                  # ONE PER PIECE OF WORK
      <slug>/
        engagement-state.json     #   the record: status, decisions, outcomes
        engagement-brief.md       #   what was agreed
        delivery-report.md        #   what was delivered
        findings/*.jsonl          #   review findings packs
        evidence/                 #   test output, analyser runs
        engagement-summary.txt    #   Morgan's closing email
    config/
      extensions.md               # this project's contract                   (committed)
      preferences.json            # this project's team settings              (committed)
    local/                        # machine-only, never shared              (gitignored)
      tool-availability
      engage-probe.json
      map-fingerprint-cache.json
      guard-interpreter
  .claude/                        # the HARNESS's directory - not ours
    settings.json                 #   hooks wiring, permissions
    hooks/ skills/ agents/        #   what Claude Code loads
    .exec-consent                 #   stays put - see below
```

### Why subject/ sits one level ABOVE engagements/

Because the map is used by **multiple engagements** and outlives all of them. That is the
entire reason it is worth curating: ADR-003's argument is that project memory survives the
engagement that produced it, so the third review of a codebase starts from what the first two
learned instead of rediscovering it.

Nesting it under an engagement would say the opposite - that what we know about the code
belongs to whoever last looked at it. It would also mean engagement four cannot find what
engagement one learned without knowing engagement one's slug.

So the rule reads straight off the tree: **subject/ is about the THING UNDER REVIEW; engagements/ is
about the WORK.** Anything that would still be true if this engagement had never happened
belongs in the first.

| | subject/ | engagements/&lt;slug&gt;/ |
|---|---|---|
| Scope | the codebase, or the document estate, or the data platform | one piece of work |
| Lifetime | as long as the subject exists | closed, then archived |
| Read by | every future engagement | its own engagement, and audit |
| Updated | at every close, both directions | continuously, then frozen |
| Committed | yes | no |

### Not every engagement has a codebase

📊 The first draft called this folder `codebase/`, which quietly assumed every engagement is
about source code. It is not: `engage-light` names "analyses, questions, doc work" as typical
fits, and CLAUDE.md section 1 is explicit that detection logic is "ONE deliverable, not the
only one" - data pipelines, DQ and reconciliation jobs, reporting/MI, integrations and
reviews all count. A comms-surveillance policy review or an assessment of a model-validation
report has no repository at all.

So the folder is named for its ROLE - what we know about the thing under review - not for one
kind of thing. `subject/` holds:

- **code work**: the codebase map, and the derived tree of symbols and ranges;
- **document work**: an inventory of what exists and where, section indexes produced when a
  document was converted, and what was learned about the estate;
- **data work**: schemas, feed inventories, what a field actually means in practice.

All three answer the same question - *what does the next engagement need to know before it
starts?* - and all three are wasted if they live inside one engagement's folder.

**Empty is a valid state.** A project whose first engagement is a one-off document review has
no `subject/` until something is worth keeping, and creating an empty folder to look complete
would be worse than not having one.

### Where the tree-sitter output goes, and where it does not

Worth stating plainly, because tree-sitter is three separate things and only one of them
lands in the project:

| | Where | In `VSIT/`? |
|---|---|---|
| the library itself | the interpreter's site-packages | no - machine-wide |
| its grammar cache | the library's own cache directory | no - machine-wide, per user |
| what it PRODUCES: symbols, line ranges | the derived file in subject/ | **yes** |

Tree-sitter is an engine, not stored state. Which engine produced a derived file is recorded
IN that file (the `tier` field), so a reader can tell exact extraction from a regex
approximation - but the engine itself is never something the project carries.

### Why local/ is separate from subject/

Both are generated, so the instinct is to file them together - but one is a fact about the
CODE and the other is a fact about this CHECKOUT. the derived file holds content hashes: same
bytes, same value, every machine, so it is worth committing and sharing. the local folder holds file
timestamps and probe results, which are wrong on anyone else's clone (git does not preserve
mtimes - measured: the same file, byte-identical, reads a different timestamp in a fresh
clone). Committing that would ship one person's filesystem state to everyone and conflict on
every regeneration.

### What stays in `.claude/`, and why that is not inconsistency

`.claude/` belongs to Claude Code. Three things stay:

- `settings.json`, `hooks/`, `skills/`, `agents/` - the harness reads these by path. Moving
  them tidies nothing; it breaks the integration.
- The execution-consent marker - **deliberately not moved.** It is the one path a HUMAN types
  by hand at a gate, and it appears in guard messages, skills, ADR-002 and the operating
  guide. Its value is that the path is stable and memorised. Relocating it to be tidy would
  invalidate every instruction that names it and gain nothing a user would notice.

Everything else in `.claude/` today is ours and moves: the team preferences file to
config/, and the caches - tool availability, the probe cache, the fingerprint cache, the
interpreter cache - to local/.

### The README is not decoration

A visible folder in someone else's repository owes an explanation to the engineer who finds
it and did not put it there. A generated `VSIT/README.md` says what the folder is, which
parts are generated, which are safe to delete, and how to remove the whole thing. A tool that
leaves an unexplained directory in a bank's monorepo earns the ticket it will get.

## Migration, which is the hard half

Nothing here is worth breaking a working project for.

1. **Read both, write new.** Every consumer accepts the old location and the new one, and
   writes only the new one. A project migrates the first time anything regenerates.
2. **No flag day, no required action.** A project that upgrades the plugin and changes
   nothing keeps working indefinitely.
3. **`artifacts/` last, and loudly.** 40 referencing files, plus `check_artifacts`'
   discovery scan, plus the dashboard, plus every skill that names a workspace path. This
   step needs its own change, its own tests, and a release note - not a quiet rename inside
   a larger commit.
4. **A one-shot mover**, offered and never automatic: `virt-surv` Advanced gains "relocate
   team files into VSIT/", which reports what it would move before moving anything. Silently
   restructuring someone's repository is exactly the behaviour this plan exists to stop.

## What would make this wrong

- Hiding `VSIT/` behind a dot. The folder is meant to be found: a project's engineers should
  be able to see what the team keeps about their codebase without being told it exists.
- A flag day, or any change that requires action from a project that was working yesterday.
- Renaming `artifacts/` inside an unrelated commit. It is the highest-blast-radius change in
  this plan and deserves to be the most visible.
- Adding a second top-level directory later. If a future feature needs a home, it goes
  inside `VSIT/`, and this document is the reason.

## Settled, so it is not re-litigated

Whether `VSIT/` is committed or ignored **as a whole**: neither. It is split, and the split
is the point. The map, the derived tree and the project's contract are committed, because
their whole value is that the next person - or the next engagement - inherits them.
`engagements/` and `local/` are ignored, because one is per-piece-of-work and the other is
wrong on any machine but this one.

A blanket ignore would be simpler to explain and would throw away the shared tree, which is
most of the reason for storing it at all.
