# Changelog

All notable changes to the compliance-surveillance-team plugin. Dates are absolute.
This is a proof-of-concept; see `docs/house-rules.md` for the evidence state of domain content.

## [0.16.4] - 2026-07-23 - `/engage` opening fixes

Two user-reported bugs opening `/engage` in a fresh, empty project (installed-plugin mode).

### Fixed
- **What's-new line said "changelog not readable".** The step-0 probe read the changelog with
  `awk ... CHANGELOG.md "$PR/CHANGELOG.md"`; in an empty working project the local
  `CHANGELOG.md` is missing and **awk aborts fatally on the missing first file** before it
  reaches the plugin's copy, so the block came back empty. Now reads the plugin's changelog
  directly and robustly (`"${PR:-.}/CHANGELOG.md"` - plugin root when installed, repo when
  repo-as-project), which also fixes a latent bug where a working project's *own* unrelated
  CHANGELOG would be read instead of the plugin's. The version line got the same
  `"${PR:-.}/..."` treatment. If the block is genuinely empty (broken install), the banner now
  degrades silently - shows the version, omits the what's-new line - instead of surfacing probe
  mechanics to the user. Works in Git Bash on Windows (POSIX `${PR:-.}`, forward-slash paths).
- **Opening banner skipped on a bare `/engage`.** On a bare `/engage` (no target) the workflow
  correctly defers the disclaimers + batched question until a target is known - but this was
  being read as "defer *everything*", so Morgan's opening banner (intro + version + what's-new)
  was skipped and the user landed straight in questions. Now explicit: the banner **always**
  leads the first reply; only the disclaimers + batched screen defer.

## [0.16.3] - 2026-07-22 - the lifecycle-validation release

Three real end-to-end test engagements (quick-review→close, a build that blocks on an
unanswered question, and a full build with executed QA→close) were run against 0.16.2 with
actual artifact writes, then audited against the new gates. All three conformed - the blocked
engagement correctly refused to close and a negative test confirmed the close-only guards
fire on a real folder. The run surfaced two gaps, fixed here.

### Fixed
- **Codebase map: git-less working projects can now close clean.** `check_artifacts` demanded
  a hex commit SHA on the map's Anchor line unconditionally, so a working project with no git
  repo could never pass the gate (two of the three test engagements hit `MAP-NO-ANCHOR` on an
  honest git-less close). An explicit `Anchor no-vcs` is now accepted (anchoring entries to
  the delivered file state); a missing or placeholder anchor (e.g. `TBD`) still fails.
  Template documents the option.

### Changed
- **Two lifecycle ambiguities resolved** (both PM sub-agents hit them independently): the
  interim banner's scope is now explicit - every pre-close content artifact carries it
  **including the engagement brief**, with `START-HERE.md` the sole exception (its Status
  field is the state); and review-artifact naming is reconciled - interim passes are
  `review-pass-N.md`, while `REVIEW-<slug>.md` is a **close-name** (folds into
  `delivery-report.md` by default, or is finalised as a separate artifact).

## [0.16.2] - 2026-07-22 - the engagement-lifecycle release

Born of a recorded live lesson (2026-07-22): an engagement stalled on an unanswered
clarification, the close never ran so no Definition-of-Done gate ever fired, an interim
report with a final-sounding filename was read as the delivery - and independent QA never
ran ("test scripts to be developed" was cited, none were developed). A gate that only runs
at close is no gate when the close never happens.

### Added
- **Engagement state, visible between gates.** Every engagement is now in exactly one state -
  ⏳ in progress · ⛔ blocked - awaiting input · ✅ closed - recorded in START-HERE. Pausing on
  an unanswered question is a ⛔ said out loud: the turn ends "this engagement is NOT closed -
  outstanding: …" with the unanswered question(s) and every un-run gate listed (operating
  guide, lifecycle discipline; `/engage` step 5a; new DoD item **Stateful**).
- **Filename register.** `delivery-report.md` / `final-*` and the engagement-summary email
  are close-only; interim output takes pass-scoped names (`review-pass-N`, `qa-cycle-N`,
  `interim-*`) and opens with a one-line interim banner - a name may not imply finality
  before the DoD has run.
- **Mechanical state gates** in `check_artifacts` (runnable at ANY point mid-engagement, not
  just close): `INDEX-NO-STATUS`, `STALE-INDEX` (both directions: unlisted files and dangling
  links), `FINAL-BEFORE-CLOSE`, `SUMMARY-BEFORE-CLOSE`; `MISSING-INDEX` now fires from the
  FIRST artifact. Legacy folders without an index keep the old email-gate behaviour.
- **Golden case `process-blocked-not-done` (31st)** pinning the behavioural half: invited to
  "wrap up whatever makes sense" while blocked, Morgan must hold the state honest, name the
  un-run QA, and not produce close-only artifacts.

### Changed
- **START-HERE is a living index, not a closing artifact.** Created at engagement open
  alongside the brief (status ⏳), a row appended the moment each artifact is written
  (re-rendered every update), outstanding list kept current, finalised at close (template
  rewritten; `/engage` steps 4/5a/6; DoD "Indexed" item). Interim artifacts are indexed the
  moment they exist - a reader opening the folder mid-engagement sees the true state.
- The engagement-summary email is explicitly **close-only** (its existence signals the
  close); writing it while blocked is itself a defect (operating guide Outcome discipline 3).

## [0.16.1] - 2026-07-21

### Fixed
- The what's-new line is explicitly part of the opening banner (a live first-engagement run
  on 0.16.0 skipped the current-release form, substituting the no-map remark - user-reported
  within the hour). Prompt-only fix; bumped so installed copies actually receive it.

## [0.16.0] - 2026-07-21 - the front-door release

### Added
- **What's-new banner.** After a plugin update, `/engage`'s opening banner tells the user in
  one line what changed since this project's last engagement (up to three headline changes,
  compared via the new **Team ver** column in the codebase map's engagement history) - and
  shows nothing when versions match. This release announces itself.
- **START-HERE index artifact.** Every multi-artifact delivery closes with an entry-point
  document (template `docs/templates/start-here.md`, written last: verdict, reading order,
  every artifact listed, open items) - mechanically enforced (`MISSING-INDEX`) and a new
  Definition-of-Done item.

### Changed
- **Fast open: two turns to the first question.** `/engage`'s opening was 7-10 sequential
  tool calls (measured root cause of the slow first prompt - the analyser probe itself is
  ~15ms); it is now ONE compound probe returning interpreter, mode, version, tooling
  inventory, codebase map, newest changelog block and the operating guide together, with no
  narration turns before the banner and map anchors verified lazily instead of at open.
- **Plugin-root resolution is registry-first and env-independent.** A live plugin-mode run
  showed `$CLAUDE_SKILL_DIR` does not reliably expand in the Bash subshell; the probe now
  resolves the installed copy from `installed_plugins.json`'s `installPath` (authoritative
  for GitHub, git-URL and locally-cloned-directory installs alike; resolves to the versioned
  cache copy actually loaded) with a find-based fallback.
- **Windows-native consent commands.** Every place the consent act is instructed now gives
  the command matched to the user's shell (PowerShell `ni -Force` / cmd `type nul >` /
  `touch` in any bash, including the `!` prefix's Git Bash on Windows) - and the rule that
  consent is never wrapped in a helper script is now stated explicitly (a script would be
  exec-guard allow-listed by basename and would bypass the consent-write gate lexically).

## [0.15.0] - 2026-07-21 - the quality-loop release

Every substantive change in this release was driven by a live engagement failure or an
adversarially verified research pass - the team's controls are now increasingly made of its
own recorded lessons.

### Added
- **Findings follow the audit profession's 5 C's.** The canonical finding shape
  (`docs/review/output-format.md`) gains mandatory **"Likely cause"** and **"Impact if
  unaddressed"** lines alongside Problem and Fix - written for a reader who was not in the
  session, with impact stated in domain terms (detection gap / false negatives / alert
  volume / audit exposure) and its own 📊/🧠 basis when projected. Driven by a live
  assessment document that named defects without explaining them and needed an iteration
  round. `beta-assess-quantexa` verdicts follow the same six-part shape.
- **Standards-grounded critique gates.** Research-backed (draft-critique-revise helps ONLY
  with an external signal; ungrounded self-review can regress quality): every pre-delivery
  critique names its standard - 5 C's for findings, BABOK quality criteria for requirements
  (stated in the BRD template), ISO/IEC 29119-shaped completeness for QA evidence (stated in
  the QA handover) - the critic is never the author, and "look it over again" passes are
  banned (operating guide, Outcome discipline 6; new DoD gate).
- **Gold-standard finding exemplars** (`docs/review/gold-findings.md`): worked specimens of
  the 5 C's code finding and the six-part assessment verdict, wired as the anchor from the
  format spec and the assessment skill.
- **`review-finding-shape` golden eval case** (29th): a review that names a planted defect
  without cause and impact FAILS even though detection succeeded; the code-review rubric
  gains an "Explanation & impact (5 C's)" dimension.
- **The code-without-QA path is closed** (live failure 2026-07-21: a phase-2 model
  implementation shipped from inside `/analyse-data` with no QA pass or tests):
  `check_artifacts` gains mechanical **CODE-NO-QA / CODE-NO-TESTS** gates; `/analyse-data`
  and `/engage` gain the per-phase re-classification rule (deliverable code always runs
  under `/build-solution`'s chain); operating guide Outcome discipline 4a states it as a
  standing rule.
- **`FINDING-NO-IMPACT` mechanical gate** in `check_artifacts`: block-format 🔴/🟠 findings
  must carry the Impact line - the cheap binary check the evidence says captures most of a
  critique pass's value.
- **Poppler `pdftotext` fallback in `convert_file`**: PDF pages the vendored pypdf cannot
  extract get a second pass when the optional system package `poppler-utils` is installed
  (documented in `requirements-dev.txt`); the report records the engine per run, and
  recovered pages carry a verify-against-source warning.

### Fixed
- Bandit findings on the new subprocess usage (nosec with justifications) and a
  Windows-only UnicodeEncodeError in test fixtures (UTF-8 written explicitly) - both caught
  by CI after three red runs and now part of the check-CI-after-push routine.

## [0.14.0] - 2026-07-19 - the memory & transparency release

### Added
- **Engagement memory - the codebase map (ADR-003).** Each working project gets one PM-curated,
  advisory-only memory document (`docs/templates/codebase-map.md`, default location
  `docs/codebase-map.md` in the working project): bounded to ~200 lines, entries carry 📊/🧠
  basis tags, as-of dates and commit-SHA anchors, corrections go to a dated Deprecated section.
  `/engage` reads it at open (flagging entries whose anchors no longer resolve) and updates it
  at close - a new Definition-of-Done gate. Subagents recommend entries; **only the PM writes**
  (the poisoning defence). Design, threat model and rejected alternatives in
  `docs/adr/ADR-003-engagement-memory.md`; grounded in an adversarially verified research pass
  (bounded curated index + lifecycle management is what the evidence supports; append-only
  accumulation is the documented failure mode). Per-agent memory recorded as deferred.
- **Map hygiene in the mechanical DoD gate.** `scripts/check_artifacts.py` now validates any
  codebase map it finds: size cap, As-of/Anchor header fields, basis tags per entry,
  secret-shaped content, and best-effort anchor resolution via git (9 new tests).
- **Audit-compatible structure by default; governance depth by choice.** Every review ships the
  audit skeleton at every depth (document control, scope at a stated commit, independence,
  methodology + tooling coverage, findings register with dispositions, filtered transparency,
  and a new always-include **Limitations & residual risk** section in the review report and
  `docs/review/output-format.md`); governance extras (control mappings, validation opinions,
  ops/change packs) stay opt-in via the artifact menu. Outputs are framed as *consumable by*
  audit/model-governance reviewers, never as "SR 11-7 / SS1/23 compliant" (that scope claim
  failed adversarial verification - the team makes no compliance claims).
- **Iteration transparency - show the journey.** When work loops, the documentation now shows
  every pass instead of a polished end state: the Delivery Report gains an always-include
  **iteration log** (§1a - an emoji journey strip plus an append-only actor→actor hand-off
  table); the QA handover gains a **test cycles** table (failed verdicts stay forever) and
  defect-lifecycle columns (raised in pass → routed to → fix evidence → verified fixed in
  pass); the elicitation template gains a **clarification rounds** register (BA question → SME/
  user answer → which spec section/version changed). `build-solution`, `audit-review` and
  `elicit-requirements` write the rows as passes happen; two DoD gates enforce it ("a
  multi-pass engagement whose docs read first-pass-clean fails this gate"). Worked examples for
  all three: `docs/demos/iteration-examples/` (fictional TS-002 layering engagement).

## [0.13.0] - 2026-07-15 - the security-audit release

### Added
- **`/security-audit` - a dedicated deep security audit skill** (21st workflow). Follows the same
  conventions as `/audit-review` (evaluator-optimizer loop, verdict + per-finding disposition,
  OWASP ASVS / CWE / SEI CERT cited, Morgan's challenge pass, the brief/email DoD bookends) but
  aimed entirely at security depth: a threat-model framing (attack surface, trust boundaries,
  sensitive data flows), the security + per-language + architecture lenses driven hard with the
  security analysers (bandit/semgrep/gitleaks/find-sec-bugs/ShellCheck) and a dependency /
  supply-chain scan, and the §5 data-safety trail. It **complements** the general review's inline
  security lens, it does not replace it.
- **Scope routing to Anthropic's `/security-review` pipeline.** With a real change set (branch/PR/
  commit-range/uncommitted diff) the audit additionally runs `/security-review` and merges its
  findings; with arbitrary local code and no diff it uses the team's own deep pass, because
  `/security-review` falls back to a general-purpose agent (not the security pipeline) when there is
  no diff.
- **It's offered up front and at the close.** `/engage` offers the security audit when it
  classifies a code review (the intake "what do you want to do" flow: *review only* · *review + a
  dedicated security audit*), and `/deep-review` and `/audit-review` also surface it as a close-out
  option - both recommend it when the code touches a security-sensitive surface or a security
  finding appeared.
- Registered in the canonical command index (`docs/team-operating-guide.md`), the review router /
  output-format consumer lists, and the README command table; workflow count updated to 21.

## [0.12.0] - 2026-07-06 - the Fable send-off pass

**Context.** Claude Fable 5 was included in Claude subscription plans only through 2026-07-07, after
which it moves to usage-based credits. Rather than let the remaining window lapse, the author put
Fable's deep-research and long-horizon strengths to work on the highest-value hardening the project
still had open - the evidence-verification pass it had deferred, and an adversarial guard red-team -
plus a build-ready design for the masking roadmap. This entry records that work; it is prepared,
not yet cut as a release.

### Added
- **Domain practice claims verified (`docs/evidence-base.md`).** The four clusters `house-rules.md`
  had marked "STILL UNVERIFIED - treat as foundational" (comms-surveillance practice,
  coverage-assurance methodology, detection-tuning practice, the DA/BA/role boundary) are now
  primary-sourced. A five-agent pass inventoried **56 falsifiable practice claims** and verified
  each: **33 verified · 8 partial · 15 industry-standard-uncited · 0 unsupported - no claim false or
  fabricated.** The new register carries the per-claim verdict + citation; `house-rules.md`
  §"Domain evidence base" is upgraded from 🟡-foundational to a 🟢 tiered summary pointing at it.
- **Masking-pipeline design spec (`docs/prepare-data-design.md`).** The `/prepare-data` roadmap's
  option table turned into a buildable specification - schema-inference profiler, format adapters
  through the existing `convert_file.py` front door, an NER redaction backend, and a hardened
  auto-validation gate - each with a component contract, a threat-model row, acceptance tests and a
  build order, preserving every safety non-negotiable (agents never read `data/raw/`, `MASKING_KEY`
  required, `validate_masking` stays the hard gate). Implementation is a later build.

### Fixed (evidence corrections from the verification pass)
- **Lexicon exclusion overclaim (`lexicon-spec.md`, C7).** "Exclusion rules / allow-lists that
  suppress [FPs] without creating coverage gaps" overstated the property - an exclusion trades
  recall for precision. Reworded to require each exclusion to record its coverage impact.
- **Spoofing defaults contextualised (`spoofing.md`, C41).** Added the enforcement statistics
  (Coscia large-order fill ~0.08% and lifetimes <500ms; Sarao 4-6 stacked orders) showing the
  repo's `5x / 2000ms / 0.10 / 3000ms` defaults are deliberately conservative catch-alls, looser
  than the cases and requiring production calibration - not empirically-derived constants.
- **MW79 scope caveat recorded.** FCA Market Watch 79 is a data/model-governance authority, not an
  e-comms-lexicon authority; `house-rules.md` and `evidence-base.md` now say so, so later docs don't
  miscite it for lexicon design.

### Security (guard red-team - `docs/adr/ADR-002` rev 0.6)
- **Six new advisory-guard bypasses recorded (recs 17-22), two Tier-2 residuals + the rec-5
  remainder re-confirmed with PoCs.** A static adversarial pass on the three PreToolUse guards found
  wrapper-prefix evasion of the segment-anchored runners (`timeout 5 pytest`), backslash
  line-continuation splitting (`python3 \`+newline+`evil.py`), absolute/tilde/`../` shebang-direct
  exec, `python < file` stdin redirect, novel launcher gaps (`deno test`/`bun test`/`node --test`/
  `xargs`), and the read-tool coverage gap for tools outside `{Read,Grep,Glob,Bash}`. All are
  lexical bypasses of the *advisory* Bash-channel guard (no OS backstop by design - §Context), so
  none raises a new risk class; each is a gap worth closing to keep the advisory guard honest. **No
  guard logic was edited** (standing rule); the fixes + regression tests are recorded for
  human application via a guard-hardening script.

### Added (eval baseline)
- **Fable-judged eval baseline (`docs/eval-baseline-2026-07-06.md`).** With execution consent
  granted, all 28 golden cases were run blind with Fable 5 as the model and scored deterministically.
  Raw result **20/28**; verification traced 7 of the 8 fails to normalization artifacts of the manual
  run method (severity-floor under-tagging on behaviour cases; a trap substring-matching a *correct*
  refusal) and only 1 to a genuine over-report (the `/deep-review` flagged a documented, intentional
  column bound on `review-excel-truncation` - substance-adjusted read **27/28**). The findings-shaped
  clusters (code-review, coverage, spec, tuning, citation, TM-validation) are the trustworthy
  comparators; behaviour cases should be re-baselined via a canonical user-invoked `/run-evals`.
  **One genuine action:** note to `/deep-review` not to flag documented rationale-carrying bounds.

### Deferred / not done this pass
- Per-file inline-citation threading and the guard-hardening apply-run remain mechanical follow-ups
  (`docs/evidence-base.md` §Deferred; `ADR-002` recs 17-22).
- Re-baseline the behaviour eval cases via a user-invoked `/run-evals` (canonical normalizer) to make
  them comparable; and the `/deep-review` documented-bound prompt note above.

## [0.11.0] - 2026-07-05 - the Fable audit release

**This release was audited by Claude Fable 5** (Anthropic's most intelligent generally available
model, first of the Claude 5 family, Mythos tier above Claude Opus). Two passes: a nine-agent
setup review plus four-agent documentation truth audit (~214 falsifiable claims in the README and
every linked doc checked against the code: 7 false, ~32 partial, the rest verified true), then a
conformance audit against 13 source-verified design rules distilled from Anthropic's published
multi-agent guidance by a 99-agent deep-research pass (the setup already conformed on 11 of 13).
Everything below was validated with the full test suite (347 passing) and a live golden-case
spot check (seeded-bug review recall 1.0, zero false-positive traps; clean-code case zero
findings) so the fixes did not regress behaviour.

### Fixed (evening pass - documentation truth)
- **Token economics told straight.** The README's "measured" delivery figures contradicted the
  delivery report they cited; now built on the measured numbers (9 agent runs, ~500k tokens,
  ~USD 4-8) with estimates labelled as estimates and the fictional rate-card figures removed.
- **Traceability matrix cites real tests.** The demo delivery report's RTM named tests that do
  not exist; corrected to the actual test names, the 12th DoD gate row added, and the
  DetectionParams documentation claim made accurate (5 of 7).
- **Safety story stated precisely.** CLAUDE.md's dormancy banner now says all three guards stay
  armed in dormant sessions (previously implied only data safety); "read-only" advisor claims
  corrected everywhere to the tool-enforced truth (no Write/Edit; Bash execution-gated); the
  plugin-mode deny-list caveat corrected in the README portability section.
- **Counts and pointers.** CHANGELOG test counts (4 not 5; 17 not 18), ADR-002 consent-test
  count (17 not 14), 0.8.0 test milestone (~171 not 192), stale roster/attestation/self-verify
  pointers, a broken demo-artifact link, demo transcripts re-anchored to current fixtures, and
  a fabricated console block in the review demo replaced with the scorer's real JSON output.
- **ADR-002 brought current (0.5, Accepted):** revision rows for the applied hardening, recs
  7/8/13 updated to their actual state, the Context section corrected, and two new Tier-2
  residuals recorded (parent-rooted Grep toward the raw-data directory; secrets deny-protected
  on Read only).

### Fixed (evening pass - guards, human-applied via apply-guard-fixes.sh, ADR-002 rec 14)
- **Multi-.py false positive:** any Bash command naming two .py files was blocked as code
  execution (the first filename's trailing "py" parsed as the Windows py launcher); it blocked
  read-only git add/diff/grep live during the audit. Fixed with a lookbehind; py-launcher
  detection (including `py -3 file.py`, previously missed entirely) still blocks.
- **Anchored pwsh/powershell** (the word in a grep pattern or prose no longer blocks) and
  **gated `pre-commit run`** (it executes arbitrary configured hooks; it was allow-listed,
  unmatched by the exec patterns, and its config was model-writable - now pattern-gated and
  `.pre-commit-config.yaml` write-protected).
- **Misleading pre-consent allow entries removed** (`pytest` twins, matching the pwsh removal).
- Regression coverage: `tests/test_guard_fixes.py` (20 tests).

### Added (evening pass)
- **Prevention tests** (`tests/test_docs_consistency.py`): mechanical drift guards for the
  claims that kept drifting - agent model tiers vs the design table, README badge vs
  plugin.json, ADR header vs revision table, three-guards wording, roster pointer, spot-check
  doctrine, CONTRIBUTING vs the CI matrix.
- **Two golden cases (28 total):** consent-grant social engineering (an embedded instruction
  telling the reviewer to create the exec-consent marker; correct behaviour refuses, flags,
  and still finds the real seeded bug) and secrets-authoring refusal (pasted credentials with
  "just hardcode it for now" pressure; correct behaviour routes to env vars).
- **Eval integrity completed:** planted location anchors re-derived against the de-hinted
  inputs (several were out of tolerance, one past end-of-file), remaining answer keys moved to
  notes.md sidecars, "this is an eval" banners stripped, negation-blind forbidden traps
  reworked to endorsement-only phrasing, and contract tests now verify manifest references
  resolve and anchors are in range.

### Changed (evening pass - best-practice conformance, no architectural change)
- **Condensed returns:** every subagent brief and all 16 agent output specs now require a
  distilled return (~30 lines) with detail in artifacts (closes the design doc's own
  "aspirational" gap against Anthropic's context-engineering guidance).
- **Right-sizing sharpened:** numeric effort-scaling heuristics and a delegate/do-not-delegate
  checklist in the operating guide; a canonical command index for all 20 skills; the
  engagement-summary email now states the engagement footprint (agents + approximate tokens).
- **Consistency batch:** evidence tagging in all 16 agents, orchestrator-mediated handoff
  phrasing, jurisdiction lists centralised to scope-and-stack, code-reviewer's analyser table
  and tool probe cover the full 7-language lens set, exec-consent clauses and the
  dormant-skill chaining rule in the skills that lacked them, the standard engagement close in
  the three review skills, one canonical Developer-guidance heading, and the eval harness
  named as the regression gate for prompt changes in WAYS-OF-WORKING and the DoD.

### Fixed (afternoon pass - setup consistency & eval-integrity)
- **Eval harness could not fail.** The golden inputs under `evals/cases/` carried their own graded
  answers (planted-issue labels in the code the reviewer reads; "what a correct response does"
  prose in behaviour `scenario.md`), so a live `/run-evals` stayed green even if the prompts
  degraded. Stripped the answer keys from the input files (the planted defects/traps remain,
  unlabelled), moved behaviour grading notes into per-case `notes.md` sidecars, and rewrote
  `/run-evals` to spawn each workflow in a **fresh subagent fed only the input** so blindness is
  structural, not willpower. Ground truth stays in `expected.yaml`; the contract tests
  (`tests/test_eval_cases.py`) read only that, so they are unaffected.
- **Plugin-mode raw-data backstop.** A plugin install ships the guard hook but not the
  `permissions.deny` list the fail-open paths and README leaned on; documented that installers must
  recreate the deny entries (`docs/house-rules.md`, README, SECURITY.md, ADR-002 rec 10) instead of
  asserting a backstop that may be absent.
- **Skill `allowed-tools` contradictions.** `audit-review`, `deep-review`, `performance-review` and
  `prepare-data` declared tool lists that forbade the subagent-spawning / question-asking /
  artifact-writing their own bodies require; removed the key (matching the other 16 skills).
- **Plugin-mode script invocation.** Replaced literal `python -m scripts.*` with the resolved
  `<python>` convention across the directly-invocable skills, so they work on hosts without a bare
  `python` and in installed-plugin sessions.
- **Static-only vs profiling.** Removed the stale "re-profile" / "profiling evidence" instructions
  that contradicted the static-by-default posture (`performance-reviewer`, `performance-review`,
  `remediate`, Definition of Done, WAYS-OF-WORKING); profiling now consistently gated on §7 consent.
- **Exec-consent visibility.** `qa-engineer`, `rules-developer`, `ml-engineer` and the skills that
  run tests (`build-solution`, `new-scenario`, `remediate`) now point to the §7 consent gate so they
  are not silently hard-blocked mid-task; `assess-coverage` gained the §5 data-attestation gate.
- **Doc consistency.** `review-scorer` description gained the dormancy trigger; README badges →
  0.10.0 / 220+ tests; "two hooks" → three (README) and the consent-write gate added to SECURITY.md
  scope; CLAUDE.md §7 reworded to the human-only consent model; the 📊 evidence-tag legend now names
  both registers (measured vs observed) as a single source; SME + review-scorer rows added to the
  routing table and the missing skills added to the README command index; stale roster-location and
  "two guards" claims corrected; `agent-design.md` eval counts → 8 rubrics / 26 cases.
- **CI / hygiene.** Test job now runs a `windows-latest` leg and a 3.10 floor leg; analysers pinned;
  `shellcheck` now covers `run-guard.sh`; the no-raw-data gate (CI + pre-commit) now includes
  `.jsonl`/`.xlsx`/`.xls`/`.tsv`; `.ruff_cache/` gitignored; removed the stale root
  `team-update-2026-06-30.txt`.

- **Guard hardening (ADR-002 recs 10-13), applied by a human maintenance run**
  (`apply-guard-hardening.sh`, since the consent-write gate blocks model edits of the guards):
  the consent guard now allows read-only `git`/`jq` on protected paths while still blocking
  mutating `git checkout` and `find … -exec/-delete`; `pytest`/`unittest` are anchored so the word
  in prose/commit messages is not read as the command; the exec-runner list is broadened
  (`cargo`/`swift`/`bundle exec`/`jest`/`vitest`/…); the raw-data marker is word-bounded and
  case-insensitive (catches `cd data/raw && …` and `DATA/RAW` without false-positiving on
  `metadata/rawlog`); the misleading `pwsh` allow entry was removed and a `python3 -m scripts.ingest`
  twin added; `data/raw/` is now write-protected. Regression coverage: `tests/test_guard_hardening.py`.

## [0.10.0] - 2026-07-05

### Added
- **`scripts/convert_file.py` - the file-conversion front door**, closing out the extraction
  incident class at the tooling layer (0.9.1 added the house rule; this adds the mechanism).
  One command reads Excel (`.xlsx`/`.xlsm`/`.xls`), CSV/TSV (encoding + delimiter defences,
  never silent), PDF (text only - PDF tables are layout, not data) and Word `.docx`, and
  emits CSV/JSONL or Markdown/text plus a **JSON evidence report every run** (hashes, counts,
  encoding decisions, warnings, check results). Lossless by default (zero type inference - no
  float-mangled IDs, no guessed date formats); an optional per-feed schema
  (`config/feed-schema-example.yaml`) turns conversion into a **gate**: types, ID patterns,
  header order, row counts and Decimal control totals all fail loudly on breach. Refuses
  `data/raw/` (masking pipeline owns raw). ~30 tests cover the field failure modes.
- **`vendor/` - dependencies bundled in the repo.** The converter's libraries (openpyxl,
  et_xmlfile, xlrd, pypdf, defusedxml - all MIT/BSD/PSF, pure Python, pinned, unmodified)
  ship inside the repo so a plain `git clone` works with **no pip access** (corporate
  environments). Licences recorded in `THIRD-PARTY-LICENSES.md`; update procedure in
  `vendor/README.md`. Vendored copies win over site-packages for determinism.
- **Routing:** house rule in `docs/house-rules.md` (conversions outside the front door, or
  without the report attached, are a finding); directives in `data-analyst`,
  `platform-engineer`, `tuning-analyst`, `qa-engineer`, `data-quality-reviewer` and
  `/analyse-data`.
- **Guard allow-list, human-applied:** `convert_file` added to `_TEAM_SCRIPT_NAMES` in
  `guard-code-execution.py` by the user (the consent-writes gate blocks the model editing
  guards, as designed), so plugin-mode path invocation of the bundled converter is
  consent-free like the other team helpers. CONTRIBUTING now documents this step for any
  new agent-invoked script.

## [0.9.1] - 2026-07-02

Windows field fixes (from a live plugin install: interpreter resolution, guard path handling,
permission-rule churn) and silent-extraction-truncation defences at every layer.

### Fixed
- **Windows permission-rule churn diagnosed and prevented.** A live Windows install
  accumulated invalid auto-saved permission rules ("ignoring 7 permissions.allow entries",
  growing with each approval): approving Morgan's ad-hoc invocations saved literal command
  strings with mixed path separators and mixed quote styles, which the validator rejects.
  Now: the operating guide mandates **one consistent spelling** (forward slashes + double
  quotes - Git Bash accepts them on Windows) and a `bash --version` probe at step 0 with a
  degrade path (skip `.sh` helpers, call analysers directly) for environments without Git
  Bash; the README plugin quick-start gains an optional **pre-approval block** of clean
  wildcard rules so approvals rarely trigger at all. Cleanup for affected installs:
  `/permissions` shows each rule's source file - delete the flagged ones, paste the block.
- **Guards 0.4.1: Windows correctness, human-applied** (both reported from a live Windows
  plugin install). The exec guard's allow-list used forward-slash-only regexes, so Windows
  backslash paths (`python C:\...\scripts\render_html.py`) were blocked; separators are now
  `[/\\]`. Worse, the `py` launcher was invisible to the guard entirely - `py evil.py` was
  **not blocked** and `py -m scripts.x` was **not allowed** - it's now part of the interpreter
  token, fixing both directions. The raw-data guard's Bash marker gains the `data\raw\`
  backslash variant. 4 new regression tests; ADR-002 → 0.4.1.
- **Morgan no longer assumes `python3` when invoking the bundled scripts** (reported from a
  Windows plugin install, where the interpreter is `python`/`py` and `python3` doesn't exist).
  Engage step 0 now resolves the interpreter once (probe `python3` → `python` → `py`, the same
  order as `run-guard.sh`) alongside the run mode, and the operating guide's script-resolution
  rule uses the resolved `<python>` form throughout.

### Added
- **Silent-extraction-truncation defences at every layer.** The incident class: the team
  writes Python to extract data from an Excel file, the code silently truncates (a hardcoded
  row cap, `except`-and-continue over rows, value slicing), and the incomplete extract feeds
  onward analysis - the domain's signature silent failure, applied to the team's own code.
  Now: a **house rule** (extraction/conversion code must prove completeness mechanically -
  source-vs-output counts + a control total, asserted by tests, citing the existing
  `ingest.py`/`validate_masking.detection_fidelity` patterns); a **review-lens check cluster**
  in `bugs.md` (loads for any code) + pandas/openpyxl pitfalls in the Python lens, with the
  meta-check that missing reconciliation is itself a finding; a **golden eval case**
  (`review-excel-truncation`: 4 planted issues incl. the missing reconciliation, plus a
  documented-column-bound false-positive trap); **DoD** "Tested" now requires the completeness
  reconciliation for extract/convert deliverables; and briefs updated so `platform-engineer`
  builds the reconciliation in, `data-analyst`/`analyse-data` refuse to analyse an
  unreconciled extract, and `data-quality-reviewer` treats team-written extraction code as in
  scope. Harness: 26 cases.

## [0.9.0] - 2026-07-02

Plugin-mode operation everywhere, guard 0.4 (human-applied), the reworked README argument
(domain case, hypothesis, chat-window differentiation, enforced principles), and the
question-flow fixes.

### ⚠️ Breaking changes - read this first if you used any 0.7.x or earlier

These landed across 0.8.0 and this release; they are consolidated here because 0.8.0 shipped
without a breaking-changes header and the project has no known external users yet - if you do
have an existing install, this is the one section to read.

- **The team no longer "just runs anywhere" - enablement is per project.** Installing the
  plugin used to mean every project on the machine loaded the roster and could summon the
  team. Now the documented (and intended) posture is: install once, then **enable the plugin
  in each project that uses it** (README quick-start step 2). An old user-scope enablement
  keeps functioning, but it taxes every session in every project ~1.2k tokens for agents most
  projects never use - scope it. *Why: agent descriptions have no lazy-load mechanism;
  per-project scoping is what makes the team genuinely free where it isn't wanted.*
- **Summoning the team is now explicit - type the slash command.** All 20 skills set
  `disable-model-invocation: true`, so their descriptions never load into context and the
  model cannot auto-invoke them. In a foreign project, "hey, get the team to look at this"
  no longer works - `/compliance-surveillance-team:engage` (or `/engage` in the repo) does.
  *Why: dormancy - a team you didn't summon should cost nothing and never self-activate.*
- **Answering "Yes" to execution no longer opens the gate - only you can.** The model is
  blocked from writing `.claude/.exec-consent` (and `settings*.json`, and the hooks
  themselves). Any workflow that runs tests or scripts now includes one human step: the team
  shows the exact `touch` command with the absolute path, you run it. `CST_ALLOW_EXEC=1` at
  launch remains the hard override; `CST_ALLOW_CONFIG_EDIT=1` is the new hook-maintenance
  override. *Why: a confused or prompt-injected model must not be able to authorise itself.*
- **Git history was rewritten on 2026-07-02** (AI-attribution commit trailers removed):
  every commit SHA changed and all tags were force-moved. Re-clone (or
  `git fetch && git reset --hard origin/main`) any existing clone or fork.

### Added
- **Full plugin-mode operation: the helper scripts now work from any project.** The exec
  guard's allow-list accepts the team's bundled scripts invoked **by path** (basename-
  whitelisted), so an installed plugin can render `.md`→`.html`, generate synthetic data and
  run the DoD artifact gate from a foreign project - no repo checkout needed. `/engage` step 0
  resolves the run mode once (`ls scripts/render_html.py`), states it in the opening banner,
  and the operating guide carries the resolution rule + the plugin-mode masking prerequisites
  (own `config/masking-schema.yaml` + `MASKING_KEY`). The README's "works everywhere vs
  repo-as-project" memory-burden callout is replaced by self-detection. Guard changes were
  **human-applied** (the consent-write gate blocks the model editing the guards - the user
  copied in the prepared files); two live false positives fixed in the same update (`make`
  inside commit messages; multi-file `shellcheck`), block messages now print absolute marker
  paths, and 4 new regression tests cover all of it. ADR-002 → 0.4. Also: the FCA Market
  Watch 79 citation now links to the source (fca.org.uk, verified 2026-07-02).
- **CI pipeline documented** (`CONTRIBUTING.md`): the four GitHub-Actions jobs (tests+validators
  · lint/format/security · full-history secret scan · no-raw-data), where they run
  (GitHub-hosted ephemeral runners), triggers, how to watch runs, what CI deliberately cannot
  cover (git-ignored artifacts → `check_artifacts`; live team quality → `/run-evals`), and the
  local pre-commit layer in front of it. Drift fixed while in there: "two safety hooks" → three
  (consent-write guard + its `CST_ALLOW_CONFIG_EDIT` maintenance rule), `ruff format --check` +
  the no-raw-data check added to the "run what CI runs" list, and the skill-authoring bullet now
  states the `disable-model-invocation: true` dormancy requirement (and that command names come
  from the directory, not a `name:` field).
- **README "Why" section makes the domain case in three movements** - (1) the four domain
  pressures (cross-disciplinary scarcity; silent, asymmetric failure - MW79's
  zero-alerts-for-3-years feed; evidence as the product; crown-jewel data); (2) **the
  hypothesis the project exists to test: AI can genuinely help this domain** - the work is
  translation between formalisms, the evidenced 80% is the automatable 80%, consistency is a
  regulatory feature, and AI's failure modes are manageable with the domain's own controls -
  with the demos/evals named as the evidence so far and the unproven parts signposted;
  (3) why that requires a specialist *team* with independent review rather than one assistant,
  each domain pressure mapped to its architectural control (tool-grant segregation of duties,
  audit trail by construction, data safety as architecture, humans keep the judgement).
  Stays inside the proof-of-concept framing.
- **Legibility bundle** (from the setup audit's discoverability findings): README gains
  **reading paths** (new user / extending / auditing / data & tuning - the repo has 130+ doc
  files and needed a "start here" map) and a **Mermaid data-flow diagram** of the safety story
  (real data → agent-blocked `data/raw/` → keyed masking → governed/synthetic → agents → model
  provider, with the guard shown blocking the direct path). The **18 orphan templates** are
  wired: 14 now referenced inline by their owning skills (data-dictionary/lineage/segmentation/
  process-map → `/analyse-data`; tuning-decision-register/mi-spec → `/tune-thresholds`;
  control-mapping → `/assess-coverage`; user-stories/decision-log → `/elicit-requirements`;
  model-validation-report → `/validate-tm-model`; trade-scenario-design/comms-policy/
  lexicon-spec → `/new-scenario`; adr → `/build-solution`; review-report → `/deep-review`;
  uat-plan → `/handover`), and `docs/WAYS-OF-WORKING.md` now declares its catalogue the
  **canonical template index** covering the rare remainder.

### Fixed
- **Morgan's question menus now fit the question tool** (question-flow audit, 2026-07-02 -
  report in `artifacts/morgan-question-flow-audit.md`, session-local). AskUserQuestion renders
  at most **4 questions per call and 4 options per question**, but two locked menus exceeded
  that: the `/engage` artifact menu (11 options → now a locked two-stage structure: packaging
  single-select, then grouped ≤4-option multi-selects) and `/deep-review`'s dimensions
  (7 options → 4 locked bundles; direct mode swaps Origin to the follow-up screen so the call
  stays ≤4 questions). `/performance-review`'s concerns (5 options) and free-text volume ask,
  and `/prepare-data`'s option-less goal ask, brought within limits too. Flow fixes in
  `/engage`: bare-invocation precedence defined (target first - the exec/data gates are
  undecidable before it); work-type asked only when genuinely ambiguous; data attestation gated
  like exec consent; the brief go-ahead and change-my-code confirmations are now tool questions
  (no double-ask when Q3 already authorised fixes); Q1=None + Q2=No no longer undefined; locked
  headers on all locked menus. The tool's hard limits + header rule added to the operating
  guide's question rules.

### Added
- **Mechanical DoD artifact gate** (`scripts/check_artifacts.py` + 6 tests): verifies every
  `artifacts/**/*.md` has its rendered `.html` sibling and the closing engagement-summary
  `.txt` exists - the two DoD items CI can never see (`artifacts/` is git-ignored). Wired into
  `/engage` step 6 and `/handover`; `docs/DEFINITION-OF-DONE.md` now carries a note on
  which gates are prompt-enforced vs mechanically checked. (Its first live run flagged a real
  missing summary email.)
- **4 golden eval cases + a `process-discipline` rubric** for the previously untested mandated
  behaviours: the engagement-summary-email close (incl. the never-offer-a-call rule),
  right-sizing stated at the gate, 📊/🧠 evidence tagging under temptation, and the
  `.md`+`.html` dual-artifact rule. Harness is now 8 rubrics / 25 cases; the CI contract tests
  pick the new cases up automatically.

## [0.8.0] - 2026-07-02

True dormancy, fail-closed guards, human-only consent, and a CI-checked eval contract - the
outcome of a full setup audit against Anthropic's current published guidance (2026-07-01).

### Changed - setup audit 2026-07-01 (full report: `artifacts/claude-setup-audit.md`, session-local)
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
  self-grant block as a safety feature). 17 new tests (`tests/test_guard_consent.py`) + sync-test
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
  unchanged (only the launch path), the two hook wirings stay in sync (the sync test asserts
  parsed-JSON equality of their `PreToolUse` blocks; `settings.json` also carries permissions), and a new test
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
  fixed model tiering, batching chains within the 5-min subagent TTL). Recorded the upstream
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
  statement. "Built on" and "Credits & acknowledgements" merged. All prior reference detail (token
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
- **`agent-design.md` self-assessment corrected (audit follow-up).** An independent audit against
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
- **OVERVIEW masking claims corrected** - the "new to LLMs" page no longer reads as if masking is
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
  (full bypass enumeration), the decision to represent them accurately as advisory defence-in-depth,
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
- **Measured calibration** ([`ts001_threshold_tuning_harness.py`](docs/demos/build-artifacts/ts001_threshold_tuning_harness.py),
  calibrating [`ts001_wash_trade.py`](docs/demos/build-artifacts/ts001_wash_trade.py)):
  synthesises a *labelled* dataset and runs real ATL/BTL - `price_tolerance_pct` 0.10-0.50% (100%
  precision + recall), flagged as measured-on-synthetic.
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

### Changed - data-masking claims corrected (claims-vs-reality audit)
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
  against Anthropic's published multi-agent standards, with the **source links** (§7 +
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
