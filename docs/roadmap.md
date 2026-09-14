# Roadmap

> Moved out of README.md on 2026-09-14 (framework review, step 6.8); the README keeps a one-line pointer.


Tracked enhancements, with the rationale for each. *(Done this cycle: **subagent self-assessment**,
agents now self-verify against their brief and flag gaps before returning; standing rule in
[`docs/team-operating-guide.md`](team-operating-guide.md).)*

<details>
<summary>🗺️ <b>What's shipped and what's next</b></summary>

**Quality & evaluation**
- ✅ **Team-quality eval harness: SHIPPED (0.5.0)**. `evals/` has 9 rubrics + 52 golden cases
  (seeded issues + false-positive traps) across review, coverage, spec/traceability, tuning and
  data-safety. The deterministic scorer (`scripts/eval_score.py`) is unit-tested; `/run-evals`
  runs the live team + an LLM-judge and prints a scoreboard. *Remaining:* grow the case set and
  calibrate the judge against human scores over time.

- ✅ **Multi-engagement workspaces: SHIPPED (0.31.0, ADR-008)**. Several engagements per project
  at independent states: per-engagement `VSIT/engagements/<slug>/` workspaces, a derived root registry,
  resume-or-new selection at the front door, and the stop-gate arming only on gated workspaces
  (a ⛔ parked sibling stays silent). Hardened in 0.33.0 (fail-safe gates, the 🔒 closing window,
  disk-first resume, the ADR-010 placement rule - see
  [`docs/releases/0.33.md`](releases/0.33.md)).
- ✅ **Codebase map evolution: SHIPPED (0.33.28, ADR-007, Phase 1+2)**. Staleness detection
  (strict anchor validation, per-entry As-of/SHA checks, a `MAP-STALE` budget against HEAD) plus
  the generative layer: a deterministic `repo_skeleton` (inventory, tiered symbols, PageRank,
  Mermaid, churn), `VSIT/shared/map.d/` per-area detail files, the `/map-codebase` skill, and
  content-fingerprint drift stamps (`MAP-DRIFT`/`MAP-DEAD-POINTER`). The first-contact-on-
  large-codebase need the ADR parked this behind materialised; it's now gated by the
  `map_skeleton` project/machine preference (off by default - zero behaviour change unless
  opted in), pinned by the `process-first-contact-map` golden eval case. *Remaining:* Phase 3
  (demand-driven blast-radius refresh automation, a human-facing rendered map browser) stays
  deferred until a concrete need materialises.

- **🚧 RTM as a graph, not a table** (`scripts/validate_rtm.py`). The validator checks each *cell*:
  does this code path exist, does this row name an obligation. Every check is confined to one row.
  But traceability defects are usually **connection** defects, a chain that breaks in the middle
  while every individual cell resolves. Treating each item as a node and "traces to" as a directed
  edge turns four things into queries a table cannot answer: **impact analysis** (all descendants of
  a changed obligation, which `/reg-change-impact` currently reasons about by hand), **coverage as
  reachability** (can every obligation reach a real test end to end, not just "does each row name
  one"), **blast radius** (reverse traversal: which obligations does this changed file serve, useful
  at review time), and **orphans** as uniform degree checks rather than three special cases.
  *Why not yet:* absence of an RTM is deliberately not a finding, so most engagements have none, and
  a graph over an empty matrix is worth nothing. Build it when the first populated real-project RTM
  lands. *Cost:* row parsing and cell resolution already exist, so this is an adjacency structure
  plus a traversal, stdlib only.

**🚧 TODO: Automatic data-masking workflow** (detail in [`docs/internal/prepare-data-roadmap.md`](internal/prepare-data-roadmap.md))

> **The goal:** *"throw a dataset at it and it masks/anonymises it safely"*, so the team can take
> real data **without the user having to self-attest** it's clean. **Until that ships, the interim
> control is the startup data-safety disclaimer** (you confirm shared data is masked/synthetic/
> anonymised; `data/raw/` stays hard-blocked). This workflow is what *replaces* that disclaimer.

- **Local schema-inference profiler**: propose a masking schema from a local profile (no agent
  reads raw data). *Why:* removes the biggest `/prepare-data` friction and the manual schema step.
- **NER/Presidio redaction**: replace regex-only free-text masking. *Why:* makes **comms/chat**
  data viable (regex misses names / obfuscated IDs).
- **Format adapters** (CSV/Parquet/Excel/nested) + **real synthetic (SDV)**. *Why:* "throw any
  structured file at it", safely; synthetic is the genuine trust-the-output path.
- **Auto-validation gate**: run the masking/NER check over the output and **block on residual
  PII**, so "auto-masked" is *proven* safe, not just attempted.

**Evidence: move foundational → verified** (detail in [`docs/house-rules.md`](house-rules.md))
- **Comms-surveillance *practice*** (lexicon/NLP/voice/coverage methodology), **per-scenario
  detection-tuning practice**, and the **DA/BA boundary**. *Why:* the *regulatory* citations are
  verified; these *practice* details are industry-grounded, not primary-sourced; verify before
  relying on them in a real engagement.

**Worked example**
- **Larger labelled synthetic calibration set** for the spoofing scenario (the shipped fixture is
  12 events). *Why:* enables a *measured* `/tune-thresholds` demo (ATL/BTL, real FP reduction)
  rather than an illustrative one. Plus the price-context (distance-from-touch) check noted in
  [`docs/scenarios/spoofing.md`](scenarios/spoofing.md).

**Performance / startup** *(nice-to-have)*
- ✅ **Trim routing metadata: SHIPPED (0.8.x)**. Skill descriptions no longer load at all
  (`disable-model-invocation: true`); agent descriptions trimmed to crisp routing lines.
- ✅ **Merge the Bash-matching PreToolUse guards into one interpreter call: SHIPPED (0.33.6)**.
  The raw-data, code-execution and consent-write guards each launched via `run-guard.sh` (which
  probes `python3`/`python`/`py`), so a single `Bash` call spawned the interpreter once per
  matching guard. `scripts/bash_hook_dispatcher.py` now runs them in-process behind one launch,
  first-block-wins, with a per-guard crash policy so a broken guard fails closed rather than
  silently disabling the rest. Wired in both `hooks/hooks.json` and `.claude/settings.json`.

**Corporate Windows estate: open follow-ups from the live sessions of 2026-09-14** *(P1 first)*
- **P1: PreToolUse hooks cost 2.4 to 4.4 seconds per Bash and Read call** on the owner's
  corporate Windows box, with `guard_daemon: true` in the project's team preferences. In a
  four-reviewer parallel review (VRTSRV-13: 609k tokens, 11 minutes) that latency was the
  dominant cost. Not to be fixed blind. To measure on WINTEST (or the owner's box), in this
  order: (1) does the daemon actually start there - after one tool call, does
  `.claude/.guard-daemon-port` exist and hold a port, and does a second call reach it; (2) the
  interpreter probe - what `.claude/.guard-interpreter` (or `VSIT/local/guard-interpreter`)
  holds, and whether it is a resolved absolute path; (3) the lock - the value in
  `.claude/.guard-coldstart-ms` and how often `run-guard.sh: note: waited ... proceeded without
  serialization` appears in a fan-out; (4) the per-call `sh` spawn itself - time
  `sh .claude/hooks/run-guard.sh scripts/bash_hook_dispatcher.py < payload.json` once cold and
  once warm from Git Bash. No shipped probe prints these timings yet; `engage_probe` prints
  `DOUBLE_HOOKS`, `tier_probe` covers the launcher tiers only.
- **Two copies that can drift.** In that session the hooks resolved to the working checkout
  (`.../virt-surv-IT/.claude/hooks/`) while skills and docs resolved to the plugin cache at
  0.37.0. `engage_probe` already reports this shape as `DOUBLE_HOOKS=1` (the project is the
  team repo and the plugin is installed), and `.claude/skills/.shared/engage-open.md` tells the
  open what to say; a check that the hooks root and the skills root are the same install is a
  follow-up, not yet written.
- **The guard lock directory in a client project.** `.claude/.guard-lock/` is ignored by this
  repo's own `.gitignore`; a plugin cannot edit a host project's, and the `VSIT/.gitignore` the
  team writes covers `engagements/` and `local/` only. A client project that commits its
  `.claude/` folder can pick up a transient lock directory. Moving the lock under
  `VSIT/local/` (the two-location rule the interpreter cache already follows) is the fix; not
  done in the leak fix of the same day, which only silenced the shell error.
- **Launcher Update option repaints over printed text.** Owner's words: "choosing the Update
  option in the launcher shows text printed behind the TUI, which flashes up". Launcher-tier
  rendering on the corporate box; needs WINTEST or the owner's box to reproduce.
- **Plugin-mode sandbox has no Markdown renderer.** The eval harness's plugin-mode session could
  not render `.html` siblings (`render_html` needs the `markdown` and `bleach` packages, which
  are not vendored the way `convert_file`'s dependencies are), so a close cannot complete there.
  Vendoring them is the candidate fix.

</details>

<sub>[↑ Back to top](../README.md#readme-top)</sub>
