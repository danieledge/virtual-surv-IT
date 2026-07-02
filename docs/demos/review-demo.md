# 🔍 Review demo

*A real `/demo` transcript: Morgan reviews a small synthetic Python file end-to-end, narrating every
decision. [Back to demos](README.md).*

> 📖 **Reading key:** blockquotes that begin with **🎩** are **Morgan, the AI PM, speaking live in
> the session** (his words, generated at the moment - not the repo author's). Plain text is editorial
> framing; ` ``` ` blocks are real commands/output and verbatim agent findings.
> [Full key](README.md#how-to-read-a-transcript-whos-speaking).

---

> 🎩 **Review demo it is.** I'll review a small synthetic Python file end-to-end. Let me walk you
> through the intake first, exactly as a real engagement runs - except **I'll answer the questions
> myself and tell you why.**
>
> **The two safety gates (I answer these; on a real job, *you* would):**
> - ⚠️ **Execution?** → **No - static only.** This is a quick read-plus-analysers review; I don't
>   need to *run* the code, and static-by-default is the safe choice.
> - 🛡️ **Data?** → **Synthetic, no real data.** The file is a synthetic eval fixture.
>
> **Now I right-size - out loud, because that's the whole point of cost discipline:** this is **one
> small file** → I'll keep it to **just Ravi (`code-reviewer`)** - 1 agent, not 16. **Ravi runs on
> opus** *because* cross-language security judgement is exactly the subtle, high-blast-radius call
> that earns the top tier.

### → Ravi (`code-reviewer`, opus) reviews the file

```
Findings
🔴 Critical - Hardcoded credential - input_alert_export.py:9 - 🧠 inferred (gitleaks ran but did
   not flag; reasoned by reading). CWE-798. DB_PASSWORD = "s3cr3t-..." is a plaintext secret.
   Fix: read from os.environ["DB_PASSWORD"]; never hardcode.
🔴 Critical - SQL injection - input_alert_export.py:19 - 🧠 inferred. CWE-89. trader_name is
   string-concatenated into the query.
   Fix: cur.execute("SELECT * FROM alerts WHERE trader = ?", (trader_name,))  # parameterised
🟠 Warning - Resource leak - input_alert_export.py:32-35 - 🧠 inferred. open_db returns a cursor
   but the connection is never closed.
🟡 Medium - O(n^2) dedupe - input_alert_export.py:23-29 - 🧠 inferred. `a not in unique` is a
   linear scan in a loop. Fix: track membership with a set().
🔵 Style - missing docstrings - input_alert_export.py:16,23,32,38 - 🧠 inferred. Non-blocking.

Deliberately NOT flagged
- LARGE_ORDER_MULTIPLE = 5.0 (line 13): correctly documented threshold with rationale + tuning
  date per CLAUDE.md §4 - this is the planted FP-trap; flagging it would be a false positive.

Tooling coverage: ruff/bandit/mypy/semgrep MISSING; gitleaks ran (no leaks reported - note the
hardcoded password evaded its ruleset). All findings therefore 🧠 inferred from reading.
```

> 🎩 **Ravi's back** - and notice he did exactly what good looks like: found the issues **and**
> correctly *left the documented threshold alone* (no false alarm). That's the **blackboard** in
> action - his findings are structured data I can now work with, not chatter.
>
> **Now my challenge pass - I'm a sceptic, not a relay.** I independently re-score: both Criticals
> verified by reading; the Warning and Medium are genuine. **Note:** Ravi tagged everything
> **🧠 inferred, not 📊 measured**, *because the Python analysers aren't installed here* - only
> gitleaks ran, and it **didn't flag the password**. So I will **not** let these reach you dressed up
> as tool-verified facts.

**Scoreboard:**

| | Finding | Basis |
|---|---|---|
| 🔴 | Hardcoded credential (`:9`) | 🧠 inferred |
| 🔴 | SQL injection (`:19`) | 🧠 inferred |
| 🟠 | Connection leak (`:32-35`) | 🧠 inferred |
| 🟡 | O(n²) dedupe (`:23-29`) | 🧠 inferred |
| 🔵 | Missing docstrings | 🧠 inferred |
| ✅ | Documented threshold - *correctly NOT flagged* | - |

> 🎩 Now the flagship part - **did the team actually do a good job? Let me prove it, not assert it.**
> This file is one of our eval golden cases, so I can score Ravi's review against the known ground
> truth - the **regression net** live:

```console
$ python3 -m scripts.eval_score --expected evals/cases/review-seeded-bugs-py/expected.yaml --findings review.json
VERDICT: PASS ✅
recall = 1.0 (found all planted issues)
must-find criticals missed: none
false-positive traps triggered: none
```

> 🎩 **And there's the proof - VERDICT: PASS, recall 1.0, zero false alarms.** The eval harness
> independently confirmed Ravi caught *every* planted issue and didn't trip the documented-threshold
> trap. If a future prompt tweak quietly weakened that review, this score would drop and we'd catch it.

---

## What this demo showed
- **Right-sizing** - one small file → **1 agent, not 16.** The count is stated out loud before spawning.
- **Model tiering** - Ravi on **opus** for security judgement; on a bigger job Pip would do the
  mechanical scoring on **haiku** for pennies.
- **The blackboard** - structured findings flow forward; no agent-to-agent chatter.
- **Challenge pass** - the PM re-scores as a sceptic and verifies the evidence basis (🧠 inferred,
  not 📊 measured - no overselling).
- **The self-test** - the result is *proven* with a real eval score, not just claimed.
