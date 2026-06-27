# 🛡️ Data-safety demo

*A real `/demo` transcript: Morgan shows the §5 keystone - real data never reaches the model - and
deliberately triggers the raw-data guard so you watch it block. [Back to demos](README.md).*

---

> 🎩 **Data-safety demo - the keystone.** This is the most important thing the team does: **real data
> never reaches the model.** I'll show you the three layers, and then I'll do something deliberately -
> I'll *try* to read raw data and let you watch the guard **hard-block me in real time.** Let me start
> with what's *safe*:

```console
$ ls data/synthetic/ && head -1 data/synthetic/spoofing.jsonl
spoofing.jsonl
{"ts_ms": 468, "trader": "TRADER_SYNTH_01", "instrument": "SYNTH-EQ-0001", "order_id": "G00", "side": "BUY", "price": 100.0, "qty": 100.0, "kind": "NEW"}

$ ls -d data/*/
masked/   raw/   synthetic/
```

> 🎩 See that synthetic record? `TRADER_SYNTH_01`, `SYNTH-EQ-0001` - **totally fabricated.** That's
> what agents work on. Now the **🔴 raw tier** - the one that's off-limits.
>
> **Watch this.** I'm now going to deliberately try to read raw data, exactly as a careless agent
> might. On a real engagement this could be confidential bank records. The guard should stop me cold:

```console
$ head -2 data/raw/orders.jsonl

PreToolUse:Bash hook error:
  Blocked (raw-data marker in input - tool=Bash): this targets raw, un-masked data (data/raw/).
  Agents must not read raw records into context (CLAUDE.md §5) - they would be sent to the model
  provider. Run `python -m scripts.ingest` to produce masked data under data/masked/, then use
  that (or synthetic data from scripts/gen_synthetic.py) instead.
```

> 🎩 **There it is - blocked, in real time.** That wasn't staged: the `guard-raw-data.py`
> **PreToolUse hook** intercepted my `head data/raw/…` command *before it ran* and refused it. The
> model never saw a byte. And notice it didn't just say "no" - it told me the safe alternative.
>
> **That's the keystone, and it's a *hard* block, not a polite request.** The layered defence:
>
> 1. **🔴 The hook (what just fired)** - harness-level; can't be talked around by the model
>    "forgetting" a rule. It even fires on the team's own commit messages if they contain that path.
> 2. **🟠 The masking on-ramp** - the *only* sanctioned way real data enters: `scripts.ingest`
>    tokenises IDs, shifts timestamps, redacts free text → governed output under `masked/`. And we
>    can **check our own work** - let me show the validator catching a leak:

```console
$ python3 -m scripts.validate_masking --in masked-with-a-leak.jsonl
[FAIL] no residual PII in masked file (string fields): ['EMAIL', 'IBAN', 'PHONE', 'ACCT']
[PASS] k-anonymity: no quasi-identifiers declared - skipped (declare to enforce)
RESULT: FAIL
$ echo "exit=$?"
exit=1
```

> 🎩 **The validator caught it - FAIL, exit 1.** That `--in` mode scans your *actual* masked output
> and refused to pass a file with a residual email/IBAN. Better to fail loudly here than leak quietly.
>
> 3. **🟢 The attestation** - for data that's *already* safe, you confirm it at intake. The team can't
>    verify your data for you, so that responsibility stays with you - stated plainly, not hidden.
>
> **One honest caveat:** that `redact` step is **regex-only** today - great for structured fields
> (emails, IBANs, accounts), but it would **miss names and obfuscated IDs in free-text chat.** So for
> real *comms* surveillance you'd want NER first - that's on the roadmap, and the README says so
> rather than pretending otherwise.

---

## What this demo showed
- **🔴 A real hard-block** - the guard stopped a raw-data read at the harness level, live.
- **🟢 Synthetic-first** - agents work on fabricated data by default.
- **🟠 Mask + verify** - the on-ramp governs real data, and the validator *failed* a file that leaked
  PII rather than waving it through.
- **Honest about the edge** - regex redaction isn't enough for free-text comms; the docs say so.

**The keystone, end-to-end: real data never reaches the model, and it's enforced, not just promised.**
