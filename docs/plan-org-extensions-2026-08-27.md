# Plan: org-level extensions - author once, apply everywhere

**Status:** proposed, 2026-08-27. Supersedes nothing; extends ADR-009.

## The problem, in the owner's words

> "I don't think it makes sense for it to live in the working project - wouldn't want a user
> to have to set up a standard workflow in every project. Needs storing somewhere and
> importing automatically per project."

Correct, and it is the gap that matters. ADR-009 built a real extension contract - standing
instructions, close actions, an analyser registry, integrations - and then put it in exactly
one place: `docs/team-extensions.md` **inside each working project**
(`scripts/extensions.py::default_file`). That location is right for *this project differs*
and wrong for *this is how our organisation works*. A compliance function with fifteen
repositories currently has to author the same contract fifteen times and keep fifteen copies
in step. A standard nobody can apply centrally is not a standard.

## What already works, and must not be broken

- **Extensions survive plugin updates** because the contract lives outside the plugin. Any
  new location must keep that property - the failure mode to avoid is putting org config
  inside the plugin tree, where the next `git pull` overwrites it.
- **Additive only.** Nothing an extension expresses can waive a gate, skip the code chain,
  weaken a guard or self-grant consent. `extensions.py` carries no mechanism to express a
  waiver and must not gain one.
- **Never executes.** Tool presence is `shutil.which()` on a probe name; registry commands
  are plain argv with shell metacharacters refused at validation. A model-writable file that
  an allow-listed script executed would be a guard bypass.
- **Zero cost when absent.** No extensions file means a silent exit 0.

## The shape: three tiers, one resolution rule the repo already uses

`resolve_preferences` resolves `project > machine > built-in`, and uses key **presence**
(not truthiness) to decide whether a project has made its own choice. Extensions should
resolve the same way, for the same reason: an org default that a project cannot override is
as wrong as a per-project file that cannot be shared.

| Tier | Location | Who owns it | Answers |
|---|---|---|---|
| Project | `<project>/docs/team-extensions.md` | the engagement | "this repo is different" |
| **Org (new)** | `~/.config/virt-surv-it/team-extensions.md` | the compliance function | "this is how we work" |
| Built-in | none | the plugin | nothing - absence is valid |

`~/.config/virt-surv-it/` is already this project's machine-config home
(the machine-defaults file there, honouring `XDG_CONFIG_HOME`), so this adds a file to an existing
directory rather than inventing a location.

### Merge semantics, per section

Not one rule for all four - the sections mean different things:

- **Standing instructions** - CONCATENATE, org first. Both apply; neither replaces the other.
- **Close actions** - CONCATENATE, org first, de-duplicated by exact text. An org's Confluence
  write-up and a project's "copy the pack to the share" are both wanted.
- **Analyser registry** - MERGE BY `name`, project wins on collision. This is what lets an org
  register the corporate SAST tool once while one project pins a different version.
- **Integrations** - MERGE BY name, project wins.

Every merged entry carries its **origin** (`org` or `project`) through to `show`, so a
reader can always tell which tier an instruction came from. An extension whose source is
invisible is an extension nobody can debug.

## Distribution: how the org file gets onto a machine

Three options, in order of how much they ask of the user. Start at 1; 2 is the one worth
building; 3 is deliberately out of scope.

1. **Copy it there.** Documented path, `install_helper.py --extensions <file>` copies a file
   into place. Works on day one, works offline, works on a locked-down box.
2. **Point at a source and sync.** The machine-defaults file gains
   `"extensions_source": "<git URL | UNC path | local path>"`, and the installer (and
   `virt-surv` at `go`, freshness-gated like the probe cache) refreshes the local copy from
   it. A git URL means the compliance function versions its standard like anything else and
   a machine picks up changes without anyone editing files by hand. **A sync failure must
   never block a launch** - stale-but-present beats absent, and absent beats hung.
3. **Fetch per engagement from a service.** Not proposed. It puts a network call on the
   engagement-open path, which this project has twice measured as the worst place for one.

Option 2 needs one safety rule stated plainly: **the synced file is DATA, not instructions.**
It arrives from outside and is parsed by a script that already refuses shell metacharacters
and never executes anything. That property is what makes remote sync tolerable at all, and
it must not be relaxed to make a feature work.

## The DoD question the examples actually raise

The owner's example - "add a Confluence step at DoD where it writes up a page on what was
achieved" - sits on a fault line worth naming rather than papering over.

📊 Today, close actions are **offers made after the summary email**, and extensions are
additive-only: they cannot add a condition the DoD gate enforces. So an org can say "we
always write a Confluence page" and the team will always offer it - but a run that skips it
still closes green.

Two honest options:

- **(a) Keep it an offer.** Zero risk, and consistent with "extensions never gate". The org's
  step is prompted every time; compliance comes from people, not the tool.
- **(b) Let an org tier - and only the org tier - add a *required* close action.** The DoD gate
  gains one new finding type: "declared org close action not recorded". This is a real change
  in kind: it is the first time an extension could fail a close. It stays additive in the sense
  that it can only ADD a requirement, never remove one, and it must be expressible only in the
  ORG file (a project cannot impose it on itself, which would let an engagement invent its own
  gate) and only for actions the state file can evidence.

**Recommendation: build (a) first, ship (b) behind an explicit `required: true` flag** once
there is real usage. An SDLC step nobody can skip is exactly what a compliance function
wants; it is also the first crack in "extensions can never gate", and that rule has been
load-bearing. Get evidence before widening it.

## The TUI

`virt-surv` Advanced already hosts one-off settings, and `_TOGGLE_PREFS` already drives a
two-tier editor with a prompt_toolkit tier and a plain fallback. Extensions get the same
treatment rather than a new interface:

- **Review** - a read-only view of the resolved contract, each entry tagged `org` or
  `project`, with registry tools showing found/missing from the existing `check` (which is
  already a `shutil.which` probe, no execution).
- **Edit** - open the appropriate file in `$EDITOR`. Deliberately NOT a form: the contract is
  markdown with a fenced JSON block, and a TUI that round-trips it risks mangling a file the
  user hand-maintains. Validate on save (`extensions.py` already refuses metacharacters) and
  report, rather than constrain input.
- **Sync now** - refresh from `extensions_source` and show what changed.

## Sequencing

1. **Org tier + merge** in `extensions.py`, with origin tagging. Everything else depends on it.
2. **`--extensions <file>`** install path (option 1) and the docs to match.
3. **TUI review/edit** in Advanced.
4. **`extensions_source` sync** (option 2), freshness-gated, fail-open.
5. **Required close actions** (option b) - only with real usage behind it.

## What would make this wrong

- Putting the org file inside the plugin tree. It would work until the first update.
- A merge that silently drops a project entry colliding with an org one, with no origin shown.
- Any path where a missing, stale or unreachable org file blocks a launch or an open.
- Widening the additive-only rule beyond one explicitly-flagged, org-only, evidenced case.
