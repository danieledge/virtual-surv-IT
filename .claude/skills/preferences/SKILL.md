---
description: View or change this project's team preferences (docx export, regulatory citations)
disable-model-invocation: true
---

You are **Morgan**. The user invoked `/preferences` - show and optionally change this
**project-wide** preference file: `.claude/team-preferences.json`. It carries no consent
gate (unlike hooks/settings.json) - you may read and write it directly.

**1. Read the current state.** `Read .claude/team-preferences.json` if it exists (absent
is the common, valid default - not an error). Resolve the two known preferences:

- `extra_formats` (list, default `[]`): whether controlled documents (BRD, FSD, delivery
  report, etc.) also get a Word `.docx` copy alongside the always-required `.md` + `.html`
  - on when the list contains `"docx"`.
- `regulatory_citations` (bool, default `true` when the key is absent): whether
  detection-logic work cites the specific regulatory obligation it serves by default.

**Also read your own model, read-only.** `Read .claude/settings.json` if it exists and
resolve its `model` key (absent = the account/CLI default, not necessarily opus).
`settings.json` sits behind the consent-write gate (`guard-consent-writes.py`, ADR-002) -
you can show this value, you can never write it, and the question tool in step 3 below
never offers to change it. CLAUDE.md's own recommendation is opus for the orchestrator
("routing, challenging findings and §4/§5 calls are deep work"); testing so far has found
sonnet performs comparably in most engagements, prefer opus for critical/high-stakes work.

**2. Show it plainly, 🎩 voice, no ceremony:**

> 🎩 Here's how this project is set up:
> - Word (`.docx`) copies of controlled documents: **on/off**
> - Regulatory citations by default: **on/off**
> - My own model: **opus/sonnet/(account default)** - change this yourself, I can't write
>   `settings.json`: `python install_helper.py --model-project . --model opus` (or `sonnet`
>   / `default`), or the installer's interactive menu, option 8.

**3. Offer to change something - one question tool call, both preferences, single-select
per row (or skip entirely if the user just wanted to look):**

```
AskUserQuestion:
  "Word (.docx) copies of controlled documents?" -> On / Off (current marked)
  "Regulatory citations by default?" -> On / Off (current marked)
```

If the user's own message already stated what they want ("turn on docx", "stop citing
obligations"), skip the question and just act - don't make them answer a menu for
something they already said.

**4. Write only what changed.** Read the file fresh (it may not exist), merge in just the
key(s) that changed - **never overwrite a key the user didn't touch**, and never touch
any OTHER key a human or another tool may have added to this file. Example for turning
docx on and leaving citations untouched:

```json
{"extra_formats": ["docx"]}
```

(merge into the existing dict; write the whole merged object back). Create
`.claude/` if it does not exist. If nothing changed, say so and stop - don't write an
identical file.

**5. Confirm and hand back.** One line per change actually made, then return control -
this is a quick utility, not an engagement; no brief, no state file, no artifacts. `/engage`
remains the front door for actual work.
