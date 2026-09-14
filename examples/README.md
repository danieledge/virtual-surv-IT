# Shipped sample engagement

One complete engagement the team ran, frozen under `engagements/` so anyone can read a finished
piece of work without spending a token. Open it with `virt-surv try --replay` (in a session,
`/demo replay`): the engagement folder is copied into a throwaway project and its evidence room
opens in the browser. `engagements/` is laid out exactly as a project's `VSIT/engagements/`
root, index files included (`ENGAGEMENTS.md`, `engagements.json`), so the team's own
Definition-of-Done check passes on a copy of it as shipped.

## `engagements/alert-threshold-check-review/`

A code review of a two-function synthetic helper, `alert_threshold_check.py`, that decides
whether a day's activity on an account is reportable. The user asked whether the threshold is
defensible as written, whether the aggregation does what its name says, and what else would
need fixing before production.

**Provenance.** Eval run `20260914T072757Z` of the `process-plugin-mode-open` case, which
runs the plugin the way it is installed (a marketplace cache copy, a client project that is not
the plugin repo, hooks wired through the plugin's own `hooks/hooks.json`). Orchestrator on the
opus tier, 27 turns, 16.37 USD, no tripwire fired, plugin version 0.37.0. The scoring inputs of
the same run are kept under `evals/golden-runs/process-plugin-mode-open/` for CI's token-free
replay. Input and every piece of data in it are synthetic (CLAUDE.md section 5).

**What is in the folder.**

| File | What it is |
|---|---|
| `START-HERE.md` / `.html` | The generated front page: status, team, verdict, reading order, every artifact |
| `engagement-state.json` | The machine-readable state the front page is rendered from |
| `engagement-brief.md` / `.html` | What was asked, scope, the intake decisions (execution declined, no data shared) |
| `data/findings-*.jsonl` | Three findings packs: the code review, the compliance review, the re-review after the fix round |
| `delivery-report.md` / `.html` | The consolidated report: findings, dispositions, what was fixed, what stays open |
| `qa-handover.md` / `.html` | The QA pass, written and marked as inferred because nothing was executed |
| `engagement-summary-alert-threshold-check-review.txt` | The summary email, signed by Morgan as an AI agent |
| `EVIDENCE-ROOM-alert-threshold-check-review.html` | The evidence room rendered at close |

**What was done to it after the run, and why.** The run ended with the engagement in
`closing`: the sandbox's interpreter had no Markdown renderer, so four `.html` siblings could
not be produced and the mechanical Definition-of-Done gate refused the close (the email in the
folder says so). On this machine the same team scripts finished the job, with no model call:
`render_html` produced the four siblings, `engagement_state set-status closed` recorded the
verdict the run itself had reached, and the gate passed. The one edit to the run's words is the
requester's name in the brief, which was the eval harness's account and is replaced with a
placeholder. Everything else, including the absolute sandbox paths in the state file and the
findings the team got wrong and then caught, is as the run left it.

The folder is a record. Do not re-close or hand-edit it; `virt-surv try --replay` works on a
copy.
