# Plan: unattended runs move to `-p`, gated

**Status:** proposal, 2026-08-25. Nothing built.
**Ask (owner):** "lets move unattended to -p but gated ie can be unattended headless or
unattended normal" + "plan it out and research existing solutions we can leverage".

---

## 1. The two flags that decide the design

Researched before designing. Both are documented CLI flags, and each removes something we
built by hand and got wrong:

**`--session-id <uuid>`** - *we* choose the session id and pass it in. The launcher generates
a UUID, records it on the engagement pack, and starts the run with it. That is the
session-to-engagement correlation problem **gone**, not worked around: no newest-file guess,
no date scoping, no two-engagements-in-one-day ambiguity. It was the single worst thing about
the reader we just deleted.

**`--max-budget-usd <n>`** - a **hard** stop, print mode only, and *subagent spend counts
toward it*. Past the cap, spawning another subagent fails with `Budget limit reached`. Our
ceiling has always been advisory pacing that a run could talk itself past. This makes it
real, and it makes it real at the only layer that can enforce it.

Plus `--max-turns` as a second bound, and `system/api_retry` events so a stalling run is
visible rather than just slow.

## 2. What we can leverage, and what we should not

| Option | Verdict |
|---|---|
| **`claude -p --output-format stream-json`, consumed over a pipe** | **Yes.** Stdlib only - `subprocess` + `json`. A documented, public contract, unlike the internal transcript. |
| **Python Agent SDK (`claude-agent-sdk`)** | **No, for now.** It is genuinely better ergonomics - typed messages, `interrupt()`, `can_use_tool` callbacks, session listing - but it is a `pip install` into an estate whose whole premise is vendored dependencies and no network. It also shells out to the same CLI underneath, so it buys convenience rather than capability. Revisit only if it vendors cleanly as pure Python. |
| **OpenTelemetry** | **Yes, where an estate already runs a collector.** It is the documented monitoring answer and needs no code from us. It is not a substitute for the above, because it tells you about a run it does not control. |
| **`--bare`** | **Never here.** Documented as the recommendation for scripted calls, and it skips hooks, skills, plugins and CLAUDE.md - which disables this entire team. Worth a comment in the code so nobody adds it as an optimisation. |

## 3. The gate

One new row on the unattended pre-flight, where every other unattended decision is already
made while a human is present:

```
  How it runs      in a window          <- today's behaviour
                   headless             <- claude -p, supervised by the launcher
```

**In a window** - a real interactive session in its own terminal. You can attach to it, type
into it, watch it. The spend ceiling stays advisory, because nothing outside the session can
enforce it. This is what exists now.

**Headless** - `claude -p`, no terminal at all. The launcher owns the process: it feeds the
prompt, consumes the event stream, and enforces the ceiling with `--max-budget-usd`. You
cannot type into it, which is the point - unattended means unattended.

Naming: "headless" over "detached" or "background", because it is the word the documentation
uses and the word the owner used.

## 4. What headless changes about the degrade ladder

This needs deciding, not assuming. Today `on_budget` offers park / light / continue at an
**advisory** ceiling. With a hard stop the rungs mean different things:

- **park** - `--max-budget-usd` = the ceiling. The run stops at the cap. Clean, and the
  engagement resumes normally.
- **light** - cap set at the ceiling, and the launcher restarts the remainder with
  `--append-system-prompt` naming the light profile. A second process, so it must be a
  deliberate design rather than a side effect.
- **continue** - the cap is set ABOVE the ceiling (or omitted) and the ceiling becomes a
  reporting threshold only. Honest, but it means "continue" buys a soft ceiling and the other
  two buy a hard one, which must be said on the screen rather than discovered.

**Recommendation:** set `--max-budget-usd` to a hard ceiling in every case, and let the rung
decide what happens *at* the ceiling. A run that cannot exceed its cap is the whole reason to
have one.

## 5. Shape

- **`scripts/headless_run.py`** - owns one child process. Builds the argv, streams stdin/
  stdout, decodes newline-delimited JSON, and turns events into state. Stdlib only, no async
  framework: one process, one pipe, one reader loop.
- **The launcher's monitor reads that state**, exactly as it reads `engagement-state.json`
  today. The screen does not change shape; its source does.
- **The stream is the workflow view, properly this time**: `system/init` gives the session
  and model, `assistant`/`user` messages with `parent_tool_use_id` give the stage tree
  including nesting, the final `result` gives `total_cost_usd` and a per-model breakdown.
  Everything the deleted reader inferred, published.

## 6. Risks

- **Owning a process is a real responsibility**, not a screen refresh: lifetime, orphaning,
  SIGTERM (exit 143, turn left unfinished), and a launcher that exits while a child runs.
  This is the part to build carefully, and the part that makes it a supervisor.
- **Permissions must be pre-granted.** `--permission-mode dontAsk` denies anything outside
  the allow rules *and* denies `AskUserQuestion` outright - which is correct for a run whose
  gates were answered at the pre-flight, and wrong for anything else.
- **A headless run cannot ask.** Everything the team would have asked has to already be
  decided: data attestation, execution consent, the ceiling and its rung. That is exactly
  what the pre-flight collects, so the gate belongs there and nowhere else.
- **Cost figures are documented as client-side estimates.** Better than ours, still not a
  bill, and the honesty framing stays.
- **`-p` on Windows** is where this repo's last four bugs lived. Verify on WINTEST before
  claiming it works, not after.

## 7. Build order

1. `headless_run.py` - argv construction and stream decoding, tested against captured
   `stream-json` output. No process control yet.
2. Process supervision: start, monitor, terminate cleanly, survive the launcher exiting.
3. The pre-flight row, and `--session-id` recorded on the pack at init.
4. Monitor reads the live state.
5. Windows verification on WINTEST.

Steps 1-3 are useful before any UI exists: a run that is correlated by session id and capped
by a hard budget is already better than what ships today.
