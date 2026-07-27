# Frequently asked questions

**What can it actually do?**
Lots! If it comes up in surveillance engineering, there's probably a specialist for it. The
short version:

- **Build things.** Detection rules, data pipelines, utility scripts, reconciliation jobs,
  reports, tooling. Everything arrives specced, tested and independently QA'd, with docs a
  stranger could pick up and run.
- **Look hard at things you already have.** Code reviews and audits (security included),
  threshold tuning backed by real numbers, "are we actually monitoring everything we think
  we are?" coverage checks, and model validation by someone who didn't build the model.
- **Get to the bottom of something odd.** An alert storm, a false-positive spike, a feed
  gone quiet, a trade that should have alerted but didn't. Proper investigations: evidence
  first, then findings, then a fix plan. Never a shrug.
- **Write things down properly.** Requirements, specs with testable acceptance criteria,
  runbooks, handover packs, decision records. It will also happily reverse-engineer
  documentation from code nobody wrote docs for the first time round.
- **Think a problem through with you.** A vague "we keep getting hammered by alerts on X"
  becomes scoped requirements, options with a recommendation, or a plan. Same for new
  business requirements, reg-change impact, or a hard question that just needs the right
  specialist's hat on.

You don't have to pick a category. Tell `/engage` what's going on and Morgan works out the
shape. Whatever comes back is traceable, evidence-tagged, and checked by someone other than
whoever made it.

**What's the difference between "measured" and "inferred"? I keep seeing 📊 and 🧠 tags.**
It's the team's honesty system, and probably the single most useful thing to understand.
📊 **observed/measured** means the team actually ran or counted something and the evidence
exists on disk: a test run, a line count, a diff. You can go look. 🧠 **inferred** means it's
a reasoned conclusion, not a measurement: "this loop is probably slow at your volumes" from
reading the code is inferred; running a profiler on it would be measured (and running
anything needs your consent, see below). There's also 📄 **coded** for "it's literally
written in the code, here's the file and line". The rule is that an educated guess must never
dress up as a fact, and it's enforced: a "measured" claim whose evidence file got deleted is
downgraded to inferred at close.

**Does it hallucinate?**
LLMs can, so the honest answer is: the system is built assuming it will try, and is designed
to catch it. Every data claim needs an evidence tag (above). Citations run through a
mechanical gate that flags anything unverified rather than letting the model invent a
plausible-looking URL. A mechanical checker verifies claimed files actually exist on disk,
independent QA re-runs claims rather than trusting them, the PM spot-checks findings
including the discarded pile, and the machine-readable state file is hash-verified against
its human rendering. When an independent three-reviewer audit went through a full live
engagement pack, every load-bearing number (test counts, build hashes, finding tallies)
verified against disk and nothing fabricated was found. That's not a guarantee, it's a
design: nothing is trusted until it's tied to something checkable, and your sign-off stays
the final gate.

**What analysers does the review use, and what happens if I don't have them installed?**
The standard ones per language when present (ruff, mypy, bandit, semgrep, gitleaks,
shellcheck and friends). At engage-time the team inventories what's actually installed and
works with that; nothing silently pretends a tool ran. Missing analyser? The review still
happens, statically, and the report says exactly which tools ran and which findings are
therefore 🧠 inferred rather than 📊 measured. Same philosophy for the environment: no
`python3`? It falls back to `python`, then `py`. No `bash`? It skips the shell helpers and
calls the analysers directly, and says so.

**Why won't it run my code or tests? And how do I grant consent when I want it to?**
By design: review is static by default, because running code under review is a real risk.
Execution needs consent that only you can grant, by creating a marker file the model is
physically blocked from writing (a hook enforces it, and the model can't edit the hook
either). Until then, anything that would need a run stays honestly tagged 🧠 inferred.
Granting it is one command, run by you:

```bash
touch .claude/.exec-consent        # from any terminal at the project root
```

or type `! touch .claude/.exec-consent` as the first characters of your Claude Code prompt
line (the `!` runs it as your shell command, not the model's). Alternatively set
`CST_ALLOW_EXEC=1` in the environment you launch Claude Code from - handy for CI. To revoke,
delete the file (`rm .claude/.exec-consent`); answering "static only" at intake deletes it
for you. The asymmetry is the point: the model may *delete* the marker (fail-safe) but can
never *create* it, so consent is always a human act with a file's worth of evidence.

**Who is Morgan?**
The project manager, and the only "person" you ever need to talk to. Morgan opens every
engagement (the 🎩 at the start of a line means the PM is speaking), asks the intake
questions, decides which specialists the job actually needs and says so out loud before
spawning any, challenges their findings rather than relaying them, and comes back to you at
every gate. Morgan is a persona with teeth: the discipline is re-injected every turn while an
engagement is open, so it survives long sessions. The specialists (Amara, Mateo, Linh, Ravi
and friends) are separate agents Morgan briefs and coordinates; you can meet them with
`/meet-the-team`, but you never have to manage them yourself.

**What's the `artifacts/` folder that appeared in my project?**
That's the engagement's paper trail - everything the team produces lands there, each document
in both `.md` (source) and `.html` (readable render). The key files: **`START-HERE.md`** is
exactly what it sounds like, the index to read first - what this engagement is, whether it's
finished (⏳ in progress / ⛔ blocked / ✅ closed) and what to read in what order.
**`engagement-state.json`** is the machine-readable version of the same truth (status,
outstanding work, decisions, the artifact inventory); START-HERE is generated from it, so
don't hand-edit either. **`engagement-brief.md`** records what was agreed at the start.
Mid-engagement you'll see pass-scoped names like `review-pass-1.md` and `qa-handover.md`
(interim by design). **`delivery-report.md`** and the **`engagement-summary-*.txt`** email
only appear at close - if they're absent, the engagement isn't done, on purpose. Treat the
folder as the audit trail: it's the evidence behind every claim, so archive it rather than
delete it, and add `artifacts/` to your `.gitignore` if you don't want it in version control.

**Do I need to learn all the commands?**
No. `/engage` is the front door and routes everything; the rest are shortcuts the team
itself knows how to reach.

**What if my session dies mid-engagement?**
Nothing is lost. The engagement's state lives in a machine-readable file on disk (updated
with every artifact write), with a human-readable START-HERE generated from it. A brand-new
session reads those, picks up the outstanding list and carries on, this has been proven live,
twice in one day, including once after the session hit its budget cap mid-delivery.

**Can I trust it with real data?**
Short version: don't paste raw data, and it will try hard to stop you. `data/raw/` is
hard-blocked from the model by an always-on hook, everything else runs on your attestation
that it's masked or synthetic, and `/prepare-data` exists to get you there. Pseudonymised
still counts as personal data, so prefer fully synthetic. See
[Handling real data](../README.md#-handling-real-data) for the long version.

⚠️ **One caveat on `/prepare-data` itself**: the masking pipeline behind it is a
**placeholder implementation** (a proof-of-concept showing the shape of the workflow, with a
[roadmap](prepare-data-roadmap.md) of what a real one needs). Do not rely on it as your
control for de-identifying production data - if the stakes are real, use your organisation's
approved masking tooling, or fully synthetic data, and treat `/prepare-data` as a demo of
where that step slots into the flow.
