# Safety gates - verbatim disclaimers + consent mechanics (read when a target exists)

> Loaded just-in-time by `engage` (progressive disclosure - this detail doesn't ride in every
> engagement's context). Repo path: `.claude/skills/engage/references/safety-gates.md`; installed
> plugin: `$PLUGIN_ROOT/.claude/skills/engage/references/safety-gates.md`.

## Execution-safety disclaimer (show PROMINENTLY - its own block, ⚠️ header, bold; never buried)

> ⚠️ **SAFETY - running your code.** I review code **statically by default** (reading it +
> analysers that don't run it). To run its tests or profile it, the team has to **execute** it.
> I'll keep strictly to static-only if you say so - but I **can't guarantee a mistake never
> happens**, so please treat anything you hand over as if it **could** be run: **make sure it's
> safe to execute and don't provide code that would be harmful if run. Ensuring handed-over code
> is safe is your responsibility.**

## The execution-consent question (ask once, batched in the opening screen when code is involved)

Word it exactly as an **intent** question, not a grant - the menu answer does NOT open the gate,
and the options must say so or the user is misled into thinking they've consented:
*"Should the team execute the code under review (run tests / profile)?"* →
- **Yes - I'll grant consent** (trusted code, safe/dev or sandbox env, synthetic data only §5).
  *Description must include:* "this answer alone doesn't unlock anything - I'll give you a
  one-line command to type; execution stays hard-blocked until you do."
- **No - static analysis only** (dynamic/perf findings stay 🧠 inferred; any existing consent
  marker gets deleted).

Record the answer; don't re-ask per command. Default to **No** if unsure; **never** run code of
unknown provenance or touch production data/systems.

## The menu answer is INTENT; the marker is the CONSENT

Execution is hard-blocked by `guard-code-execution.py` until authorised - and **the team cannot
grant that authorisation to itself**: a second hook (`guard-consent-writes.py`, ADR-002 rec 5)
blocks any model write of the consent marker or the settings files. On **"Yes"**, ask the user to
perform the actual consent act **themselves** - and **always show the command with the absolute
project path** (resolve the project root first, e.g. from `pwd`; never a bare relative path, which
silently creates the marker in the wrong place if their terminal is elsewhere).

**Which form(s) to show - checked against the step-0 probe's `OS=` field, never inferred or
guessed from context:**
- **`! touch /absolute/path/to/project/.claude/.exec-consent`** - always show this one (`!` as
  the *first* character of the prompt line runs it as their own shell command; on Windows the `!`
  shell is Git Bash, so `touch` works there too).
- **`OS=Windows` → ALSO show the PowerShell form in the SAME message, every time, no exceptions**:
  `ni "C:\absolute\path\.claude\.exec-consent" -Force` (a Windows user pasting into their own
  terminal has no `touch`; live report 2026-08-03: the `!` form was given alone on a Windows host,
  leaving the user with a command that doesn't work in their own terminal).
- If the user's own messages point at `cmd.exe` specifically, add that form too:
  `type nul > "C:\absolute\path\.claude\.exec-consent"`.

Alternatively `CST_ALLOW_EXEC=1` in the launch environment (the hard override - also human-only).
**Never wrap consent-granting in a helper script** - the act stays a literal command the human
types. **Verify the marker exists** (a read-only `ls .claude/.exec-consent` is allowed) before
executing anything; if the user answered "Yes" but the marker never appears, execution is still
blocked - say so plainly, keep dynamic findings 🧠 inferred, and never present the menu answer as
consent. On **"No"**, **delete** `.claude/.exec-consent` if it exists (`rm` is allowed - closing
the gate is always fail-safe), so the gate stays closed. Repeat the responsibility note in the
final Delivery Report.

## Data-safety disclaimer (show at startup too, right next to the execution one - CLAUDE.md §5)

> 🛡️ **DATA SAFETY - what you share.** 📡 Everything you point me at goes to the model provider.
> 🔴 Raw data in `data/raw/` is **hard-blocked** - I can't read it. 🟠 For **any other data you
> share**, by giving me access you **confirm it carries no PII/MNPI or anything your data policy
> prohibits - or that you've anonymised/masked it appropriately.** 🤖 I **can't verify that for
> you** - keeping shared data safe and compliant is **your responsibility.** 🟢 Unsure? Go
> synthetic, or **pre-mask/sanitise by your own approved external means** - `/prepare-data`
> can help but is **best-effort, not production-grade**.

## The data-attestation question (include only when data is plausibly involved)

Header `Data safety`, `multiSelect: false`:
*"Any data you'll share - is it safe to use?"* →
**Yes - synthetic/masked/anonymised, no prohibited PII** · **No / unsure - help me prepare it**
(→ `/prepare-data`) · **No data involved** (always offered, so it's one tap).

Record the answers; don't re-ask per file/command. **`data/raw/` stays hard-blocked regardless.**

## Persist the answers the moment the workspace exists (engage step 4)

The transcript is not the record: a compacted or resumed session must re-read these from disk and
must never re-ask them. As soon as `engagement_state init` has run:

- `set-decision data-attestation "<answer / no data involved>"`
- `set-decision fix-cycle "<the review menu's Q3 answer>"`
- `record-consent-outcome asked|declined` - a "No" or "unsure" records `declined`.

The recorded outcome is **never a grant**: the grant stays the human-created marker only, and the
state file cannot represent one (ADR-002). Repeat the execution- and data-responsibility notes in
the final Delivery Report.
