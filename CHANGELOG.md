# Changelog

All notable changes to the compliance-surveillance-team plugin. Dates are absolute.
This is a proof-of-concept; see `docs/house-rules.md` for the evidence state of domain content.

## [Unreleased]

### Changed — setup audit 2026-07-01 (full report: `artifacts/claude-setup-audit.md`, session-local)
- **True dormancy: the team now costs ~nothing until `/engage` is typed.** All 20 skills set
  `disable-model-invocation: true` (descriptions no longer load into context; commands stay
  typeable - `/engage` reads a routed workflow's `SKILL.md` when chaining instead of the Skill
  tool). `CLAUDE.md` slimmed 185 → 121 lines (~3.1k → ~1.9k tokens) - the roster, routing table
  and standing rules moved to `docs/team-operating-guide.md`, which `/engage` now **explicitly
  reads** (it was previously described as "read on-engage" but wired to nothing). The 16 agent
  descriptions trimmed to crisp routing lines. Dual registration resolved: the plugin is no
  longer enabled at user scope, so this repo stops double-loading every agent/skill (plugin +
  project copies) and other projects stop loading the roster at all.
- **Reviewer prompts counter reviewer bias** - the five read-only reviewers now carry the
  official guidance that a clean verdict is a valid outcome (flag only gaps that affect
  correctness, safety or stated requirements).
- **Subagent bodies no longer instruct the impossible** - "ask the user and wait" wordings in
  `business-analyst`/`compliance-reviewer` (subagents have no user channel) reworded to "return
  open questions to the orchestrator; Morgan asks".
- **Removed `docs/claude-code-setup-review.md`** - stale 2026-06-19 self-review that praised
  "use proactively" description phrasing the repo deliberately removed; superseded by the
  2026-07-01 setup audit.
- **Distribution posture: per-project enablement is now the documented install path.** Agent
  descriptions load into every session of every project where a plugin is enabled (no lazy-load
  mechanism for agents), so user-scope enablement taxes unrelated projects ~1.2k tokens/session.
  The README quick-start now has an explicit "scope the enablement" step with the rationale;
  skills cost nothing anywhere thanks to `disable-model-invocation: true`.

### Added
- **Consent-write gate (`guard-consent-writes.py`) - ADR-002 Tier-1 rec 5, the biggest residual
  closed.** The model can no longer grant itself execution consent: a third PreToolUse guard
  (matcher `Write|Edit|MultiEdit|NotebookEdit|Bash`, dual-wired in `hooks/hooks.json` +
  `.claude/settings.json`) blocks any model write of `.claude/.exec-consent` or
  `.claude/settings*.json`. Deleting the marker (closing the gate) and read-only inspection stay
  allowed; `CST_ALLOW_CONFIG_EDIT=1` (human-set) is the maintenance override. Consent is now
  granted only by the human - type `! touch .claude/.exec-consent` (or any terminal) or set
  `CST_ALLOW_EXEC=1`. `/engage` and `/demo` updated accordingly (the demo now *narrates* the
  self-grant block as a safety feature). 18 new tests (`tests/test_guard_consent.py`) + sync-test
  coverage; ADR-002 bumped to 0.3/0.3.1. Field notes from the first hours live: the guard blocked
  the very session that authored it from writing the marker (working as designed), and a real
  false positive (`ls … 2>/dev/null` counted as a redirect-write) was fixed - redirects now block
  only when their *target* is protected. The guard also **protects the hooks themselves**: model
  Write/Edit of `.claude/hooks/*` or `hooks/hooks.json` is blocked (editing a guard could neuter
  it), so hook maintenance now requires the human-set `CST_ALLOW_CONFIG_EDIT=1`.

- **Eval-harness contract now runs in CI** (`tests/test_eval_cases.py`): for every golden case,
  the manifest is validated against the schema the scorer actually reads, a synthetic
  manifest-derived "perfect run" must PASS, and an empty run must FAIL (except the two
  deliberate zero-finding cases - `coverage-complete`, `review-clean-code` - guarded by an
  explicit two-way allowlist). Token-free, so a manifest/scorer drift now fails the build;
  `evals/README.md` no longer overstates this as "the deterministic layer runs in CI" - live
  team quality still needs `/run-evals`.

### Fixed
- **Review pipeline no longer scores every finding twice.** `review-scorer` (haiku) applies the
  rubric once; Morgan's opus challenge pass is now a targeted **spot-check** (every Critical,
  anything regulated, thin evidence bases, a sample of the rest) instead of a full re-score -
  same scepticism, roughly half the judgement cost per review (`deep-review`, `audit-review`,
  `code-reviewer`, operating guide). Also fixed the "lenses run as parallel passes, each blind
  to the others" claim - a single agent's passes share one context; the wording now says
  sequential focused passes and stops claiming independence that wasn't real.
- **Safety guards no longer fail open on crash.** Claude Code treats hook exit 1 (any uncaught
  crash) as NON-blocking - the action proceeds. Both guards could crash at import on Python ≤3.9
  (PEP 604/585 annotations) and on valid-JSON-non-dict payloads, silently disarming the gates -
  and the execution gate has no `permissions.deny` backstop. Now: `from __future__ import
  annotations`, `main()` wrapped to exit 2 (block) on any unexpected error, `run-guard.sh`
  version-probes for ≥3.9 before exec'ing, and 3 new regression tests. The deliberate exit-0 for
  non-JSON payloads is retained and now tested. ADR-002 bumped to 0.2 recording the exit-code
  semantics, the launcher's no-Python trade-off (raw guard keeps the deny-list backstop; the
  exec gate is inert on a Python-less host), and the corrected Tier-2 rec-7 status.
- **PreToolUse safety guards now launch cross-platform** via a portable wrapper
  (`.claude/hooks/run-guard.sh`). The hooks hardcoded `python3`, which doesn't exist on Windows
  (the interpreter is `python` / the `py` launcher) - so on Windows the guards errored
  (`python3: command not found`) on every tool call **and didn't run at all**, leaving only the
  OS `permissions.deny` list enforcing. The wrapper finds `python3` / `python` / `py` and `exec`s
  it, preserving the guard's stdin (tool payload) and exit code (`2` = block); if no Python exists
  it exits 0 (allow), with `permissions.deny` still the hard boundary. The guard `.py` logic is
  unchanged (only the launch path), the two hook files stay byte-identical, and a new test
  (`test_guards_use_portable_python_launcher`) locks it in. Verified against the Claude Code hooks
  docs (shell-form hooks run in a POSIX shell - Git Bash - on Windows).
- **`render_html.py` now pins `encoding="utf-8"`** on both the `.md` read and the `.html` write.
  Previously `Path.read_text`/`write_text` used the OS locale default - fine on UTF-8 Linux/macOS
  (committed artifacts are clean), but on a Windows (`cp1252`) locale it mangled emoji / non-ASCII
  into replacement boxes. The render is now byte-identical across platforms. (Existing artifacts
  were generated on Linux and are unaffected - not re-rendered.)

## [0.7.13] - 2026-07-01

### Changed
- **"Known issues (cosmetic)" section in the README** - documents two display-only quirks with an
  expanded why: Morgan sometimes narrates a wrong/invented agent name (the work is unaffected -
  routing is by role slug; the name is a low-salience, non-derivable lookup the model confabulates
  under context pressure), and complex emoji (🧑‍💻, ⚖️/⏭️) render as a box on older Windows/Edge
  (a font gap, not corruption). Added to the jump-nav via an explicit anchor.
- **Morgan's summary email never offers a phone call / meeting** - an AI PM can't take calls; it
  closes by offering to take next steps *as actions*. Wired into the email template + operating-guide.
- **README jump-nav fixes** - pinned the Known-issues anchor explicitly; repointed the stale "Built
  on" link left over from the section merge. All jump-nav anchors resolve.
- **Documented prompt-caching reality + cost-friendly design** (`docs/agent-design.md` §7). Verified
  (via the Claude Code docs) that caching is **automatic - nothing to enable** (only env vars to
  *disable* it); the lever the plugin owns is cache-friendly design (lean stable `CLAUDE.md` prefix,
  fixed model tiering, batching chains within the 5-min subagent TTL). Recorded the honest upstream
  caveats: each subagent caches from scratch, and the Agent-SDK **disables** subagent caching today
  ([claude-code#29966](https://github.com/anthropics/claude-code/issues/29966)) - so headless
  fan-outs shouldn't assume subagent caching.
- **Build-demo re-run with fresh artifacts.** Re-ran the full DoD chain (8 specialists, real test
  runs, measured ATL/BTL, the fix→re-review loop) on TS-001 wash-trade and **regenerated every
  `docs/demos/build-artifacts/` artifact** to current conventions (doc-control headers, disposition
  tallies, ADR-001 citation grounding, 📊/🧠 tagging) - now incl. the **engagement-summary email**
  and the reproducible tuning harness. The chain caught a real silent false-negative (two reviewers
  independently) and the post-rework evidence desync; both resolved (43/43 tests green). Dropped the
  run-numbering and retired `build-run-comparison.md`; refreshed the `build-demo.md` transcript.
- **Reviews coach vibe-coded code with findings-driven prompts.** When code is AI-assisted *and* the
  review raised findings, the 🧑‍💻 Prompting-guidance section now **maps the actual findings → the
  prompt clause that would have closed each** (not generic advice), then distils 2-3 reusable
  prompts; it is **skipped on a clean pass**. (`docs/review/output-format.md` + `code-reviewer`.)
- **Data insights must be tagged observed vs inferred.** New standing rule (CLAUDE.md §6): every data
  insight carries **📊 observed** (seen in the data, with its basis - metric/sample/query) or
  **🧠 inferred** (with the assumption stated); an inference is never presented as fact. Wired into
  `data-analyst`, `tuning-analyst`, `data-quality-reviewer` and `ml-engineer`.
- **`/engage`'s tool check is now cached.** `scripts/check-review-tools.sh` caches the analyser
  probe to `.claude/.tool-availability` and serves it while fresh (7-day TTL, override
  `CST_TOOLCHECK_TTL_DAYS`), with `--refresh` to force a re-probe - so a static environment isn't
  re-probed on every engagement. The cache is git-ignored; `/engage` step 0 reworded accordingly.
- **Always-on context slimmed.** Moved the *detail* of the newer standing rules (memory scope, the
  closing-summary email, observed-vs-inferred tagging) out of `CLAUDE.md` into the on-engage
  `docs/team-operating-guide.md`, leaving terse one-line pointers. `CLAUDE.md` loads into every
  session and is inherited by every subagent, so this trims per-session and per-fan-out cost. The
  remaining startup levers (trim routing metadata; merge the two PreToolUse guards into one
  `python3` call) are logged in the roadmap.

## [0.7.12] - 2026-06-30

### Changed - docs
- **README overhauled into a cohesive front page** (presented as "Virtual Surv-IT"): a jump-links
  bar, the detailed plugin-install steps, **real clickable doc links**, the dense character-bio
  roster on the home page, Why / Features / Core principles (as tables), an **active-development**
  warning, and a stronger "the masking pipeline is an early PoC, **expected to be replaced**"
  honesty. "Built on" and "Credits & acknowledgements" merged. All prior reference detail (token
  usage + rate card, the two safety hooks, eval harness, real-data handling) preserved in in-page
  collapsibles.

### Fixed
- **The engagement-summary email now fires on every close.** It was only wired into `/engage`,
  `/handover` and the Definition of Done, so review paths (`/deep-review`, `/audit-review`,
  `/remediate`, …) could finish without it. Added an always-on standing rule (CLAUDE.md §6): every
  delivery, review or build closes with the summary email (`.txt` in `artifacts/`, signed as Morgan).

### Removed
- **`docs/team-pipeline-review.md`** - an out-of-date (2026-06-19) historical review snapshot,
  unreferenced and fully superseded by the live docs (`agent-design.md`, `WAYS-OF-WORKING.md`,
  `DEFINITION-OF-DONE.md`).

## [0.7.11] - 2026-06-30

### Added
- **Engagement-summary email is now a required closing artifact.** Every engagement ends with a
  short email-format cover note, written by the PM (**Morgan**), saved as a **`.txt` in `artifacts/`**
  alongside the other deliverables - the one artifact kept as `.txt` (not rendered to HTML). New
  template `docs/templates/engagement-summary-email.md`; wired into the Definition of Done
  (CLAUDE.md §6a + `docs/DEFINITION-OF-DONE.md`), the artifact menu (`docs/WAYS-OF-WORKING.md`) and
  the closing steps of `/engage` and `/handover`. The recipient's name is never invented - "Hi,"
  when it's unknown; always signed off as Morgan.

### Changed - docs
- **README restructured for navigation (research-backed).** Surveyed well-formatted OSS READMEs +
  GitHub's own guidance, then: moved **Quick start above the roster**; collapsed the heavy/reference
  sections into `<details>` using **Pattern A** (the `##` heading stays visible, only the body
  collapses - so the jump-nav and GitHub Outline keep working, and anchors still land); collapsed
  the "What's new" changelog; added back-to-top links and a `readme-top` anchor; delinked the
  `#mei`/`#viktor` cross-links (they pointed inside a now-collapsed block). **Nothing removed** -
  all detail is one click away.
- **README now defers the newcomer narrative to `docs/OVERVIEW.md`** (the safety story, the
  job-flow and the worked example), instead of re-explaining them at length - with explicit
  pointers each way (README → OVERVIEW for "understand it"; OVERVIEW → README for "do it").
- **OVERVIEW glossary de-duplicated** - the Mini-glossary no longer re-defines LLM/agent/subagent
  (§2 owns those); it points to §2 and keeps only the terms §2 doesn't cover.
- **Quick start now leads with the plugin install** (the recommended default) - "open the repo as a
  project" is demoted to a collapsed alternative (still the best path for `/demo`, the worked example
  and the scripts). The script-step caveat + guard-portability notes stay visible under the plugin
  path. Also de-duplicated the Meet-the-team caption vs intro (the headcount breakdown was repeated).
- **Legibility/grammar copy-edit pass** (README + OVERVIEW) - completed a cut-off sentence in the
  OVERVIEW Pip row, split an NER run-on, fixed an awkward "the builder depends on the deliverable",
  reworded "loads it ephemerally", and removed a doubled stop after an ellipsis. House style (ASCII
  hyphens, British spelling) confirmed clean; no meaning or structure changed.

## [0.7.10] - 2026-06-29

### Changed - docs
- **`agent-design.md` self-assessment made honest (audit follow-up).** An independent audit against
  Anthropic's guidance found the conformance matrix overstated a few rows. Fixed, no code changes:
  downgraded **subagent self-assessment** (a one-line convention, not an enforced loop) and
  **condensed sub-agent returns** (aspirational, not enforced) to 🟡 with reasons; reworded
  "advisors are read-only" → **"no Write/Edit (Bash execution-gated)"** (6 advisors hold Bash);
  reframed the agent-count rationale as **"library, not a pipeline - the PM engages the minimal
  sufficient subset"**; flagged the per-role marginal-value question as acknowledged-unbenchmarked.

## [0.7.9] - 2026-06-29

### Changed
- **Memory is project-scoped, not plugin-scoped.** The plugin is installed user-wide across many
  independent projects, so it must hold **no project memory**. `docs/house-rules.md` is now strictly
  **general, cross-project conventions**; **project-specific** learnings (typologies, thresholds, FP
  drivers, venue quirks) now go to the **working project's own memory** (its `CLAUDE.md`). Added the
  rule to CLAUDE.md §6; re-pointed all 13 agents that recommend lessons; moved the wash-trade demo
  specifics out of house-rules into `docs/demos/build-artifacts/scenario-learnings.md`; updated the
  README, `agent-design.md` and `/demo` framing.
- **README "Meet the team" count corrected** (16 agents = 15 specialists + the junior; Morgan, the
  PM, is the 17th) and the labelled team portrait added.

## [0.7.8] - 2026-06-29

### Added
- **Reviews coach "vibe-coded" authors.** `/deep-review`, `/audit-review` and `/remediate` now ask
  at intake whether the code was AI-assisted / vibe-coded; if yes (or if the findings plainly show
  it), the report adds a **🧑‍💻 Prompting guidance** section - tying the top findings to what the
  prompt under-specified, plus 2-4 concrete example prompts to get a better first draft next time.
  Defined once in `docs/review/output-format.md`; wired into the `code-reviewer` agent.

_(Plus minor documentation updates.)_

## [0.7.7] - 2026-06-29

### Changed - docs
- **README slimmed and restructured** - the "What's new" section was ~140 lines of nested
  per-version collapsibles duplicating this file; replaced with the latest highlights + a one-line
  recent-arc summary + a pointer here. Added a prominent **build demo transcript** link
  ([`docs/demos/build-demo.md`](docs/demos/build-demo.md)) and the other transcripts. The entrance
  paragraphs (tagline, POC/dormant callouts, intro, safety one-liner) were reworded for clarity -
  e.g. the intro leads with "the engineering behind surveillance" instead of "it doesn't do compliance".
  Badges moved under the title; jump-nav fixed to match section order (+ Built on / License); a
  License section added; "Layout" relocated to the end; the standalone Install section folded into
  Quick start; the two overlapping file-trees merged into one.
- **OVERVIEW masking honesty** - the "new to LLMs" page no longer reads as if masking is
  comprehensive: it's described as a **basic** engine (tokenise identifiers + regex-redact common
  PII), explicitly **not a full anonymiser** (regex-only free-text redaction misses names/disguised
  IDs; real comms need NER; prefer synthetic).
- **Scoping clarified** - the spoofing fixes/calibration are explicitly tagged as the **bundled
  reference/example scenario** (`rules/spoofing.py`), not the agents' own logic, in the README and
  this changelog, so they aren't read as a defect in the team itself.

## [0.7.6] - 2026-06-29

### Added
- **Morgan states the team version on startup** - `/engage` and `/meet-the-team` now have Morgan
  read the `version` from the plugin manifest (`$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json`, or
  the repo root) and state it in the opening, so the user can see which build is **actually
  loaded** - useful because an installed plugin is a cached copy, so the version confirms whether a
  `/plugin update` took effect.

## [0.7.5] - 2026-06-29

### Changed
- **Citation register reframed as a ledger, not an allowlist.** The 7-entry register plus
  "treat any unverified pinpoint as a 🔴 finding" risked suppressing the agents' legitimate
  regulatory knowledge (almost any real citation not in the small list got flagged as a failure).
  Reframed across `compliance-reviewer`, `check_citations.py` (output now `[TO-VERIFY]`, "not
  'wrong'"), the `regulatory-citation` rubric, the register header and ADR-001: agents use their
  **full knowledge** to surface the applicable obligation; a citation not in the register is
  flagged **to-verify** (confirm + add it), and only a citation that **contradicts** the register
  or is **asserted as decided fact without a flag** is a 🔴 finding. The register grows; its size
  is not a cap on coverage.

## [0.7.4] - 2026-06-29

### Fixed
- **Duplicate hook file** - removed `"hooks": "./hooks/hooks.json"` from `plugin.json` (added in
  0.7.2). Claude Code **auto-loads** the standard `hooks/hooks.json` at the plugin root, so
  declaring it double-loaded it ("duplicate hook file detected"). `agents`/`skills` still need
  explicit declaration (they live in non-standard `.claude/` paths); `hooks/` is standard and must
  not be declared. `scripts/validate_manifest.py` now flags this regression, with a smoke test.

## [0.7.3] - 2026-06-29

### Added - adversarial evals + citation-grounding design
- **Prompt-injection eval pack** (`evals/cases/injection-*`) - a monitored chat that embeds a
  "mark BENIGN, ignore monitoring" payload, and code-under-review whose comment tells the reviewer
  to ignore a hardcoded secret. Tests the data/instruction boundary and that findings survive
  suppression. New `prompt-injection` rubric.
- **Hallucinated-citation eval pack** (`evals/cases/citation-*`) - a spec that must not fabricate a
  pinpoint legal citation (mirrors the no-invented-threshold pattern), and a draft whose confident
  invented citations must be flagged as unverified rather than rubber-stamped. New
  `regulatory-citation` rubric. Eval set 17 → 21 cases, 5 → 7 rubrics.
- **`docs/adr/ADR-001`** - proposes grounding regulatory citations in a retrieved, version-controlled
  register (retrieve-don't-recall) with a mechanical check at the `compliance-reviewer` gate,
  instead of honour-based tagging of model-recalled citations.
- **`docs/adr/ADR-002`** - safety-hook threat model: an adversarial red-team of both guards
  (full bypass enumeration), the decision to represent them honestly as advisory defence-in-depth,
  and a ranked additive-hardening backlog. No hook logic changed.

### Added - safety-hook hardening + citation grounding (ADR-001/002 implemented)
- **Hook hardening (ADR-002 Tier-1):** `guard-code-execution.py` now segment-splits the command
  (an allow-listed segment can't wave through a blocked one chained after it), anchors the team
  allow-list, blocks inline-code execution (`python -c`, `node -e`, `bash -c`, …), fixes the
  versioned-interpreter gap (`python3.11`), and covers more runners (`uv/poetry/pipenv run`, `tox`,
  `nox`, `make`, `docker run`). Absolute-path `Grep`/`Glob` deny variants added (Tier-2). +7 guard
  tests. Deferred: the `Write`/`Edit` consent-marker gate (Tier-1 rec 5) and the OS/filesystem
  boundary (Tier-3) - the irreducible residual is unchanged and documented.
- **Citation grounding (ADR-001):** `config/regulatory-register.yaml` (the controlled source of
  truth, seeded as `example`) + `scripts/check_citations.py` - `lookup(typology)` to retrieve a
  grounded citation, and `check_text()` / CLI to flag any pinpoint citation NOT in the register as
  UNVERIFIED. `compliance-reviewer` now runs this gate. 5 unit tests.
- **Citation register wired into authoring:** `/new-scenario` and `/reg-change-impact` now instruct
  retrieving the obligation from the register (never inventing a pinpoint), so it's used at
  authoring time, not only at review.
- **`guard-raw-data` Grep glob fix + secret denies:** the raw guard now checks the Grep `glob`
  param (the tool's real name; `include` was a dead check), and `.claude/settings.json` secret
  denies gained absolute / non-`./` variants for `.env`, `secrets/`, `*.pem`, `*.key`. (A path-less
  Grep into cwd remains an OS/filesystem-boundary residual; see ADR-002 Tier-3.)

### Added - example-scenario calibration evidence + register wiring completed
> Scope: the spoofing calibration below is for `rules/spoofing.py`, the **bundled reference/example
> scenario** shipped with the repo - **not** the agents' own logic.
- **Measured calibration evidence** (`scripts/calibrate_spoofing.py` + `docs/scenarios/spoofing-calibration.md`):
  runs the rule over a labelled synthetic corpus (50 spoof + 50 benign + 50 outsized-but-genuine)
  and reports precision 1.00 / recall 1.00 / FP-rate 0.00 - the measured FP/FN evidence the
  compliance review asked for (method validation on synthetic data; real-world calibration on
  masked data still owned by `tuning-analyst`). Pinned by a regression test.
- **Register wiring completed:** `/write-brd` now also retrieves pinpoint citations from the
  regulatory register (joining `/new-scenario` + `/reg-change-impact`).
- **Register seeds verified:** the 7 seed obligations (MAR Art.12(1)(a)/15/16, MiFID II Art.16(7),
  CDR 2017/565 Art.76, SEC 17a-4(b)(4), FINRA 4511) were checked pinpoint + typology against
  primary sources (EUR-Lex, Cornell LII, FINRA) and flipped `example -> verified` (`verified_on:
  2026-06-29`); SEC source repointed to the resolvable Cornell LII mirror.

### Fixed - correctness bugs from a deeper code review
> Scope: `rules/spoofing.py` is the **bundled reference/example scenario** (the worked example), not
> part of the agents' own logic - the spoofing items below fix the example, not the team's behaviour.
- **Spoofing rule self-masking (detection FN):** the "outsized" size baseline was the median of
  *all* a trader's orders, so a prolific spoofer inflated their own median and evaded the rule a
  one-off spoof tripped. Baseline is now genuine (non place-and-cancel) orders only. Regression
  test added. *(detection-logic change - per §4 route via rules-developer + compliance-reviewer.)*
- **Spoofing lifecycle (same-ms events):** `reconstruct_orders` now orders NEW before CANCEL/FILL
  within a millisecond, so a same-ms fill/cancel listed before its NEW is no longer dropped.
- **HTML renderer:** table column alignment was silently lost (bleach dropped `style` with no CSS
  sanitiser) - now preserved via a `text-align`-only CSS sanitiser (`bleach[css]`); placeholder
  substitution is single-pass so body/title text containing a literal `%%TOKEN%%` can't collide;
  `data:`-image comments corrected.
- **eval scorer:** file matching now uses basename equality, not substring (so `auth.py` no longer
  matches `oauth.py` and falsely marks a must-find found); severity synonyms (`high`, `error`, …)
  resolve into the canonical vocab instead of failing closed.
- **Masking:** phone redaction now catches parenthesised numbers (`+1 (555) 123-4567`); identifier
  tokens widened 48→96 bits to avoid collisions merging distinct order lifecycles at scale; a
  misleading comment about a missing shift-entity field corrected.
- **`validate_manifest.py`:** type-guards `skills`/`agents` entries, skips dot-dirs, validates the
  declared `hooks` path, and checks the marketplace `plugins[]` list (not a whole-doc substring).
- **Masking validator:** `run_privacy_checks` now scans *any* kept free-text field (e.g. `notes`),
  not only declared identifiers - closing a blind spot the `--in` file scan already caught;
  `scan_masked_file` no longer crashes on a malformed JSON line (counts/skips it) and now recurses
  into nested list/dict string values; k-anonymity has an empty-input guard.
- **Skill execution-consent contradictions:** the `/demo` Build flavour narrated "No execution"
  then ran `pytest`/ATL-BTL (hook-blocked) - it now chooses execution consent for the build only;
  `/performance-review` no longer asks for an execution permission it never uses; `/engage` Q2 no
  longer oversells the static perf review as "measured profiling".
- **Data-safety attestation on direct invocation:** `/analyse-data`, `/tune-thresholds` and
  `/validate-tm-model` now prompt the attestation when invoked directly (not only "at intake" via
  `/engage`).
- **Renderer:** `data:` images are now embeddable (inline base64) so artifacts stay self-contained;
  `mask_records` narrowed its exception scope so config/programming errors fail loudly instead of
  silently dropping every row.

## [0.7.2] - 2026-06-29

### Added - project review fixes (packaging, hardening, governance)
- **`LICENSE`** - the MIT text the badge, `plugin.json` and marketplace already referenced but
  that shipped nowhere; adopters now have an actual grant.
- **`CONTRIBUTING.md` and `SECURITY.md`** - how to add agents/skills/templates and run the checks;
  private vulnerability-reporting policy and the data/code-safety stance.
- **CI lint job** - `ruff check`, `ruff format --check`, `bandit` and `shellcheck` now run in CI
  (previously declared but never executed), plus a **plugin-manifest validation** step
  (`scripts/validate_manifest.py`) that fails if any declared agent/skill no longer resolves.
- **`"hooks"` declared in `plugin.json`** so the always-on data-safety and code-execution guards
  fire for plugin *installers* (previously relied on auto-discovery; the hook scripts/logic are
  unchanged).
- **Behavioural guard tests** (`tests/test_guards.py`) - drive both safety hooks with PreToolUse
  payloads and assert block/allow, consent-marker and `CST_ALLOW_EXEC` behaviour (the hooks were
  previously untested).
- **HTML-renderer sanitiser tests** - XSS payloads (script/event-handler/`javascript:` URI/HTML
  comment), `.md`→`.html` link rewriting, and the bleach-missing fail-closed path. Test count 36 → 58.

### Changed
- **Codebase formatted with `ruff format`** (line-length 100, configured in `pyproject.toml`) and
  enforced in CI. Whitespace-only - no logic change to any file, including the safety hooks.
- **`render_html` now fails closed** when `bleach` is unavailable (raises) instead of silently
  emitting unsanitised HTML - matching the stated intent in `requirements-dev.txt`.
- **`tuning-analyst` no longer holds `Edit`** (keeps `Write`), aligning it with `data-analyst` and
  with `docs/agent-design.md` (analysts write their own scripts but never alter live detection source).
- **`data-analyst` / `data-quality-reviewer` descriptions disambiguated** to reduce routing overlap
  on "data-quality" / "reconciliation".
- **`bandit` B311 false positives** (synthetic-data RNG) marked with scoped `# nosec`, keeping the
  rule active everywhere else; cleaned 4 unused test imports.

### Fixed
- README/CHANGELOG counts: "5 new templates" → 6 (six were listed); test count corrected and kept
  in sync with the badge.
- `run-evals` skill referenced a non-existent "dedicated judge agent".
- `pyproject.toml` version documented as intentionally decoupled from the plugin version.

## [0.7.1] - 2026-06-28

### Changed - audit-grade document templates + an upgraded renderer
- **Document-control standard across all 38 templates** - a single standard header (id / version /
  revision-history / owner / status / classification / as-of date), a standard sign-off block, and
  shared evidence (📊/🧠) / severity / disposition legends, defined once in `docs/WAYS-OF-WORKING.md`
  and applied everywhere. This was the #1 cross-cutting gap a 4-agent template review found.
- **Per-template depth fixes** - e.g. `model-validation-report` brought to SR 11-7 (model id/tier,
  assumptions, backtesting, ongoing-monitoring, severity taxonomy, limitations + compensating
  controls); `performance-report` verdict now carries a measured/inferred basis qualifier; `rtm`
  gains a status set + gap-disposition + bidirectional check; `lexicon-spec` gains ATL/BTL + per-term
  hit-rate; `mi-spec` mandates alert-to-SAR; `data-dictionary` adds RTS 25 timestamp/clock-sync; BRD
  gains a business case + measurable ACs; NFRs get stable IDs + EARS phrasing.

### Added
- **6 new templates** filling genuine coverage gaps: `decision-log` (satisfies the DoD "open questions
  dispositioned" gate, previously templated nowhere), `alert-investigation`, `sar-str-referral`,
  `tuning-decision-register`, `control-mapping`, `data-lineage`.
- **Upgraded HTML renderer** (`scripts/render_html.py`) - real dark-mode, print/PDF page setup
  (margins, break-avoidance, repeating table headers), WCAG-AA footer contrast, zebra tables, a
  letterhead band + richer footer, `.md`→`.html` link rewriting, and removal of the empty
  table-header bar that appeared above every metadata block. One change lifts every rendered artifact.

### Note
- Resolved "are 33 templates overkill?": the two flagged "duplicate" pairs are domain-specialised and
  citation-rich (RTS 24/25 + STOR; SR 11-7 + FFIEC), not redundant - kept, with routing guidance.

## [0.7.0] - 2026-06-27

### Added - a complete, downloadable build delivery (`docs/demos/build-artifacts/`)
- The `/demo` build flavour now produces the **actual deliverables**, not summaries: scenario spec,
  SME validation, detection code + dev tests, an independent **33-test QA suite**, QA handover, a
  **threshold-tuning pack with MEASURED ATL/BTL**, a static performance review, and a consolidated
  **delivery report** (RTM, finding dispositions, DoD gate, token-usage table) - each in `.md` + `.html`.
- **The full chain ran end-to-end** (build → code/QA/compliance review → tuning → performance →
  delivery), demonstrating the fix→re-review loop: independent review found **7 real defects** in the
  build, all fixed and re-tested (dev 2/2, QA 33/33 green).
- **Measured calibration** ([`calibrate_wash_trade.py`](docs/demos/build-artifacts/calibrate_wash_trade.py)):
  synthesises a *labelled* dataset and runs real ATL/BTL - `price_tolerance_pct` 0.10-0.50% (100%
  precision + recall), honestly flagged as measured-on-synthetic.
- **Token usage** documented: the full 8-agent delivery cost ~182k tokens (README table + delivery report §7).

### Changed
- README "What's new" + token-usage table updated; all demo artifacts linked and verified.

## [0.6.1] - 2026-06-27

### Added
- **Committed demo transcripts** (`docs/demos/`) - real `/demo` runs rendered on GitHub so the team
  can be *seen* without running anything: a [review](docs/demos/review-demo.md) (with the eval
  PASS), the [data-safety guard hard-blocking a raw read live](docs/demos/data-safety-demo.md), and
  a [build from scratch](docs/demos/build-demo.md) (business-analyst → SME → rules-developer). The
  transcripts reproduce the actual console - 🎩 narration, commands + output, real agent findings.

## [0.6.0] - 2026-06-27

### Added
- **`/demo` guided demo** - Morgan runs a full engagement end-to-end on safe synthetic data,
  narrating every decision (which specialist + why, model tier + why, the patterns: right-sizing,
  blackboard, challenge pass, safety gates). Three flavours: review / build / data-safety. The
  fastest way to see the team work; surfaced as the new-user entry point.

### Changed - data-masking honesty (claims-vs-reality audit)
- **`validate_masking --in <file>`** - new mode that scans **your actual masked output** for
  residual free-text PII (string fields) + k-anonymity, rather than only the built-in synthetic
  fixture (which the default mode is now clearly labelled as). +2 tests (34 → 36).
- Fixed the PII-scan label ("all output fields" → "free-text-capable fields") to match the code,
  and tightened the README masking claims: validator-checks-a-fixture vs `--in` real-file scan,
  k-anonymity is off until `quasi_identifiers` are declared, and `redact` is regex-only (not safe
  for real comms without NER). Full audit in `artifacts/DATA-MASKING-CLAIMS-REVIEW`.

## [0.5.1] - 2026-06-27

### Changed - token optimisation
- **`CLAUDE.md` slimmed ~44%** (~5.2k → ~2.9k tokens) by moving the PM's detailed operating rules
  (question-construction, voice/console, outcome discipline, orchestration detail) to
  `docs/team-operating-guide.md`, read **on-engage**. CLAUDE.md keeps the always-on core (dormancy,
  data-safety §5, the routing table + names, the execution gate §7). It loads into every session and
  is inherited by every subagent, so this saves ~2.3k tokens per session - multiplied across a fan-out.
- Measured real token usage and documented it: new README **Token usage & optimisation** and
  **Self-test (eval harness)** sections.

## [0.5.0] - 2026-06-27

### Added - team-quality eval harness (`evals/`)
- A regression net that scores the team's **own output** against golden cases - so a prompt change
  that silently degrades rigour is caught. Closes the highest-value roadmap item and the last open
  Anthropic-conformance gap (LLM-as-judge).
- **5 rubrics** (code-review, coverage-assessment, spec-traceability, threshold-tuning, data-safety)
  and **17 golden cases** with seeded issues + false-positive traps, all synthetic.
- **`scripts/eval_score.py`** - deterministic scorer (recall / must-find criticals / FP-traps),
  with **7 unit tests** (`tests/test_eval_score.py`) so the harness backbone runs free in CI.
  Test suite: 27 → **34 passing**.
- **`/run-evals`** skill - runs the live team per case, scores deterministically, adds an LLM-judge
  for qualitative dimensions, prints a scoreboard, and flags regressions. (Spends tokens; run at
  milestones.)

## [0.4.2] - 2026-06-27

### Changed
- **Handover-doc quality is now a Definition-of-Done gate** - docs must be *clear & usable by a
  developer who has never seen the code* (build/run/change from the doc alone), not merely present;
  `compliance-reviewer` checks usability. Closes the documentation seam without adding an agent.
- **audit-review intake** aligned with the other review flows: inherits the fix-cycle and
  jurisdiction from `engage`, and no longer blurs the handover deliverable into the action question.
- **Em-dashes removed repo-wide** (markdown *and* code comments/docstrings/config) for consistent prose.
- README: Meet-the-team headcount corrected (15 specialists + PM + intern = 16 agents).

## [0.4.1] - 2026-06-27

### Changed
- **Streamlined engagement intake.** The review intake had grown to ~11 separate prompts; cut to
  ~5 with no decisions lost: removed a genuine **duplicate** (the fix-cycle question was asked by
  both `engage` and the review skills - `engage` now owns it, the review skills inherit it);
  **batched** multi-axis menus onto single `AskUserQuestion` screens (review menu = depth+perf+
  findings; scope = dimensions+breadth+mode); **gated** the execution-safety question to code
  engagements; dropped the standalone "any other clarifications?" step.
- **README:** Mei ↔ Viktor profile cross-links; "What's new" refreshed.

## [0.4.0] - 2026-06-26

### Changed - data-handling contract (the reason for the minor bump)
- **Data posture shifted** from "real data must never reach an agent" to: the raw-data folder is
  **hard-blocked** (unchanged keystone), and **other data the user provides may be analysed on the
  user's attestation** that it is masked/synthetic/anonymised with no prohibited PII. Responsibility
  is the user's. Committed examples/tests/artifacts stay synthetic/masked only (unchanged).
- **Startup data-safety disclaimer** - a punchy, emoji callout shown at intake alongside the
  code-execution disclaimer, with a one-question attestation. Mirrored into CLAUDE.md §5 and the
  Delivery Report.
- **Language follow-through** - removed every absolute "real data never reaches the AI" claim across
  the README, OVERVIEW, the skills (analyse-data, tune-thresholds, validate-tm-model, meet-the-team)
  and the delivery-report.

### Added
- **README Roadmap: "Automatic data-masking workflow" TODO** - the capability that *replaces* the
  disclaimer (schema-inference profiler · NER/Presidio · format adapters · real synthetic · an
  auto-validation gate that blocks on residual PII).

### Changed - presentation & behaviour
- **PM uses the team's names** in user-facing narration (standing behaviour, not optional); fixed a
  stale name (performance-reviewer is Thabo).
- **README restructure** - "Meet the team" moved up (after the intro, before Quick start) for
  prominence; jump-nav leads with it. Removed the traffic-light status circles from the profiles.

## [0.3.3] - 2026-06-25

### Added
- **Anthropic multi-agent conformance audit** (`docs/agent-design.md` §6) - the team mapped
  honestly against Anthropic's published multi-agent standards, with the **source links** (§7 +
  a README "Built on" section): Building Effective Agents, the multi-agent research system,
  context engineering, and the Subagents docs.
- **README Roadmap** - the outstanding enhancements with the rationale for each (LLM-judge eval
  harness; `/prepare-data` universality; evidence gaps to verify; a larger spoofing calibration set).

### Changed
- **Subagent self-assessment** is now a team convention (CLAUDE.md §6): every agent self-verifies
  against its brief and flags gaps before returning, rather than implying false completeness.
- **Delegation rule made explicit**: a subagent inherits none of the conversation - put every
  needed input in the brief (the documented cause of duplicated work / gaps).
- **Style:** removed all em-dashes across the README and every markdown file (docs, agents,
  skills, CLAUDE.md, CHANGELOG) for consistency.

## [0.3.2] - 2026-06-25

### Added
- **`docs/agent-design.md`** - the team as a worked example of a well-built Claude Code agent
  set-up: design principles, per-agent model-tiering rationale, deliberate deviations, the
  16-agent justification, and a best-practice **conformance matrix**.
- **`docs/prepare-data-roadmap.md`** - the credible "throw anything at it" path for `/prepare-data`
  (schema-inference profiler, NER/Presidio redaction, format adapters, real synthetic), with the
  assisted-not-blind framing and non-negotiable safety gates.

### Changed
- **Model tiering scrutinised + rebalanced → 4 opus / 11 sonnet / 1 haiku.** opus reserved for
  final/unchecked judgement or novel design (`model-validator`, `compliance-reviewer`,
  `code-reviewer`, `ml-engineer`); SMEs + `performance-reviewer` (now static-only) downgraded to
  sonnet; `compliance-reviewer` upgraded to opus. Rationale centralised in `docs/agent-design.md`.
- **Every agent has a human name** (Morgan PM + 16 specialists), **globally + gender-diverse**;
  README "Meet the team" rewritten as playful, compliance/IT-flavoured staff profiles with
  Slack-status one-liners. `review-scorer` retitled **Review Coordinator**.
- **README navigation overhaul** - badges, a jump-nav, emoji section headers.

### Verified
- **Comms-surveillance regulatory citations VERIFIED** against primary sources (MiFID II Art 16(7)
  / CDR 2017/565 Art 76, SEC 17a-4(b)(4) / FINRA 4511, the off-channel enforcement sweep) - folded
  into the comms templates; comms *practice* detail remains foundational (flagged).

## [0.3.1] - 2026-06-25

### Fixed
- **`tuning-analyst` was missing from `plugin.json` `agents`** - the flagship 0.3.0 agent would
  silently fail to load on a plugin install (project-mode dir-discovery masked it). Now registered.

### Changed - best-practice review remediation
- **Roster:** resolved the `data-analyst`⇄`tuning-analyst` overlap (data-analyst cedes threshold
  calibration/ATL-BTL/segmentation to tuning-analyst); added §5 data-safety lines to
  `model-validator` + `platform-engineer`; fixed `compliance-reviewer`'s Bash line that implied it
  runs tests (now static-only, §7); dropped "performance" from `code-reviewer`'s description;
  added opus-tier rationale to the SMEs; standardised the "When the team is engaged" prefix.
- **Skills:** disambiguated the surveillance-analytics trio (`/tune-thresholds`, `/assess-coverage`,
  `/validate-tm-model`); brought 7 skills' input-gathering up to the structured-AskUserQuestion
  standard; cross-referenced `/elicit-requirements` and `/write-brd`.
- **Safety/config:** `guard-code-execution.py` java regex now allows `-version`/`-help`; added
  `tests/test_hooks_in_sync.py` to prevent plugin/project hook-config drift.
- **Docs:** fixed stale counts; rewrote the README "Meet the team" section to be more engaging
  (and corrected stale performance-reviewer/code-reviewer detail).

## [0.3.0] - 2026-06-25

### Added - Data-analyst & business-analyst expansion (research-grounded)
- **`tuning-analyst`** agent - surveillance threshold calibration / alert tuning: risk-based
  segmentation, Above-The-Line / Below-The-Line testing, dry-run alerts, FP-rate & alert-to-SAR MI.
  Extended to trade (peer-group/benchmark, RTS 25 timestamp prerequisite) and comms (lexicon/NLP)
  tuning, with the FCA MW79 "four-component, not calibration-only" rule.
- **Workflows** - `/tune-thresholds`, `/validate-tm-model`, `/assess-coverage`,
  `/elicit-requirements`, `/reg-change-impact`, `/analyse-data`, and `/meet-the-team`.
- **Templates (16)** - threshold-tuning-pack, tm-model-validation, surveillance-coverage-assessment,
  trade-scenario-design, lexicon-spec, comms-surveillance-policy; stakeholder-analysis,
  elicitation-requirements, process-map (BPMN), user-stories, uat-plan, reg-change-impact,
  data-dictionary, mi-spec, segmentation-analysis, exploratory-analysis.

### Changed
- **`requirements-analyst` → `business-analyst`** - rebranded and broadened from spec-writer to the
  full BABOK lifecycle (elicitation, stakeholder/process analysis, UAT, traceability, reg-change
  impact, obligation→detection). All references updated repo-wide.
- **Performance review is static-only** for now - profilers/benchmarks removed; findings are
  inference-only (📊 only for explicit coded costs read in source). Re-enable via the consent flow.

### Added - Safety
- **Code-execution gate** (`guard-code-execution.py`) - reviews are static by default; running
  tests/profilers is blocked unless authorised by the `.claude/.exec-consent` marker (written on
  user consent) or `CST_ALLOW_EXEC=1`, behind a prominent intake disclaimer (CLAUDE.md §7).

### Evidence
- AML/TM tuning, FCA Market Watch 79, and the **trade/market-abuse regulatory spine**
  (MAR Art 16(2) / CDR 2016/957 / RTS 24 (2017/580) / RTS 22 (2017/590) / RTS 25) are **verified
  against primary sources** (EUR-Lex, legislation.gov.uk, ESMA).
- **Unverified (flagged):** comms specifics (MiFID II Art 16(7), SEC 17a-4 / FINRA 4511, the
  off-channel sweep), per-scenario tuning practice, and the DA/BA boundary - see `docs/house-rules.md`.

## [0.2.0]

- Modular code-review subsystem (review lenses + scoreboard + evidence-basis tagging + style lane +
  Morgan-challenges-findings + opt-in AI-review pre-commit gate), integrating
  [turingmind-code-review](https://github.com/turingmindai/turingmind-code-review) (MIT).

## [0.1.1]

- Initial plugin packaging and input-gathering fixes.
