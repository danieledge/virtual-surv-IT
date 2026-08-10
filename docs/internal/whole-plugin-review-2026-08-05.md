# Whole-plugin review (report-only) — 2026-08-05

Independent review pass across the entire plugin (excluding `install_helper.py`, which just
had its own dedicated fix pass in 0.33.19). Report only — no code changes made. Scope: agents,
commands, skills, hook wiring, `scripts/`, docs consistency, manifest, README.

18 clear wins, 7 debatable items, plus a calibration note on what already works well.

## Clear wins

### Safety-hook wiring (not core guard logic)

1. **`guard-raw-data`'s WebFetch/NotebookRead/unknown-tool coverage is dead code under the live
   wiring.** The 2026-08-01 audit fix (`guard-raw-data.py:333-395`) added handling for these,
   but the dispatcher matcher (`hooks/hooks.json:14`, mirrored in `.claude/settings.json`) is
   `Read|Grep|Glob|Write|Edit|MultiEdit|NotebookEdit|Bash`, and
   `scripts/bash_hook_dispatcher.py:62` further restricts `guard_raw_data` to
   `{Read, Grep, Glob, Bash}`. A `WebFetch(file:///…/data/raw/x.csv)` never reaches the guard.
   Fix is wiring-only: widen the matcher and the `_CHECKS` tool set.

2. **`README.md:1208-1223`** says two guard fixes are "staged, not yet live" — they shipped in
   0.33.6, 13 releases ago. Understates the shipped protection to security-conscious readers.

3. **"Three guards" is wrong in 11+ places** — `guard-findings-pack-write.py` is a fourth
   fail-closed guard (`scripts/bash_hook_dispatcher.py:70-75`). Stale count in `README.md:302,
   725, 731, 957`, `docs/safety-model.md:9`, `docs/DEFINITION-OF-DONE.md:108`, `CLAUDE.md:15`,
   `SECURITY.md:18`, `CONTRIBUTING.md:91,148`, `docs/adr/README.md:9`,
   `docs/agent-design.md:57-58` (contradicts its own lines 40/126). Worst:
   `tests/test_docs_consistency.py:110-115` **asserts** "three … guards" — the drift-prevention
   test locks in the stale count.

4. **`scripts/apply-hooks.sh:18-20` regresses the hook architecture if run.** Still invokes
   `apply-document-redirect.sh` / `apply-module-redirect.sh`, re-fragmenting the dispatcher and
   double-running both redirects; also omits `apply-bash-hook-dispatcher.sh`,
   `apply-stop-hook-dispatcher.sh`, `apply-guard-findings-pack-write.sh` while claiming to apply
   every staged wiring. `test_hooks_in_sync.py` can't catch it (compares settings.json to
   hooks.json, which take the same damage).

5. **`scripts/dashboard.py` misreports a fully-wired repo as 5/9 wired** —
   `_ROUTINE_HOOK_SCRIPTS` (92-102) still lists four basenames now folded into the dispatchers.
   Also lines 76-84: two `except ImportError` fallbacks are byte-identical to their `try`
   bodies (copy-paste dropped `sys.path.insert`).

### Agent/skill runtime correctness

6. **`code-reviewer` is instructed to write a file its own guard hard-blocks.**
   `code-reviewer.md:143-144` (step 4) says write full findings to `artifacts/REVIEW-<slug>.md`;
   `guard-findings-pack-write.py:47-56` blocks any Write outside
   `artifacts/[<slug>/]data/findings-*.json`, and lines 172-175 of the same file say so. Path is
   also wrong per ADR-010 (canonical: `artifacts/<slug>/REVIEW-<slug>.md`).

7. **`code-reviewer` and `performance-reviewer` write the *same* pack filename** — both
   `artifacts/<slug>/data/findings-<slug>.json` (`code-reviewer.md:168-169`,
   `performance-reviewer.md:92-93`). Both run in one engagement; second write clobbers first.
   `compliance-reviewer.md`/`model-validator.md` already use prefixes to avoid this;
   `performance-reviewer` needs `findings-performance-<slug>.json`.

8. **Stale "hold no Write" in docs the reviewers are told to read.**
   `docs/code-review-method.md:145` and `docs/review/findings-schema.json:5` still say the four
   reviewers hold no Write and the PM writes the pack — superseded by the 0.33.8 Write grant.
   Direct contradiction of the agents' own system prompts.

9. **Pack-schema mismatches that fail validation on first pass.** (a)
   `compliance-reviewer.md:83-84` / `model-validator.md:55` say tag findings "📊 observed" — the
   schema's `basis` enum is `measured|coded|inferred`. (b) None of the four pack-emitting agents
   mention the required top-level `scope`/`mode` fields — likely first-pass `validate_findings`
   failure.

10. **The shared close bookend omits `set-status closing` — 17 skills will trip the gate they're
    told to run.** `.claude/skills/.shared/engagement-bookends.md:44-57` has no `closing` step
    and puts the summary email before it, while `scripts/check_artifacts.py:1400-1417` raises
    `SUMMARY-BEFORE-CLOSE` whenever the email exists while status is still open. Every other
    close description mandates `closing` first. `handover/SKILL.md` writes the closing email
    and runs the gate but never closes the engagement at all — it can never reach ✅.

11. **Eleven skills contradict ADR-010's "one placement rule"** by saying bare `artifacts/`
    where the gate flags root files as `ORPHAN-ARTIFACT` — `analyse-data:41`,
    `assess-coverage:51`, `build-solution:74`, `elicit-requirements:35`, `handover:48,53`,
    `remediate:60`, `tune-thresholds:53`, `validate-tm-model:50`, `engage:248`, `demo:79`,
    `new-scenario/SKILL.md:56`.

12. **`run-evals/SKILL.md:5` `allowed-tools` forbids the tools its own body requires** (Read,
    Task×3, Write, artifact render) — a repeat of the bug already fixed once for four other
    skills. Pre-approves `scripts.eval_engage`, which the body never mentions; covers
    `python`/`python3` but not the `py` launcher the run-mode doc says Windows uses.

13. **`validate_findings.py` is missing from the consent-free allow-list** while being handed to
    the model as a command — `README.md:914` labels it "model, consent-free" but it's absent
    from `_TEAM_SCRIPT_NAMES` (`guard-code-execution.py:131-136`) and CLAUDE.md §7, so a
    plugin-mode invocation trips the consent gate on the team's own tooling — same incident
    class as the 2026-08-01 `engage_probe` note. One-line staged-guard addition + human apply.

14. **Two allow-listed scripts cannot run in the mode they're allow-listed for.**
    `render_docx.py:31` imports `scripts.render_html` with no path fallback (compare
    `render_findings.py:30-33`); `calibrate_spoofing.py:22-23` has no path setup for its
    imports, so even `python scripts/calibrate_spoofing.py` from repo root fails.

15. **Windows-crash encoding gap:** ~6 scripts pin stdout to UTF-8 but read/write files with the
    locale codec — `check_citations.py:179`, `ingest.py:294`, `validate_masking.py:296`,
    `eval_score.py:78,285`, `validate_manifest.py:32,100`, `gen_synthetic.py:183`.

16. **Small verified bugs:** `extensions.py:304-305` — documented `extensions show --file PATH`
    doesn't parse; `extensions.py:171,177` — registry JSON used as `re.sub` replacement template
    corrupts backslashes; `render_findings.py:179` — flag values aren't filtered, `--out
    REVIEW.md pack.json` treats `REVIEW.md` as the pack; `subagent_return_budget.py:121` — only
    hook missing `CLAUDE_PROJECT_DIR` anchoring; `persona_anchor.py:39` — points at nonexistent
    a nonexistent "apply-persona-anchor.sh" (real file is `apply-project-anchor.sh`); `audit-review/SKILL.md:63`
    — says compliance-reviewer holds "no Write/Edit" (it holds scoped Write); `CLAUDE.md:89-91`
    + `agent-design.md:16,126` — "six hold Bash" is arithmetically five for the enumerated set.

17. **README internal contradictions on the Write grant:** lines 189, 480, 514, 630, 977 (+
    `docs/FAQ.md:37`) say advisors hold no Write/Edit; line 956 states the correct scoped-Write
    reality. Also stale: rubric count "9" (10 exist) at lines 197,637,708,710,892,1061;
    `docs/releases/0.33.md` stops at 0.33.7 while linked as the overview for 0.33.19; ADR index
    "001 to 011" at line 1178 (ADR-012 exists); operating-guide line counts at lines 1232,1255
    (490 vs actual 593).

18. **`/engage`'s review menu offers a "Quick" depth that routes nowhere.**
    `engage/SKILL.md:149-155` + `review-menu.md:23-30` offer Quick·Deep·Audit·None; nothing maps
    Quick to a workflow. The locked-menu guard enforces the menu's shape, so the model *will*
    present an option it has no instruction for.

## Debatable / needs a call

1. **`_TEAM_ALLOW`'s broad branches undercut the basename discipline**
   (`guard-code-execution.py:173-186`): `python -m scripts.<anything>`, `python
   scripts/<anything>`, `bash scripts/<anything>` are consent-free with no basename constraint.
   In plugin mode in a foreign project, the host project's own `scripts/` dir could run
   consent-free; `python scripts/../../x.py` traverses out. Within ADR-002's acknowledged
   lexical residual, but contradicts the documented basename-list intent.

2. **`guard-findings-pack-write.py` depends on an `agent_type` field** in the PreToolUse
   payload (line 79) that I could not confirm is actually delivered for subagent tool calls
   (tests inject it synthetically). If it's absent in practice, the scoping guard fails open.
   Worth one live verification against a captured payload. **Resolved 2026-08-10, live-verified
   both dispatch paths:** a real `code-reviewer` subagent attempting an out-of-scope `Write`,
   dispatched once via `Task` and once via `Workflow`'s `agent(prompt, {agentType:
   "code-reviewer"})`, was blocked identically both times (`Blocked (findings-pack write scope,
   agent=code-reviewer): ...`) - `agent_type` is delivered correctly for both, the guard does
   not fail open on this dimension for either dispatch mechanism.

3. **Live false positive observed during this review:** guard-consent-writes blocked a
   read-only Python heredoc that merely *mentioned* a protected filename
   (`.claude/settings.json`) in a string literal — heredoc bodies are judged as shell segments.
   Fifth instance of the prose/argument FP class the guards already track.

4. **`scripts/staged_hooks/`** — 17 files, all byte-identical to live, ~130 KB. Only the four
   guards + launcher need staging (model can't edit `.claude/hooks/**`); the eleven `scripts/*.py`
   copies aren't guard-protected and don't need it. Side effect: `validate_references.py:57`
   searches `staged_hooks`, so the link checker would miss deletion of a live hook.

5. **Verbosity/token cost — ~11% duplication in both prompt corpora.** Agents: ~120 redundant
   lines (three SME files ~30% identical; `code-reviewer.md` carries an 80-line tool-availability
   essay duplicating `check-review-tools.sh`). Skills: ~215/1,954 lines duplicated across the
   four review skills despite `.shared/` existing. Scripts: ~450 lines duplicated across five
   clusters (21 copies of UTF-8 forcing, 5 of dormancy detection, 4 of `_load_checker` — which
   carries a `sys.path` leak and a dead-path memo cache). Real token/maintenance win, but
   consolidation risks regressing tuned prompt text.

6. **Deletion candidates:** `scripts/diagnose-engage-startup.sh` (referenced by nothing; claims
   read-only but `rm -f`s the tool cache; stale "5 hooks on Bash" conclusion);
   `scripts/apply-outstanding.sh`, `apply-document-redirect.sh`, `apply-module-redirect.sh`
   (spent migrations, the latter two now actively harmful per win #4).

7. **`performance-reviewer.md:85-89`** tells the agent to hand candidates to `review-scorer` —
   subagents can't invoke each other (its own lines 14-16). `code-reviewer.md:138-141` has the
   correct formulation to copy.

## What already works well

Frontmatter discipline is excellent — all 24 skills carry `disable-model-invocation: true`
(dormancy invariant holds), all 16 agents' `model:` tiers and tool grants match
`agent-design.md`/`CLAUDE.md` §8 exactly, roster names are consistent across all 16 files. Zero
broken file references across agents and skills. Version 0.33.19 is consistent across
plugin.json, README badge, and CHANGELOG. Guard code itself is high quality: quote-aware
segmentation, each historical FP documented at its fix site, fail-open/fail-closed policies
preserved through both dispatcher consolidations, staged/live copies byte-identical with sync
tests enforcing it. No tracked cruft in git.

The dominant defect pattern is not bad code but **doc/wiring lag behind fast-moving code**: the
0.33.8 Write-grant change and the two dispatcher consolidations each left a ring of stale
claims, counts, and apply-scripts behind them. A post-release "sweep the blast radius" checklist
would prevent most of this class.
