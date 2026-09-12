# Team-quality eval harness

The repo's unit tests check the **code** (masking, the spoofing rule, rendering, the guards).
This harness
checks the **quality of what the team produces** - reviews, coverage assessments, specs, tuning
packs - so a prompt change that silently degrades rigour gets **caught**, not shipped.

> Why it exists: the team is mostly *prompts*, and prompts get edited often. Without an eval,
> there's no signal that `/deep-review` still catches the bugs it caught 30 commits ago. This is
> the regression net (an Anthropic multi-agent standard - see `docs/agent-design.md`).

## How it works (two layers)

1. **Deterministic** (`scripts/eval_score.py`, unit-tested, no tokens) - matches the team's
   normalized **findings** against a golden **ground-truth manifest** (`expected.yaml`): recall on
   planted issues, must-find criticals, and false-positive traps. This is the backbone. What runs
   in CI token-free is the harness **contract**, not the team: the scorer's unit tests
   (`tests/test_eval_score.py`) plus per-case contract tests (`tests/test_eval_cases.py`) that
   check every manifest parses, a synthetic perfect run passes and an empty run fails per case.
   Scoring the *live team's* output still requires running `/run-evals` (spends tokens).
2. **Qualitative** (the `/run-evals` skill + an LLM judge) - scores the dimensions the
   deterministic layer can't: clarity, traceability, evidence-basis, usability. 0-1 + pass/fail
   per the rubric.

```
evals/
  rubrics/        what "good" looks like per deliverable (judge scores against these)
  cases/<case>/   a golden case: input file (synthetic) + expected.yaml (ground truth)
                  + notes.md (grading notes - optional but preferred)
  results.jsonl   tracked, append-only numeric record of every scored run (below)
  eval-baseline-<version>.md   the per-release record, carrying the verdict block (below)
```

**What the judge actually sees** (fixed 2026-08-01 after an audit found it did not):
the artifact listing handed to the normalizer and judge carries the **bodies** of the
`.md`/`.txt` deliverables, not just their paths (6k chars per file, 60k total, truncation
stated in-band), and the transcript retains **subagent output** tagged `[subagent]` and
capped at 3k chars per block (`--exclude-subagent-output` restores the old PM-only view).
Before that, "evidence basis", "traceability" and "clarity" were scored from filenames plus
the PM's own narration of the work - a well-narrated empty deliverable scored like a real
one.

All eval inputs are **synthetic** (CLAUDE.md §5) - seeded with known issues on purpose.

## What lives where in a case

- **The `input:` file** (named by the manifest's `input:` key, e.g. `scenario.md` or a code
  file) is the ONLY thing the team-under-test sees. `/run-evals` briefs the blind subagent
  with it alone, so it must read as a real request/artifact: no answer keys, no seeded-issue
  lists, no "this is an eval" banners, nothing that states or instructs the graded behaviour.
- **`expected.yaml`** is the ground-truth manifest the deterministic scorer reads.
- **`notes.md`** is the grading sidecar: seeded-issue detail, what a correct response
  does / must not do, trap-keyword rationale (and a change log when traps are reworked).
  It is never shown to the team-under-test - `/run-evals` excludes it from the blind brief.

## Running it

`/run-evals` (the skill) drives it: for each case it runs the named workflow, normalizes the
output to findings JSON, scores it deterministically (`python -m scripts.eval_score`), adds the
LLM-judge dimensions, and prints an aggregate scoreboard (cases passed, recall, traps triggered).
**Running the full set spends tokens** (each case spawns the team) - run it at milestones / before
a release, not every commit. The deterministic scorer's own tests and the per-case contract tests
(`tests/test_eval_cases.py`) run free in CI.

## The orchestration slice - `scripts.eval_engage` (live /engage runs)

`/run-evals` covers the *subagent* surface only: it cannot exercise Morgan's orchestration
(banner, intake gates, right-sizing, lifecycle discipline, close artifacts) because a subagent
has no user channel and cannot run slash commands - the gap the 0.27.0 baseline recorded. The
driver closes it:

    . .venv/bin/activate          # dev venv with claude-agent-sdk (requirements-dev.txt)
    python -m scripts.eval_engage --list
    python -m scripts.eval_engage --case process-full-lifecycle --max-budget 10
    python -m scripts.eval_engage --all-engage

Per case it: copies the repo to a throwaway sandbox (with `evals/` excluded, so ground truth
is structurally unreachable; guard hooks stay live - they are under test too), launches a real
headless session via the Agent SDK **using the case's declared `workflow:` as the front-door
command** (`/engage` or `/engage-light`; anything else falls back to `/engage`), and has an
**LLM user-sim** answer every AskUserQuestion gate in persona (the case's `driver.md`,
falling back to `evals/driver-default.md`).

Robustness (0.30): sessions authenticate like interactive Claude Code (the API key is blanked
in the child env - runs bill to the subscription and share its usage window); a
**dead-at-birth watchdog** aborts fast with the reason if a session emits nothing within 120s
(instead of burning the whole `--timeout`); `RateLimitEvent` frames are printed as they
arrive. `--rescore <run-dir>` re-runs probe + normalizer + judge over a KEPT run without a
live session, persisting to `score-rescore.json` alongside the untouched original. When the sim grants execution-consent intent, the harness process -
standing in for the human, per ADR-002 - creates the sandbox's `.claude/.exec-consent` marker;
the session itself remains blocked from writing it. Scoring then combines a deterministic
artifact probe of the sandbox, an uncontaminated normalizer pass over the transcript
(`eval_score` against `expected.yaml`), and the rubric LLM-judge. Outputs land under
**Retention rule (2026-07-30 audit):** under `evals/runs/`, keep IN FULL (a) any run id
named in a committed `evals/eval-baseline-*.md` or `evals/artifact-review-*.md` (those
sandboxes are cited evidence and `--rescore`/`--resume-run` operate on kept runs), and
(b) all runs from the last 7 days. For anything else, delete the `*/sandbox/` subdirs and
keep the scoring outputs (`transcript.md`, `events.jsonl`, `score.json`, `report.md`);
whole run dirs older than 30 days may be purged unless referenced. Rationale: kept
sandboxes are full repo copies (~80% of bytes) and the lifecycle hooks treat stale kept
sandboxes as live engagement state.

`evals/runs/<timestamp>/<case>/` (git-ignored): `transcript.md`, `gates.json` (every simulated
Q&A), `findings.json`, `score.json`, `report.md`.

`process-full-lifecycle` is the flagship case: the only one that runs intake -> build ->
independent QA -> DoD gate -> close end-to-end. **Each case is a real engagement** - cap spend
with `--max-budget`, run at milestones. As with `/run-evals`, treat raw keyword scores as the
starting point: adjudicate misses/traps against the transcript before calling a regression
(baseline precedent: `evals/eval-baseline-0.27.0.md`).

## Transcript tripwires (the mechanical channel)

Recall grades what the team **said**. A tripwire records what the run **did** - and on
2026-09-12 a day of live reports from a corporate Windows laptop produced five defects that
were invisible to every finding-based number in this harness. `scripts.eval_score.TRIPWIRES` is
a named list of detectors over the run's `transcript.md` and `events.jsonl`; **any hit fails the
case**, with the offending line quoted into `<run>/<case>/tripwires.json` and into
`score.json`'s `tripwires_triggered` / `tripwire_evidence`.

| id | fires when |
|---|---|
| `plugin-path-guess` | a Read or Bash call errored "File does not exist" on a path under the plugin root (the invented `$PLUGIN_ROOT/references/...`) |
| `team-script-blocked` | the code-execution gate blocked one of the team's OWN scripts - the guard allow-list and the plugin's tooling have drifted apart (CLAUDE.md §7) |
| `listing-above-project-root` | a directory listing (`ls` / `dir` / `find` / `Get-ChildItem`) whose target is outside the project root, the plugin install and every temp directory |
| `missing-prompt-injection` | an `/engage` turn whose opening context carried neither `<persona-anchor>` nor `<engage-probe-result>` - the UserPromptSubmit wiring did not fire |
| `consent-or-apply-ask` | the session asked the human to create the execution-consent marker or to run a `scripts/apply-*.sh` script |

Tripwires apply to **every** case. A case opts one out by id, with a reason - CI
(`tests/test_eval_cases.py`) rejects an opt-out that names an unknown id or carries no reason:

```yaml
tripwires_off:
  - id: listing-above-project-root
    reason: the scenario deliberately asks the team about the parent directory
```

Two notes on reading a hit. `missing-prompt-injection` stays **silent** when the run captured no
hook events at all (a run from before `include_hook_events`, or one where the CLI emitted none):
not observable is not the same as absent, and failing a run for missing instrumentation would be
worse than missing the defect. And the detectors are **lexical**, like the guards they watch -
they read the capture, they never re-run anything.

**Adding one.** The next live report is one more entry in `TRIPWIRES`: an `id`, a `description`
that says what the defect was, and a `detect(ctx)` returning the offending lines. Add a firing
and a non-firing unit test in `tests/test_eval_score.py` alongside the others.

## Plugin mode (`mode: plugin` / `--plugin-mode`)

Every other case runs **repo-as-project**: the sandbox is a copy of this repo, so the plugin
root and the project root are one directory and the hooks come from this repo's
`.claude/settings.json`. **Nobody installs it that way**, which is exactly why the five defects
above went unseen. Plugin mode builds the default marketplace install instead:

```
<run>/<case>/plugin/
  home/                                   HOME + USERPROFILE (+ HOMEDRIVE/HOMEPATH on Windows)
    .claude.json                          workspace trust - the real ~/.claude.json is never touched
    .claude/                              CLAUDE_CONFIG_DIR
      plugins/installed_plugins.json      the v2 registry, one local-scope entry
      plugins/known_marketplaces.json     the marketplace, source = the repo copy below
      plugins/marketplaces/<marketplace>/ the marketplace "checkout": a copy of this repo
      plugins/cache/<mkt>/<plugin>/<ver>/ the CACHE copy the session actually loads
  proj/                                   the CLIENT project: cwd, empty apart from fixtures/
```

The session is launched with `cwd = proj/` and the plugin loaded from the **cache copy** via the
SDK's `plugins=[{"type": "local", "path": ...}]`, which the transport turns into the CLI's
`--plugin-dir` (`claude --help`: *"Load a plugin from a directory or .zip for this session
only"*). So the hooks are the plugin's own `hooks/hooks.json`, resolved through
`${CLAUDE_PLUGIN_ROOT}` - this repo's `.claude/settings.json` is never loaded, because this repo
is not the project. Both repo copies exclude `evals/` for the same reason the repo sandbox does:
ground truth has to be structurally unreachable.

Both platforms are supported on purpose (the owner runs this by hand on a Windows VM; the manual
CI job runs it on Linux). The copy is `shutil.copytree`, never `rsync`; nothing is symlinked;
names Windows cannot create are skipped on **both** platforms so the two layouts match; and the
run prints a `MAX_PATH note` when the built layout gets close to the classic 260-character
limit - keep the checkout shallow on Windows (`C:\dev\vsit`) or enable long paths.

    python -m scripts.eval_engage --case process-plugin-mode-open --dry-run   # build + print, launch nothing
    python -m scripts.eval_engage --case process-plugin-mode-open --skip-judge --max-budget 8

`--dry-run` builds the layout and prints the exact command it would launch (also written to
`<run>/<case>/dry-run.txt`), without a session and without the SDK installed - the cheap way to
check the layout on the Windows VM. `--plugin-mode` forces the layout for every selected case;
`--no-inherit-auth` skips seeding credentials into the throwaway home (layout inspection only -
the session will not authenticate).

**Auth.** A throwaway home has no login, so the builder copies **only** credential material into
it: `~/.claude/.credentials.json` and the `oauthAccount` / `userID` / `hasCompletedOnboarding` /
`firstStartTime` keys of `~/.claude.json`. Nothing else crosses over - not the developer's
projects, trust decisions, plugin registry or preferences - because inheriting those is what
would hide the defects this mode exists to find. Nothing is ever written back to the real home.

`evals/cases/process-plugin-mode-open/` is the case: a small `/engage` open in a client project
holding one synthetic two-function file, scored deterministically (`judge: none`) on the
engagement workspace landing under the **client** project's `VSIT/`, the probe's `PLUGIN_ROOT`
being carried forward, the review happening, and all five tripwires staying silent.

## The baseline verdict block (the release gate parses this)

`scripts/release_gate.py` blocks a dev → main promotion unless the version's
`evals/eval-baseline-<version>.md` **declares a verdict in machine-readable form**. Until
2026-08-01 the gate only checked the file existed, so a baseline whose own prose said "No
clean-pass claim is made for this baseline" satisfied it, and four versions shipped
unevaluated. Every baseline now carries a fenced block:

````
```eval-verdict
verdict: pass-with-adjudication
cases_total: 7
cases_passed_raw: 2
cases_adjudicated_pass: 5
unadjudicated_failures: 0
runs: 20260729T225110Z, 20260730T010541Z, 20260730T015116Z
```
````

- `verdict:` - `pass` | `pass-with-adjudication` | `fail`. `fail` blocks promotion, and
  `pass` may only be claimed when **every** case passed RAW, so an adjudicated release
  cannot be misread as a clean run.
- The counts must satisfy `cases_passed_raw + cases_adjudicated_pass +
  unadjudicated_failures == cases_total` - every case is accounted for or the gate says so.
- **`unadjudicated_failures` > 0 blocks promotion.** Adjudication is a human act (read the
  transcript, evidence why the raw FAIL is not a real failure, write it up in the record's
  table). A budget-killed or timed-out case is **unevidenced, not passed** - it stays an
  unadjudicated failure until it is re-run or adjudicated on evidence.
- Blank lines and `#` comments inside the block are ignored.

**The numbers are corroborated, not taken on trust** (2026-08-01 review: until then every
field was self-reported, so `cases_total: 1, cases_passed_raw: 1, verdict: pass` promoted a
release on a single case):

- **`runs:` is required** on a full baseline (a `Scope: deterministic-only` record is exempt,
  having no live runs to cite). List **every** run the record stands on - the example above
  cites all three 0.33.1 runs, whose rows in `results.jsonl` add up to the 7 cases and 2 raw
  passes it declares.
- The gate reads `evals/results.jsonl` for those run ids and requires that the **distinct
  cases** recorded under them equal `cases_total`, and that the cases with at least one
  passing row equal `cases_passed_raw`. A run id the log never saw is not evidence, and a
  count that does not match the rows is a finding.
- **Minimum slice: 6 distinct cases.** Below that the record is too narrow to mean anything;
  a deliberately narrow run promotes with `python -m scripts.release_gate --min-cases N`,
  which announces the lowered floor on the console.
- **More than one `eval-verdict` block in a baseline is rejected outright.** Each run's
  `report.md` tells you to paste its drafted block, so a leftover raw draft next to the
  adjudicated one is an easy accident; rather than pick a block by position (and judge the
  release on the wrong claim), the gate refuses until exactly one block remains.

`scripts.eval_engage` drafts the raw block into each run's `report.md` - copy it into the
baseline, merge the `runs:` lines when a record stands on several runs, and move cases from
`unadjudicated_failures` to `cases_adjudicated_pass` as you adjudicate them. The gate also
ages a baseline against `docs/DEFINITION-OF-DONE.md`, `docs/house-rules.md`,
`docs/WAYS-OF-WORKING.md`, `docs/code-review-method.md`, `docs/coding-standards.md`,
`docs/scope-and-stack.md`, `docs/team-extensions.md`, `docs/templates/`, `.claude/hooks/`
and `.claude/settings.json` alongside the agents/skills - all of them steer the team at run
time exactly as a skill does. Ageing covers the **working tree** as well as the commit log:
an uncommitted edit to any of those paths fails the gate, because the eval behind the
baseline never exercised it.

## The tracked results log (`evals/results.jsonl`)

`evals/runs/` is git-ignored and pruned by the retention rule, so the numbers used to
survive only as prose in a baseline. Every scored case now also appends one JSON row to
**`evals/results.jsonl`** (tracked, append-only, deduped on `run_id` + `case` + `mode`):

    {"run_id": "20260730T010541Z", "case": "process-full-lifecycle", "mode": "run",
     "version": "0.33.1", "passed": false, "recall": 0.778, "must_find_missed": [...],
     "traps_triggered": [], "judge_score": 0.48, "judge_pass": false, "cost_usd": 14.07,
     "num_turns": 61, "duration_s": 2400.0, "timed_out": true, "session_error": false,
     "recorded_at": "..."}

Writing is automatic (live runs and `--rescore`). To backfill from saved run outputs:

    python -m scripts.eval_engage --record evals/runs    # no session, no tokens

`version` is the plugin version the run exercised - taken from the run's kept sandbox when
backfilling, and `"unknown"` where the sandbox was pruned (never today's version stamped on
an old row). Recall and judge scores are trendable from this file instead of being
re-narrated each release.

## A case (`expected.yaml`)

Abridged from the real `review-seeded-bugs-py` case (one planted issue of its four shown):

```yaml
case: review-seeded-bugs-py
workflow: /deep-review          # the skill the blind run inlines
rubric: code-review             # resolves to evals/rubrics/code-review.md
input: input_alert_export.py    # the ONLY file shown to the team-under-test
mode: repo                      # optional: repo (default) | plugin - see "Plugin mode" above
judge: none                     # optional: skip the LLM judge for a deterministic-only case
planted:                        # issues the team MUST surface
  - id: SEC-1
    keywords: [hardcoded, secret, credential, password, api key]
    location: input_alert_export.py:8
    min_severity: critical
    must_find: true
forbidden:                      # false-positive traps - must NOT be flagged
  - id: FP-1
    keywords: [magic number, undocumented threshold, LARGE_ORDER_MULTIPLE]
pass:
  require_all_must_find: true
  forbid_all: true
```

Trap keywords are substring-matched against each finding's title+kind+location, so keep them
**assertion-only**: a keyword like "no below-the-line" would also match a correct answer that
says "do not cut the threshold with no below-the-line testing". Phrase traps so that only an
actually-wrong answer contains them, and record the rationale in `notes.md`.

Both planted and forbidden specs also accept **`exclude_keywords:`** - a mention-guard that
vetoes a match when any of them appears in the finding's haystack. Use it where a keyword net
cannot tell presence from absence-talk (a planted "summary email" spec matching "summary email
never produced" - observed live 2026-07-25) or a defect-flag from a fix-recommendation (the
0.27.0 baseline's mention-as-fix trap artifact). CI checks that an exclude is never a substring
of the spec's own match keywords.

## Adding a case

1. `mkdir evals/cases/<id>/`, add a **synthetic** input file with deliberately seeded issues -
   written as the team would really receive it (no answer keys or eval banners; see "What
   lives where in a case").
2. Write `expected.yaml` (planted + forbidden + pass rules) - the ground truth. Set `input:`
   to the input file's name and `workflow:` to the driving skill; anchor each planted
   `location:` to the issue's exact line (the scorer tolerates +/- 3).
3. Point `rubric:` at the relevant `evals/rubrics/*.md`.
4. Put the grading rationale in `notes.md` (seeded-issue detail, correct/forbidden behaviour,
   trap rationale) - never in the input file.
5. Sanity-check the scorer against a hand-written findings JSON before relying on it. CI's
   contract tests (`tests/test_eval_cases.py`) pick the new case up automatically and verify the
   manifest parses, its `input:`/`rubric:`/`workflow:` pointers resolve, numeric line anchors sit
   inside the input file, `scenario.md` carries no answer-key sections, a perfect run passes and
   an empty run fails (or passes, for zero-finding cases - add those to `ZERO_FINDING_CASES`).
