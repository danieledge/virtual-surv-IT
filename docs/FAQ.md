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

**I already have ChatGPT / Claude / Copilot, so why would I need this?**
You already have the engine; this is the vehicle. Virtual Surv-IT *runs on* Claude. It is not a
rival model, but a demonstration of what the same model does when you stop driving it from a
blank chat box. A chat window cannot give you:

| With a chat window | With this |
|---|---|
| The quality of the output depends on *today's* prompt: your best prompting on a good day, someone else's on a bad one. | The prompting **is the repo**: intake questions, review method, templates and standing rules, version-controlled, peer-reviewable, identical on every engagement, and regression-tested by an eval harness. |
| The domain knowledge has to be typed in every session: typologies, MW79, SR 11-7, ATL/BTL method, EARS syntax… | Encoded once, cited to sources, and loaded only when relevant, with a register that grows instead of a prompt that gets retyped. |
| One context does everything: it writes the code, reviews its own code, and declares itself done. | **Separation of duties**: reviewers hold no `Write`/`Edit` tools, QA and validation run as separate agents from the build, and a fresh context reviews without the author's bias. |
| Whatever you paste **leaves**: into someone's context window, on their retention terms. | Raw data under `data/raw/` is **kept from the model's file-read tools** (hook + OS deny-list + a CI check); the model works downstream of masking, and code execution needs a human-created consent file. (PoC-grade controls with limits documented in ADR-002, not a sandbox.) |
| The output is a transcript. Six months later an auditor asks "why this threshold?" and the answer is scrolling. | The output is an **evidence pack**: RTM, tuning rationale with dates, finding dispositions, review reports, and a Definition of Done, in `.md` + `.html`, gated by a mechanical check. |
| The discipline lives in your head and leaves with you. | The discipline lives in the harness and survives staff turnover, deadline pressure, and whoever types next. |

None of that requires a better model. It requires the model to arrive inside **controls**, which
is also why the pattern transfers: swap the surveillance domain knowledge for another regulated
domain and the harness (dormancy, gates, segregation, evidence, evals) carries over.

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
The standard ones per language when present (ruff, mypy, bandit, gitleaks, shellcheck and
friends - semgrep and pip-audit are deliberately not used, even if you have them installed,
after repeated corp-proxy hangs from network calls neither could reliably avoid). At
engage-time the team inventories what's actually installed and
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
Granting it is one command, run by you - always with the **absolute project path**, so a
terminal sitting in another directory can't create the marker in the wrong place:

```bash
touch /path/to/your-project/.claude/.exec-consent
```

or type `! touch /path/to/your-project/.claude/.exec-consent` as the first characters of your
Claude Code prompt line (the `!` runs it as your shell command, not the model's - and that
shell is Git Bash on Windows too, so it works everywhere). From a **native Windows terminal**
use PowerShell `ni "C:\path\to\your-project\.claude\.exec-consent" -Force` or cmd
`type nul > "C:\path\to\your-project\.claude\.exec-consent"` instead. Alternatively set
`CST_ALLOW_EXEC=1` in the environment you launch Claude Code from - handy for CI. To revoke,
delete the file (`rm /path/to/your-project/.claude/.exec-consent`); answering "static only"
at intake deletes it for you. The asymmetry is the point: the model may *delete* the marker (fail-safe) but can
never *create* it, so consent is always a human act with a file's worth of evidence. And a
"no" sticks: a declined or not-yet-answered consent is recorded in the engagement's state
file (only the non-granting outcomes are representable there - anything grant-shaped fails
validation), so a resumed or compacted session re-reads your answer instead of asking again.

**Who is Morgan?**
The project manager, and the only "person" you ever need to talk to. Morgan opens every
engagement (the 🎩 at the start of a line means the PM is speaking), asks the intake
questions, decides which specialists the job actually needs and says so out loud before
spawning any, challenges their findings rather than relaying them, and comes back to you at
every gate. Morgan is a persona with teeth: the discipline is re-injected every turn while an
engagement is open, so it survives long sessions. The specialists (Amara, Mateo, Linh, Ravi
and friends) are separate agents Morgan briefs and coordinates; you can meet them with
`/meet-the-team`, but you never have to manage them yourself.

**Are Morgan and the specialists real people?**
No, and the artifacts are built so nobody downstream could think so. Every roster name is
an AI agent, and any document that attributes work to one marks it explicitly: 🤖 plus
"Virtual Surveillance IT" on first mention, with a legend under every sign-off table. An
agent never shares a sign-off or approval line with a human, because only the human grant
carries authority: an auditor reading "Reviewed by Layla" will always also read that Layla
is an AI agent, and your approval always stands on its own line. This is mechanically
checked, not just a convention: the DoD gate flags an unmarked persona attribution
(`AGENT-UNMARKED`) and any line joining an agent and a human (`AGENT-HUMAN-COMBINED`), and
fabricated or wrong-role reviewer names are caught by the roster gate
(`ROSTER-UNKNOWN` / `ROSTER-ROLE-MISMATCH`).

**What's the `VSIT/engagements/` folder that appeared in my project?**
That's the engagement's paper trail - everything the team produces lands there, each document
in both `.md` (source) and `.html` (readable render). Each engagement gets its **own
workspace subfolder**, `VSIT/engagements/<slug>/`, so several engagements can coexist at
independent states; the root holds a generated registry (`ENGAGEMENTS.md`) listing them.
The key files inside a workspace: **`START-HERE.md`** is exactly what it sounds like, the
index to read first - what this engagement is, whether it's finished (⏳ in progress /
⛔ blocked / 🔒 closing / ✅ closed) and what to read in what order.
**`engagement-state.json`** is the machine-readable version of the same truth (status,
outstanding work, decisions, the artifact inventory); START-HERE is generated from it, with
a content hash so a hand-edit is detected - don't hand-edit either. **`engagement-brief.md`**
records what was agreed at the start. Mid-engagement you'll see pass-scoped names like
`review-pass-1.md` and `qa-handover.md` (interim by design). **`delivery-report.md`** and
the **`engagement-summary-*.txt`** email only appear once the close window opens (🔒
closing) - if they're absent, the engagement isn't done, on purpose - and the flip to ✅ is
gate-verified: the close runs the full mechanical check and refuses on any finding. Treat
the folder as the audit trail: it's the evidence behind every claim, so archive it rather
than delete it, and add `VSIT/engagements/` to your `.gitignore` if you don't want it in version
control.

**What is the codebase map?**

The team's memory of YOUR project: `VSIT/shared/map.md` (created at the first close),
a short PM-curated index of durable facts about how your code is built - read at every
engagement open so the team never starts cold, corrected/deprecated at every close, and
mechanically hygiene-checked (size, provenance anchors, staleness, no secrets). Advisory
context only, never instructions (ADR-003 / ADR-007).

**I ran engagements on earlier versions - is my artifacts folder still OK?**
Yes. The layout has evolved (flat folders became per-engagement workspaces, the index
became generated, statuses gained a closing stage), but every older shape keeps working:
old flat packs are checked exactly as before, hand-written indexes from early versions
stay legal, files that were already sitting loose in the folder were exempted once and
stay exempt, and the lifecycle hooks never nag about closed or ancient packs. If you want
a verdict and a tidy-up, two commands do it: `python -m scripts.check_artifacts --fix`
gives you a fix-list (and fixes the mechanical items itself), and
`python -m scripts.engagement_state migrate` moves an old flat engagement into its own
workspace folder. Neither is required - they are offered, not demanded.

**Do I need to learn all the commands?**
No. `/engage` is the front door and routes everything; the rest are shortcuts the team
itself knows how to reach. The one other command worth knowing early is `/engage-light`
(next question).

**When should I use `/engage-light` instead of `/engage`?**
For small, non-regulated jobs where the full framework would cost more than the work: a
utility script, a quick review, an analysis, doc work. You choose it explicitly - Morgan
never quietly downgrades an engagement. It uses a fraction of the tokens of a full
engagement on the same job, because it removes documents and repetition - never checks or
safety. Side by side:

| | `/engage` (standard) | `/engage-light` |
|---|---|---|
| Safety gates (consent, data attestation) | Full | **Identical - never lightened** |
| Requirements | BRD / functional spec / traceability matrix as needed | One-page brief with bullet requirements |
| Team | Right-sized from the full roster, parallel work allowed | 2-3 agents, no parallel fan-outs |
| Review + independent QA on any code | Chosen depth, cycles until clean | One review pass + one QA verification (a fail still loops - it never ships one) |
| Detection rules / scenario logic | In scope, with compliance review | **Refused - auto-upgrades to a standard engagement** |
| Close | Full close: reconciliation sweep, delivery report, summary email, next steps | Quick close: mechanical check, a **short** summary email from Morgan, one next step |
| Evidence tags, truthful blocked states, your sign-off | Standing rules | **Identical** |
| Token usage, same small job | The full framework's | A fraction of it |

If the work grows past light mid-engagement (detection logic appears, a regulated obligation
enters), Morgan says so and upgrades the same engagement to standard - it never restarts and
never quietly stays light.

**What if my session dies mid-engagement?**
Nothing is lost. The engagement's state lives in a machine-readable file on disk (updated
with every artifact write), with a human-readable START-HERE generated from it. A brand-new
session reads those, picks up the outstanding list and carries on, this has been proven live,
twice in one day, including once after the session hit its budget cap mid-delivery. Since
0.33.0 the resume is disk-first end to end: which engagement was active is recorded on disk
(`VSIT/engagements/.active-engagement.json`), your intake answers (go-ahead, fix-cycle, the data
attestation) persist as decisions, the phase and run-mode probe are cached, and a "no" to
execution consent is recorded so a resumed session never re-asks its way into a yes.

**Can I trust it with real data?**
Short version: don't paste raw data, and it will try hard to stop you. `data/raw/` is
hard-blocked from the model by an always-on hook, everything else runs on your attestation
that it's masked or synthetic, and `/prepare-data` exists to get you there. Pseudonymised
still counts as personal data, so prefer fully synthetic. See
[Handling real data](../README.md#-handling-real-data) for the long version.

⚠️ **One caveat on `/prepare-data` itself**: the masking pipeline behind it is a
**placeholder implementation** (a proof-of-concept showing the shape of the workflow, with a
[roadmap](internal/prepare-data-roadmap.md) of what a real one needs). Do not rely on it as your
control for de-identifying production data - if the stakes are real, use your organisation's
approved masking tooling, or fully synthetic data, and treat `/prepare-data` as a demo of
where that step slots into the flow.

---

Next: [Overview](OVERVIEW.md) · [Demos](demos/README.md) · [Glossary](glossary.md) · [README](../README.md)

## Startup feels slow in a project with lots of old engagements - can I speed it up?

Yes, two ways (0.33.2):

1. **Archive them.** Say "archive the old engagements" to Morgan (or run
   `python -m scripts.engagement_state archive --all-closed` yourself). That drops a
   `.archive` marker file into each closed pack - nothing moves, links keep working,
   and every scanner (DoD checker, end-of-turn gate, registry, status line, resume
   menu) skips the folder from then on. Works on any directory under `VSIT/engagements/`,
   not just engagement packs - `touch VSIT/engagements/legacy-stuff/.archive` excludes a
   folder by hand. `unarchive <slug>` brings one back.
2. **Nothing at all.** Engagements closed on 0.33.2+ store a fingerprint at close;
   unchanged closed packs are skipped automatically. Packs closed on older versions
   keep full-scanning until archived (the checker nudges you when several are in
   that state).

Archiving an *open* engagement is refused - it would silence the close gate. A
hand-touched marker on an open pack shows as an `ARCHIVED-OPEN` warning, never a
silent skip.
