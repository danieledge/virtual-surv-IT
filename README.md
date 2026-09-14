<a id="readme-top"></a>

# Virtual Surv-IT

![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)
![Version 0.38.0](https://img.shields.io/badge/version-0.38.0-blue)
![Tests 3200+ passing](https://img.shields.io/badge/tests-3200%2B%20passing-brightgreen)
![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2)
![Status: proof of concept](https://img.shields.io/badge/status-proof%20of%20concept-orange)
[![Quick start: one-page PDF](https://img.shields.io/badge/Quick%20start-one--page%20PDF-important)](docs/quick-start.pdf)

<details><summary><b>What changed recently</b> (0.38.0 highlights; full history in the changelog)</summary>

<table>
<tr><td>

🏷️ **Current version: 0.38.0** (2026-09-14) · 📖 [0.38.0 working notes](docs/releases/0.38.0.md) · 📜 [Full changelog](CHANGELOG.md)

**0.38.0 in one paragraph.** The guard changes of the 2026-09-13 framework review are applied and
ship under a new number (the version is what `claude plugin update` keys on; an unchanged number
leaves every installed copy stale, which the installer now detects and refreshes). The plugin-mode
open, the way the team is really installed, passed a live eval and its run is kept as the first
golden replay and frozen as the shipped sample engagement (`virt-surv try --replay`). CI is green
on Linux and Windows. One eval case is still failing and the baseline says so.

**Biggest features of the 0.34 to 0.37 cycle: the front door became a launcher, and the token bill got engineered.**
- 🛡️ **The safety gates were off in every new project, and now are not** (unreleased). The
  `VSIT/` layout became the default for new projects on 2026-08-28 and the three guard hooks
  were never told: they looked for the acting-session stamp under the old `artifacts/` path
  only. So in any project created since, the execution gate never armed, an engaged session
  could run the code under review with no human consent, settings were not write-protected,
  and the four reviewers were blocked from writing their own findings pack and fell back to
  prose. This repo is on the legacy layout, which is exactly why nothing surfaced it, and no
  guard test carried a new-layout path. Found by an adversarial review, fixed in both layouts,
  and the tests now cover both.
- 🚪 **`virt-surv go` is the front door** (0.34.0). The resume-or-new decision, environment
  probe and interpreter discovery are computed *outside* the LLM and pre-encoded into the
  session's first prompt - no more burning turns rediscovering the machine. Engagements can
  now be picked up straight from a Jira ticket (beta), delivered back to the ticket at close.
- ⚡ **Corporate-box performance, measured.** A persistent guard daemon takes safety-hook
  response from ~307ms cold start to ~12.6ms; one dispatcher process replaces five per Bash
  call; a Git Bash fix cut shell-snapshot startup ~15x. Built against live reports from
  locked-down Windows estates.
- 📊 **The team can now interrogate data and documents, not just code** (0.37.0). Three
  deterministic tools: temporal profiling of alert data (**calendar-aware** gaps, freshness,
  cadence - a naive gap check flags every weekend and buries the real outage), FIBO-grounded
  column meanings, and a token-budgeted documentation inventory. The first two emit
  **aggregates only, never a record**, which makes them *safer* than the alternative of an
  agent reading rows into context. `.eml` and `.msg` mail finally convert too - comms
  surveillance is a pillar of this team, and `.msg` was being skipped silently.
- ⏱️ **A performance pass that began by finding a hang** (0.37.0). The suite was not slow, it
  was stuck - on an interactive screen waiting for keys a test harness never sends. Then the
  measured wins: state mutations 0.38s → 0.10s, date parsing 29x, the codebase skeleton 15s →
  6.5s, and both every-prompt hooks now share the persistent guard daemon, which is on by
  default. Every figure here was measured before and after, not estimated.
- 🤖 **Autonomy grew up** (0.36-0.37). Unattended runs are decided **per ticket, not per
  project**, reachable from a typed request as well as a Jira, bounded by a spend ceiling
  whose degrade ladder is answered up front - because an unattended run has nobody to ask.
  Its Definition-of-Done gates turned out to be **dead code**, caught by an adversarial audit
  and by writing the first test that drove the real entry point rather than the gate.
- ⚡ **The probe prefetch actually fires now** (0.35.1). The hook that serves a pre-computed
  engage probe read the submitted prompt from a field name Claude Code has never sent, so it
  had never once fired: every `/engage` silently paid the full in-session probe, which is
  minutes on a corp box. Found by following one user report about a slow open; the repo's own
  tests had been feeding the same wrong field, so they agreed with the bug rather than
  catching it. Two neighbouring cache bugs fell out of the same trace.
- 💰 **Token economics overhauled against a measured audit** (0.35.0). A cold engagement open
  now costs ~28% fewer standing tokens: the operating guide split into an open-core with
  detail loaded on route, the probe bootstrap moved to its miss path, tool reports compacted
  to what prompts actually consume, and review context forwarded once instead of re-derived
  per agent. A prompt-budget check in CI fails the build if any prompt file quietly regrows,
  and every eval run now records per-agent cost attribution.
- 🧾 **Review flows tightened end to end** (0.34.0-0.35.0): one consolidated reviewer pass
  runs all lenses (security is a lens, never a second fan-out), Quick reviews run in-session
  from a ~1k-token recipe, and the Level 0-3 cost ladder (Answer/Quick/Deep/Audit) is the
  stated cost model - independence bought deliberately, never by habit.

</td></tr>
</table>
</details>

**Virtual Surv-IT is a virtual engineering team for the software that catches financial crime and
market abuse.** A project manager (Morgan) and **13 specialist AI agents** (plus three in-line SME
knowledge packs) run it inside
[Claude Code](https://claude.com/claude-code).

Banks and trading firms spot money laundering and market manipulation with software: detection
rules, data pipelines, threshold tuning, test evidence, and the audit paperwork a regulator can
still question years later. That software is slow to build, risky to change, and heavy on
documentation. Virtual Surv-IT is a proof of concept exploring how agentic AI and AI agents can
help with the engineering challenges of this domain: the work is split across a team of
specialists, each doing one job, with **every piece independently checked by a different agent**
before it counts as done.

The team builds the tooling; a person signs off every step.

![The Engagement Machine - one engagement end to end: a single front door (Morgan the PM plans the job and sets the headcount), specialists working in their own sealed workspaces, every hand-off a written artifact pinned to a shared board, a delivery pack that grows as it passes spec, build, independent QA and review, guards that keep real data and secrets out and let no code run without a human turning the key, a done-gate checklist that cannot be skipped, and a human signature before anything ships](docs/assets/engagement-machine.png)

> ⚗️ **Proof of concept, under active development.** An experiment, not production or regulatory
> tooling. It is pre-1.0 and changes often; behaviour and interfaces may break between updates, and
> it can get things wrong. **Review everything it produces; never rely on it as a control or as
> regulatory advice.**

> 🚀 **In one minute.** Virtual Surv-IT is a Claude Code plugin: Morgan, a PM agent, and 13 specialist agents that build,
> review and hand over surveillance tooling, every step independently checked by a different agent before it counts as done.
> **Three commands:** `/engage` (the front door for any job), `/demo` (a narrated engagement on synthetic data), `/team` (meet the roster).
> **Three guarantees:** the project's raw-data folder never reaches the model ([always-on guard](#-the-safety-hooks)); the code under
> review never runs without a consent marker only a human can create; nothing is "done" until the mechanical Definition-of-Done gate says so.
> **Install:** `git clone https://github.com/danieledge/virtual-surv-IT.git && cd virtual-surv-IT && python install_helper.py`, then enable
> the plugin in each project that uses it (`/plugin`). Needs Python 3.9+ and, on Windows, Git Bash or WSL. Full steps: [Quick start](#-quick-start).
> **See a finished engagement in one minute, no tokens:** `python scripts/try_engagement.py` (or `virt-surv try`) closes a synthetic review in a throwaway project and opens its evidence room.
> **Or read a real one:** `virt-surv try --replay` (in a session, `/demo replay`) opens the shipped sample engagement, a real run the team did on synthetic data, frozen under [`examples/engagements/`](examples/README.md) with its START-HERE page, state, findings, summary email and evidence room.

**New to AI agents?** Start with [`docs/OVERVIEW.md`](docs/OVERVIEW.md), a plain-English tour.
**See it work:** the [review demo](docs/demos/review-demo.md) transcript, and a full-lifecycle
[eval run](docs/demos/transcripts/eval-full-lifecycle-20260801.md) captured end to end.

> ⏱️ **Try it in 60 seconds.** Type **`/demo`** - from the repo opened as a project, or
> `/compliance-surveillance-team:demo` from a plugin install - and Morgan runs a real engagement
> end-to-end on safe synthetic data, narrating every decision. The Review flavour is light on
> tokens; a full guided Build delivery is a real 9-agent run and costs roughly **$4-8 in API
> tokens** (the measured number in [Token usage](#-token-usage--optimisation)). No tokens to
> spare? A review run is captured verbatim in
> [`docs/demos/review-demo.md`](docs/demos/review-demo.md) - reading it is free.

---

**📑 Jump to** - [🤔 Why](#-why-virtual-surv-it) · [✨ Features](#-features) · [🚀 Quick start](#-quick-start) · [👥 Meet the team](#-meet-the-team) · [🤖 Using them](#-using-them) · [📓 Worked example](#-worked-example) · [🧭 Core principles](#-core-principles) · [🔍 Tooling](#-code-review-tooling) · [🧪 Self-test](#-self-test-eval-harness) · [🪝 Safety hooks](#-the-safety-hooks) · [🔒 Real-data handling](#-handling-real-data) · [📁 Layout](#-layout) · [🗂️ Scripts](docs/scripts-reference.md) · [🔧 Config](docs/INTEGRATIONS.md) · [💰 Token usage](docs/token-usage.md) · [🗺️ Roadmap](docs/roadmap.md) · [📖 Docs](#-documentation) · [⚠️ Known issues](#known-issues) · [🤝 Contributing](#-contributing) · [📚 Built on](#-built-on--acknowledgements) · [📄 License](#-license)

---

📖 **Acronym glossary** - the domain and spec shorthand used throughout: [`docs/glossary.md`](docs/glossary.md)

## 🤔 Why Virtual Surv-IT?

### If you've worked in surveillance IT, you know these moments

This project comes out of working in this domain, and out of a handful of moments most
surveillance technologists will recognise on sight:

- **The quiet discovery that something has been broken for years.** The feed that was never
  switched on. The venue migration that silently dropped a slice of order flow. The symbology
  mapping nobody re-tested after the upgrade. Surveillance fails *silently*: a working system
  and a broken one both look like "no alerts today", and that sits in your stomach precisely
  because nobody can say how long it has been true. The version that became public is
  [FCA Market Watch 79](https://www.fca.org.uk/publications/newsletters/market-watch-79) (May
  2024): a news feed never activated, so the insider-dealing scenario fired **zero alerts for
  over three years**. Every practitioner reading that felt the same thing: *that could have
  been us.* The countermeasure, independently assuring that every feed, instrument and threshold
  is actually working, is staffing-intensive, so it is exactly what gets squeezed.
- **The threshold nobody can explain.** Set years ago by a contractor who has since left, the
  rationale lost with their inbox. Everyone is afraid to touch it; the regulator's review is
  asking why it's 3.0 and not 2.5, and the answer on file is an email chain. In this domain the
  evidence *is* the product: the documented rationale, the tuning date, the trail from an alert
  back to the rule it serves, all expected to stand up **years later**. Producing that evidence
  (the specs, the traceability, the test packs, the reporting) is what quietly consumes your
  scarce experts.
- **The queue behind one "simple" change.** Tighten a spoofing threshold and you have touched
  regulatory interpretation, requirements, detection engineering, statistics, model risk, QA and
  audit evidence. The people who hold more than two of those disciplines are rare, everything
  waits on them, and the backlog grows while they spend their days drafting and formatting
  documents instead of deciding things.
- **The data you can't just paste anywhere.** Transactions, orders and communications carry
  personal data, and potentially inside information: the one dataset in the firm you cannot
  experiment with. Any AI approach has to be *structurally* incapable of leaking it, not just
  told to be careful.

### The hypothesis this project explores: AI can genuinely help here

Those four moments turn out to match what large language models are genuinely good at, and that
match is the **hypothesis Virtual Surv-IT was built to test**, not an assumption it starts from:

- Most of the work is **translation between formalisms**: regulation → requirement → spec →
  code → test → evidence. Each hop is language work with a checkable output, which is what an
  LLM does well, and each hop is where surveillance change is slowest today.
- The **evidenced 80% is exactly the automatable 80%**: specs, RTMs, tuning packs, QA
  evidence, handover docs and MI are structured documents derived from decisions, so an LLM can
  draft them consistently, in minutes, every time, while the *decisions* stay human.
- **Consistency is something the domain actively wants**: a regulator comparing two tuning
  packs from two quarters benefits from them being structurally identical. Humans drift;
  templates and agents don't.
- The **failure modes of AI are manageable with the domain's own tools**: hallucinated
  citations → retrieval from a verified register; unchecked output → independent review;
  over-claiming → evidence tagging; data exposure → hard architectural blocks. The domain has
  spent decades building controls for fallible humans, and those controls transfer.

The project's demos, worked example and [eval harness](#-self-test-eval-harness) are the
evidence gathered so far: an end-to-end build with measured calibration on synthetic data,
reviews that catch seeded defects without inflating clean code, and safety guards that hold
under test (and have caught their own authors). Where the hypothesis is *not* yet proven, the
repo says so; see the evidence basis in [`docs/house-rules.md`](docs/house-rules.md) and the
[known issues](#known-issues).

### Why a specialist *team* with independent review, not one assistant

"AI can help" is not the same as "one AI assistant can help". A single general-purpose
assistant does each of those disciplines shallowly, with nobody checking its work, and its
output is a chat transcript rather than an audit trail. Virtual Surv-IT splits the work across
specialists and builds in **independent review**:

- **Business analysis**: turning a regulatory obligation into a buildable, unambiguous spec.
- **Surveillance rule development**: deterministic, tested detection logic.
- **Data engineering**: pipelines, ETL (extract, transform, load), transformation and utility scripts.
- **Data analysis and threshold tuning**: false-positive analysis, ATL/BTL calibration, MI.
- **ML / AI detection**, with *independent* model validation.
- **QA**: independent test design and evidence (it does not mark its own homework).
- **Code, performance and compliance review**: quality, scalability and audit-readiness.
- **Data-quality and coverage assurance**: the missing feed that means abuse goes undetected.
- **Technical documentation**: handover a real developer can build, run and maintain from.

It also maps the domain's own control expectations onto the AI itself: segregation of duties
(advisors and reviewers hold no edit tools, so they can't alter what they assess), an audit trail
by construction (the RTM, source-verified citations, evidenced findings), data safety as
architecture rather than policy (raw data blocked from the model, execution human-gated), and the
economics of it (the evidenced work runs in minutes for API-token cost, while humans keep every
judgement call). The full mechanics, one row per principle with what actually enforces
it: [Core principles](#-core-principles).

The result is an engineering workflow that produces more **consistent, auditable and
maintainable** output than one generalist assistant, because the work is specialised,
**independently reviewed**, and **right-sized** to each task (see below). *(All of it within
the proof-of-concept framing above: a demonstration of the architecture, for real engineers
and reviewers to build on, not accredited regulatory tooling.)*

**Already have ChatGPT or Copilot?** The chat-window-vs-this comparison moved to the FAQ:
[`docs/FAQ.md`](docs/FAQ.md).

<sub>[↑ Back to top](#readme-top)</sub>

## ✨ Features

What the team gives you today, each row tied to where the claim is enforced or demonstrated:

| Capability | What you concretely get | Where to see it |
|---|---|---|
| A real engineering team, right-sized | Morgan (PM) + 13 specialist subagents, with domain typology advice as three in-line knowledge packs ([`docs/sme/`](docs/sme/README.md), zero spawn cost); a typical task fires only 2-5 agents, and the PM states the intended count at the gate. | [`docs/agent-design.md`](docs/agent-design.md) · [Meet the team](#-meet-the-team) |
| Independent review by construction | Advisors and reviewers hold no `Write`/`Edit` tools; QA and validation run as separate agents from the build. More than rules: pipelines/ETL, scripts, ML, reviews and docs all route to their own specialist. | Tool grants in [`.claude/agents/`](.claude/agents/), pinned by [`tests/test_docs_consistency.py`](tests/test_docs_consistency.py) · routing table in [`docs/team-operating-guide.md`](docs/team-operating-guide.md) |
| Stateful, crash-safe engagement lifecycle | Per-engagement `VSIT/engagements/<slug>/` workspaces, a machine-readable state file (⏳ · ⛔ · 🔒 closing · ✅), a close that runs the mechanical gate and refuses on findings, and disk-first resume of state, intake answers and consent outcome. | ADR-008 · ADR-006 · [`docs/releases/0.33.md`](docs/releases/0.33.md) |
| Safety guards: always-on data wall, session-scoped gates | Raw data under `data/raw/` blocked from the model in EVERY session; the execution gate and settings write-protection arm only in sessions that invoked the team (2026-08-17 - a dormant session is plain Claude Code), while the consent marker, hook files and git execution config stay write-protected everywhere. | [`docs/safety-model.md`](docs/safety-model.md) |
| Document conversion front door | Excel/CSV/PDF/DOCX read via the vendored converter - no pip needed - with a JSON evidence report every run; a PreToolUse hook redirects binary-document reads to it. | [`docs/house-rules.md`](docs/house-rules.md) · [`scripts/convert_file.py`](scripts/convert_file.py) · [`scripts/document_input_redirect.py`](scripts/document_input_redirect.py) |
| A real review subsystem | Context-routed lenses, the standard analysers per language, schema-validated findings packs rendered to one canonical layout, and a build fingerprint tying the reviewed code to the shipped artifact. | [`docs/code-review-method.md`](docs/code-review-method.md) · [`docs/review/`](docs/review/) · the [review demo](docs/demos/review-demo.md) |
| Independent QA + a mechanical DoD gate | A close only counts when `check_artifacts` passes - finding codes like `STALE-INDEX`, `FINAL-BEFORE-CLOSE`, `ROSTER-UNKNOWN` catch the failure modes that actually happened live. Iteration history stays visible append-only (journey strip, QA cycles). | [`docs/DEFINITION-OF-DONE.md`](docs/DEFINITION-OF-DONE.md) · [`scripts/check_artifacts.py`](scripts/check_artifacts.py) |
| Engagement memory | A per-project **codebase map**: bounded, PM-curated, SHA-anchored, hygiene-checked mechanically, advisory-only - repeat engagements start warm. | ADR-003 · ADR-007 |
| Company extensions | Additive per-project standing instructions, close actions, an analyser registry and named integrations - never a safety waiver, and eval-tested. | ADR-009 · [`docs/EXTENDING.md`](docs/EXTENDING.md) |
| Self-tested quality | 9 rubrics + 52 golden cases with a deterministic scorer in CI, and a mechanical dev→main release gate that fails a promotion with no eval baseline. | [`evals/README.md`](evals/README.md) · [`scripts/release_gate.py`](scripts/release_gate.py) · [Self-test](#-self-test-eval-harness) |
| Cost visibility | Measured per-run token numbers, and a local observability page: engagement inventory, DoD gate result, map hygiene, consent highlight, measured token cost (`python -m scripts.dashboard`). | [Token usage](#-token-usage--optimisation) · [`scripts/dashboard.py`](scripts/dashboard.py) |
| Console & UX discipline | Progress in the native task list (TodoWrite), every clarification via the question tool, a statusline showing dormant-vs-engaged, and a clean console with detail in artifacts. | [`docs/team-operating-guide.md`](docs/team-operating-guide.md) · [`scripts/statusline.sh`](scripts/statusline.sh) |
| Explicit AI identity | Every roster name in an artifact is marked 🤖 + "Virtual Surveillance IT"; an agent never shares a sign-off line with a human - mechanically checked. | [FAQ](docs/FAQ.md) · `AGENT-UNMARKED` / `AGENT-HUMAN-COMBINED` in [`scripts/check_artifacts.py`](scripts/check_artifacts.py) |
| Claude Code native, dormant by default | A plugin with per-project enablement; skills cost ~nothing until `/engage`; a guided installer walks the whole flow (`python install_helper.py`). | [Claude Code features](#-claude-code-features-this-team-is-built-on) · [Quick start](#-quick-start) |
| Documentation generation | Every deliverable in `.md` + `.html`, plus a close-only summary email signed by Morgan. | [`docs/WAYS-OF-WORKING.md`](docs/WAYS-OF-WORKING.md) · [`docs/templates/`](docs/templates/) |

<sub>[↑ Back to top](#readme-top)</sub>

## 🚀 Quick start

### Prerequisites

- **Python 3.9 or newer on PATH** (`python`, `python3` or the `py` launcher). The safety guards run on it; a host with no
  Python leaves them inert, so the installer's preflight checks for one.
- **A POSIX `sh` for hooks.** Present on Linux and macOS; on Windows use **Git Bash** (ships with Git for Windows) or WSL.
  Claude Code runs every hook command through `sh`.
- **Claude Code** with plugin support, and **git**.
- Optional: the review analysers the installer fetches; reviews run without them and say what they could not measure.
<table>
<tr><td>

### Three steps

**1. Install** (from a terminal, not inside Claude Code):
```bash
git clone https://github.com/danieledge/virtual-surv-IT.git
cd virtual-surv-IT
python install_helper.py
```
The helper checks the prerequisites, picks a release channel, clones or safely updates, and runs
the real `claude plugin marketplace add` / `claude plugin install compliance-surveillance-team@virtual-surv-it`
commands. `--yes` for unattended defaults; `--no-downloads` (or `CST_NO_DOWNLOADS=1`) to fetch no
analyser binaries at all.

**2. Enable it per project.** From the project you want the team in, run `/plugin` and enable
**compliance-surveillance-team** *for this project*, or add to that project's `.claude/settings.json`:
```json
{ "enabledPlugins": { "compliance-surveillance-team@virtual-surv-it": true } }
```
Not at user scope: every enabled plugin's agent roster loads into every session on the machine.

**3. Start.** Restart Claude Code in that project and type `/compliance-surveillance-team:demo` for a
narrated engagement on synthetic data, or `/compliance-surveillance-team:engage <what you need>`,
then reply in plain English; Morgan stays in role for the session. Recommended launch:
`virt-surv go` from the project folder (the helper's alias step sets it up).

One-page reference: [`docs/quick-start.md`](docs/quick-start.md), also rendered as
[HTML](docs/quick-start.html) and [PDF](docs/quick-start.pdf).

<details><summary><b>Why per-project, not enabled everywhere</b></summary>

> **Why per-project instead of "enabled everywhere"?** Claude Code loads every enabled plugin's
> **agent descriptions into every session's context** so it can route work to them; there is no
> lazy-load mechanism for agents. A user-scope enable therefore taxes *every* project on the
> machine (~1.2k tokens per session, every session) for a team most of them never summon, the
> opposite of this repo's **dormant-by-default** principle. The team's *skills* are already free
> everywhere (they set `disable-model-invocation: true`, so their descriptions never load and the
> commands stay typeable); the agent roster is the irreducible cost, so it's scoped to the
> projects that actually use it. (The 2026-07-01 setup audit measured the old always-on posture
> at ~2.7k tokens per session per project, hence this step.)

</details>

<details><summary><b>What the helper does, step by step</b></summary>

The helper walks the whole flow: preflight (git / claude CLI / network), a persisted
release-channel pick (**`main`** is the **stable** line; bigger, in-progress changes land first
on **`dev`** and are promoted to `main` at a release), clone or safe update (it refuses to
reset a dirty tree), optional `pip install -r requirements-dev.txt`, then the real
`claude plugin marketplace add` / `claude plugin install compliance-surveillance-team@virtual-surv-it`
commands - and it closes by listing what stays manual (per-project enablement below, the
restart; hooks ship pre-wired). Re-runnable; `install`/`update` auto-detect
from `~/.config/virt-surv-it/installer.json`; `--yes` for non-interactive defaults.

</details>

<details><summary><b>Fewer permission prompts (optional)</b></summary>

**Fewer permission prompts (optional).** Without pre-approval, every analyser run and
helper-script call prompts you, and each "don't ask again" saves the *literal command string*
as a rule (on Windows that accumulates mixed-path, mixed-quote rules the validator then flags
as invalid). The helper can add the recommended clean wildcard allow-list to a chosen project
for you: `python install_helper.py --permissions <project-dir>` - opt-in, add-only, and it
backs up the settings file first. (`/permissions` shows every rule and which file it came
from. Permission rules are Claude Code's prompting layer; the team's execution *gate* is
separate and stays human-consent-only.)

</details>

<details><summary><b>Fewer timeouts on slow networks or proxies (optional)</b></summary>

**Fewer timeouts on slow networks/proxies (optional).** `python install_helper.py --env-tuning
<project-dir>` upserts a curated set of Claude Code env vars into the project's
`.claude/settings.json` - raised API/stream-idle timeouts, retry-watchdog, capped
single-tool output sizes, and the **1-hour prompt-cache TTL** (`ENABLE_PROMPT_CACHING_1H=1` -
on API-key/cloud billing the default 5-minute TTL re-pays the cold prefix after every
stop-start gap; see [Token usage](#-token-usage--optimisation)). `virt-surv go` also
propagates newly recommended keys to projects that already opted in, add-only, telling you
when it does. Opt-in, project-level only (Claude Code's settings-file `env` block
already wins over the shell on Linux and PowerShell alike), backs up the settings file first;
any other env var already there, or set with a different value than recommended, is corrected
in place, and everything unrelated is left untouched.

</details>

<details><summary><b>Verify it works: the self-test (optional)</b></summary>

**Verify it actually works (optional).** `python install_helper.py --selftest` runs a throwaway
synthetic "review this code" engagement - real guard hooks, an analyser proven to *detect* a
planted issue (not just stay quiet on clean input), and the full engagement-state lifecycle
(init → findings → render → the close-gate correctly refusing an incomplete close → archive) -
no LLM/Claude Code invocation, no network. On any failure it writes one debug bundle file
(`virt-surv-selftest-<timestamp>.txt`) with full detail per step, meant to be pasted or
attached whole instead of a screenshot. Also reachable via Diagnostics → "Self-test" in the
interactive menu, and folded into `--check-env`'s own comprehensive report - both end with a
compact pass/fail summary.

</details>

<details><summary><b>Launch with virt-surv go, from anywhere (recommended)</b></summary>

**Run it from anywhere - and launch with `virt-surv go` (recommended).** `python
install_helper.py setup-alias` offers to add a `virt-surv` alias/function to whichever shell
config actually exists on your machine (`~/.bashrc`, `~/.zshrc`, or a PowerShell profile on
Windows) - opt-in, previewed before writing, never duplicated on a re-run, and it upgrades
itself in place on later runs (old definitions are removed, not stacked). Once set up,
**`virt-surv go` from your project folder is the recommended way to start every session**: it
shows the project's effective team settings in one table, pre-warms the analyser and probe
caches so the first `/engage` opens with zero extra tool calls, lets you pick
**resume-or-new** with arrow keys or hotkeys before Claude Code even starts (the choice
arrives pre-seeded as the first prompt - no model round-trip spent deciding), and gives
inline access to a settings editor (`c`) and engagement archiving (`a`). **`virt-surv engage`
is the same launch command** (2026-08-19: it used to mean project setup, which read as the
opposite of `/engage` in a session). The other subcommands cover setup and upkeep:
`virt-surv configure` (on a project that isn't set up yet: enable + permissions + preferences
+ Morgan's model + an analyser-availability cache refresh, one guided pass, asks before each
choice - on an already-configured project it opens the same settings editor `go`'s `c` shows),
`virt-surv onboard` (that same setup pass with every recommended default applied
automatically, zero prompts), and `virt-surv archive` /
`virt-surv list-engagements` (bridges to `scripts/engagement_state.py`, scoped to that
folder) - no need to remember the clone's full path or hunt through the menu.

</details>

<details><summary><b>Invoking the commands, run modes and the data guard</b></summary>

**3. Restart Claude Code and launch. The recommended way is `virt-surv go`** (set up the
alias in the optional step above) - from your project folder it shows the team settings,
warms the caches, and asks resume-or-new before the session starts, then launches Claude
Code with your choice pre-seeded. Without the alias, start `claude` yourself from the
enabled project and **summon the team** (commands are namespaced):
```
/compliance-surveillance-team:engage
```
…and likewise `…:deep-review`, `…:audit-review`, `…:handover`, etc.

**Verify:** in the project, run `/plugin`; **compliance-surveillance-team** should show as
enabled for that project. *(One session only, any directory?
`claude --plugin-dir /path/to/virtual-surv-IT` loads it temporarily, not saved.)*

You get the 13 agents, the SME knowledge packs, the workflow commands and all three safety hooks in every **enabled**
project. Then just **talk to the PM**. Describe whatever you've got:

```
/compliance-surveillance-team:engage I need to detect wash trades in our equities flow
/compliance-surveillance-team:engage here's a PowerShell script - would it survive an audit?
/compliance-surveillance-team:engage build this from the attached FSD
```

> **You only invoke `engage` once**, to kick off a piece of work. After that, just reply in plain
> English ("yes, go ahead", "add a false-positive test", "now do the handover"); Morgan stays in
> role for the whole session. Invoke it again only to start a new, separate piece of work, or use a
> focused command (`…:audit-review`, `…:handover`, …) to jump straight to a specific workflow.

> **Everything works from any project: the team detects its own run mode.** At engage, Morgan
> checks whether it's running repo-as-project or as an installed plugin, states the mode in the
> opening banner, and resolves the helper scripts accordingly (the plugin's bundled copies run
> by path from a foreign project, the `.md`→`.html` render included). You don't need to
> remember any of this. Two things still want the repo opened as the project: the **masking
> pipeline** needs your project to hold its own `config/masking-schema.yaml` + `MASKING_KEY`
> (Morgan offers to set that up), and `/demo`'s Build flavour + `/run-evals` use the repo's own
> test suite and golden cases.

> **Data-safety guard is portable, with one caveat.** It's a hook, so it receives
> `CLAUDE_PROJECT_DIR` and protects **your project's** `data/raw/` (not the plugin's) wherever the
> plugin is installed. But a plugin can carry hooks, **not** a `permissions.deny` list, so a plugin
> install ships the hook alone, and installers should recreate the OS-level backstop by copying the
> `Read`/`Grep`/`Glob` `data/raw/**` deny entries from this repo's `.claude/settings.json` into
> their own project's (see [`docs/house-rules.md`](docs/house-rules.md)). The hook launcher probes
> `python3` → `python` → `py`; on a host with no Python at all the guards are inert, which is
> exactly why that deny backstop matters.

> Don't have Claude Code yet? Install it from <https://claude.com/claude-code>.

</details>

<details>
<summary>⌨️ <b>Manual commands</b> (if you cannot run the helper)</summary>

The helper only wraps these; type them **in Claude Code yourself** - `/plugin …` is an
interactive command, and if you *ask the assistant* to "install the plugin" it may claim
success without anything happening. (First remove any earlier hand-copy like
`~/.claude/skills/…`; it conflicts.)

```
/plugin marketplace add danieledge/virtual-surv-IT      # or a local clone path (for dev: git checkout dev first)
/plugin install compliance-surveillance-team@virtual-surv-it
```

</details>

<details>
<summary>📂 <b>Developer / maintainer mode: open the repo as the project</b> - a run mode, not an install path; needed for <code>/demo</code>'s Build flavour, <code>/run-evals</code> and the worked example</summary>

Project-scoped skills and agents **auto-load**, nothing to install, and the bundled scripts
(`/demo`, the worked example, the masking pipeline, the `.md→.html` render) all work out of the box:

```bash
git clone https://github.com/danieledge/virtual-surv-IT.git
cd virtual-surv-IT     # launch Claude FROM the repo root (discovery doesn't walk up dirs)
claude
```

Then run `/help`; you should see `/engage`, `/deep-review`, `/audit-review`, … New here? Type
**`/demo`** to watch Morgan run a full engagement end-to-end on safe synthetic data, or
**`/meet-the-team`** for introductions; then `/engage` to start. (Also
`pip install -r requirements-dev.txt` for the worked example, tests and the `.md→.html` render.)
Here the commands are **not** namespaced, just `/engage`, `/demo`, etc.

> ⚠️ **Don't copy the repo into `~/.claude/skills/`.** The repo's skills live at
> `.claude/skills/<name>/SKILL.md`, so copying the whole folder mis-nests them and they won't
> load. Use the plugin install (above) or this repo-as-project mode.

This mode is for working **on** the team (or running its repo-bound demos), not the everyday
install path for users - that's the helper above.

</details>

## 👥 Meet the team

Morgan (PM) and 13 specialists: Amara (business analyst), Mateo (rules developer), Ana (data analyst),
Theo (tuning analyst), Mei (ML engineer), Kenji (platform engineer), Linh (QA), Viktor (model validator),
Ravi (code reviewer), Thabo (performance reviewer), Layla (compliance reviewer), Yuki (data-quality reviewer)
and Pip (review scorer). Builders write; reviewers advise and can only write their own findings pack.
Domain typology advice comes from the three `docs/sme/` knowledge packs, read in-line. Who does what, why each
agent has its model tier and tool grants, and the roster table with the portrait: [`docs/team.md`](docs/team.md);
the canonical routing table: [`docs/team-operating-guide.md`](docs/team-operating-guide.md). Type `/team` to meet them.

## 🤖 Using them

It's one **dynamic, agile delivery team** with a single front door: the **PM, "Morgan"**,
warm, plain-speaking, can-do but realistic. Throw it a problem, code to review, or
requirements to build, and it clarifies, lets you pick the deliverables, then orchestrates
the specialists.

```
/engage <a problem, code to review, or a set of requirements>
```

> 🛑 **Dormant by default**: a normal `claude` session is standard Claude Code until you type
> `/engage` (or another team command).
> 🛡️ **Data safety always on**: raw data under `data/raw/` is **hard-blocked** from the model;
> anything else carries **your attestation** it's masked or synthetic ([details](#-handling-real-data)).

**What Morgan cannot do**, stated as plainly as the capabilities above:

- **Cannot grant execution consent.** That marker exists only if a human creates it; Morgan hands
  over the exact command to run, never writes it (CLAUDE.md §7).
- **Cannot read `data/raw/`.** The read-guard hook blocks any read, search or command that
  resolves into that folder, regardless of what the task seems to need.
- **Cannot edit the safety hooks, `settings.json`, or its own consent marker.** The consent-write
  gate blocks those writes on both the Write/Edit and Bash channels.
- **Cannot declare an engagement done.** The Definition-of-Done gate runs a mechanical checklist
  at close and refuses on any finding; "done" is what the tooling verifies, not what Morgan says.
- **Cannot let an advisory agent touch code.** Reviewers cannot mutate the code under review:
  the five pack-writing reviewers hold Write/Edit scoped (mechanically enforced) to each one's
  own findings-pack file and nothing else; a fix routes back through Morgan to a builder.
- **Cannot ship code without independent QA.** If execution consent is withheld, the close stays
  marked partial and says so; it is never silently upgraded to a pass.

Full detail: [The safety hooks](#-the-safety-hooks) · [Handling real data](#-handling-real-data).

The PM **asks clarifying questions** (batched into one screen, and it waits for your answers -
it won't guess scope, jurisdiction, data or success criteria), packages everything into **one
consolidated Delivery Report by default** (standalone documentary artifacts - BRD, FSD, ADRs,
RTM, audit pack - on request), summarises everything in an Engagement Brief,
**states how many agents it intends to use and why**, then oversees delivery and **hands back each
deliverable in both `.md` and `.html`** in the engagement's own `VSIT/engagements/<slug>/` workspace
(one folder per engagement, with a generated `START-HERE.md` index and a machine-readable state
file). Focused commands for each entry point:

> The canonical index of **all 32 skills** (13 front doors plus their engines) lives in
> [`docs/team-operating-guide.md`](docs/team-operating-guide.md) §Command index; the table below
> is a summary.

| Command | Use it for | Pattern |
|---|---|---|
| `/engage` | anything, the front door; `--light` for small, non-regulated jobs (same safety gates, a fraction of the ceremony) | PM intake + dynamic routing |
| `/demo` | watch a full engagement end-to-end on synthetic data | guided, narrated demo |
| `/review` | every code review: `--depth quick\|deep\|audit`, `--focus security\|performance\|quantexa`, `--fix` for legacy code | lenses + scoring; evaluator-optimizer loop at audit depth |
| `/build` | full requirements → end-to-end build; `--scenario` for a single detection scenario | orchestrator-workers; spec → SME pack → build → review |
| `/requirements` | `--elicit`, `--brd`, `--fsd`, `--impact` (regulatory change) | question-led discovery, prompt chaining |
| `/detection-health` | `--coverage`, `--tune`, `--validate` for what is already deployed | coverage map, ATL/BTL calibration, validation pack |
| `/why-no-alert` | "why did this not alert?" / silent scenario / volume drop | detection-gap triage: fixed lineage walk |
| `/analyse-data` | exploratory / FP analysis / reporting-MI on safe data | evidence-tagged analysis |
| `/prepare-data` | get safe data ready (synthetic or masked) before analysis | guided onboarding + validation (⚠️ the masking pipeline is a placeholder, see [FAQ](docs/FAQ.md)) |
| `/handover` | developer + QA test-evidence handover pack | independent QA + dev docs |
| `/map-codebase` | first-contact codebase map, refreshed on drift | deterministic skeleton + synthesis |
| `/team` | `--meet` the roster, `--preferences`, `--dashboard` | quick utilities, no engagement opened |
| `/run-evals` | score the live team against the golden cases | regression net (spends tokens) |

The older command names (`/deep-review`, `/write-brd`, `/meet-the-team` and the rest) are the
engines behind these front doors and still work for one release; the index names each pair.

**Example requests** (the PM routes each to the right specialists, and only those):

```
Design a spoofing detection algorithm
Review this surveillance rule and tell me if it'd survive an audit
Explain / optimise this SQL query
Create unit tests for this detector
Document this workflow for handover
Build this from the attached FSD
```

Every deliverable is produced in **`.md` and `.html`** (via `scripts/render_html.py`) for
easy distribution, and every engagement closes with a short **summary email** (`.txt`) signed by
Morgan. See **[`docs/WAYS-OF-WORKING.md`](docs/WAYS-OF-WORKING.md)** for the frameworks, the artifact
menu and the traceability spine.

You can also just describe a task in plain English (Claude matches on each agent's
`description`), or enable experimental agent teams via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
for parallel workstreams.

<sub>[↑ Back to top](#readme-top)</sub>

## 🧩 Extending the team for your organisation

Your own analysis tooling, vendor knowledge bases, Jira steps, publishing targets and
company-unique instructions - four working recipes plus the first-class extensions contract
(ADR-009), all in **[docs/EXTENDING.md](docs/EXTENDING.md)**.

<sub>[↑ Back to top](#readme-top)</sub>

## 📓 Worked example

A captured review engagement, start to close, with what Morgan said at each gate: [`docs/worked-example.md`](docs/worked-example.md) and the verbatim transcript in [`docs/demos/review-demo.md`](docs/demos/review-demo.md).

## 🧭 Core principles

A principle without an enforcement mechanism is a hope. This domain has controls for hopes, so
every principle below names **what enforces it**, and where the enforcement is soft (a prompt,
a convention), that's stated rather than dressed up.

| Principle | What it means | What enforces it |
|---|---|---|
| **Engineering first** | Assists the engineering *behind* surveillance, not compliance, legal or regulatory advice. | Scope statement + proof-of-concept framing; obligations are cited from a verified register, never interpreted as advice. |
| **Dormant until invoked** | A normal session is standard Claude Code; the team wakes only on `/engage`, and costs ~nothing until then. | `disable-model-invocation` on all 32 skills; a lean always-on `CLAUDE.md`; per-project plugin enablement. |
| **Right-sized, not all-hands** | Only the agents a task needs (typically 2-5, never all 13), the simplest thing that works. | The PM states the intended agent count at the gate (you can veto it); a golden eval case samples the behaviour. Prompt-enforced. |
| **Independent review** | Reviewers, SMEs and the model validator recommend; builders fix. Advisors hold no edit tools; QA and validation run as separate agents from the build. | Advisory agents carry **no `Write`/`Edit` tools**; build/QA/validation separation is by routing distinct agents with isolated context (see `docs/agent-design.md`). |
| **Humans hold the keys** | Execution consent and config are human-only; nothing touches a live system without sign-off. | The consent-write gate blocks the model from **writing or editing** the consent marker, `settings*.json` and the hook files; the `CST_ALLOW_*` overrides live in the launch environment the model can't reach. Bash-channel writes are lexically guarded, not sandboxed (a documented PoC limit, ADR-002). |
| **Safe data by architecture** | Raw data under `data/raw/` is kept from the model's file-read tools; work happens downstream, on masked or synthetic data. | Raw-data hook (read tools + Bash) + OS `permissions.deny` (Read/Grep/Glob) + `.gitignore` + a CI job that fails on tracked data files + keyed masking as the sanctioned ingest path. Solid on the file-read tools; the Bash channel is lexically guarded, not a sandbox (ADR-002). |
| **Fail closed on crash** | A guard that errors exits 2 and blocks. | Crash-wrappers exit 2 (block); the launcher version-probes interpreters. Two limits are deliberate and documented: a malformed payload or a Python-less host leaves the guard inert (ADR-002). |
| **Evidence, not claims** | Findings carry 📊 measured / 🧠 inferred; pinpoint citations are retrieved, not recalled; every delivery traces requirement → code → test → obligation. | The RTM + `check_citations` (flags unregistered citations) + `check_artifacts` (the mechanical DoD gate) + the Definition of Done. |
| **Remembers, safely** | Each working project gets one codebase map: bounded, SHA-anchored, 📊/🧠-tagged, PM-written only, **advisory context never enforcement**, and no PII/MNPI/secrets, ever. | ADR-003/ADR-007 + `check_artifacts` map hygiene - mechanical: size (excl. Deprecated), header fields, per-entry As-of/Anchor validation, anchor resolution + a staleness budget against HEAD, basis tags, secret patterns. The read-at-open / update-at-close discipline itself is prompt-enforced and eval-sampled, not mechanical. The guard hooks stay the only enforcement layer. |
| **Show the journey** | Iteration history is evidence: failed review/QA passes stay visible append-only (journey strip, test cycles, clarification rounds), never smoothed into a clean narrative. | Two DoD gates ("a multi-pass engagement whose docs read first-pass-clean fails") + the templates' append-only structures. Prompt-enforced, eval-sampled. |
| **Self-tested** | The team's own quality is regression-tested like code. | 3,200+ unit tests in CI (incl. the guards driven via their real protocol) + the eval harness: 9 rubrics, 52 golden cases, contract-checked in CI, live-scored by `/run-evals`. |
| **Modular** | Each specialist evolves, retiers or gets replaced independently. | Per-agent frontmatter (`model:`, `tools:`) + manifest validation in CI + the tier table kept in sync by convention. |

<sub>[↑ Back to top](#readme-top)</sub>

## 🔍 Code-review tooling

Which analysers run per language, what is deliberately not used and why, and how findings are scored: [`docs/review/tooling.md`](docs/review/tooling.md) and [`docs/code-review-method.md`](docs/code-review-method.md).

## 🧪 Self-test (eval harness)

`python install_helper.py --selftest` runs a throwaway synthetic engagement with no model call and ends on the armed-guards line; the 3,200+ unit tests in CI drive the guards through their real protocol; `virt-surv try` shows the finished result. The live eval harness (52 golden cases, tripwires, a token-free replay in CI): [`evals/README.md`](evals/README.md).

## 🪝 The safety hooks

A *hook* is a small script Claude Code runs automatically **right before** it uses a tool, and it
can **allow** or **block** that action. This plugin ships three safety guards - the raw-data
wall **always on**, the execution gate and the consent guard's settings tier **armed only in
sessions that invoked the team** (2026-08-17; the marker/hook/git-exec-config protections in
them stay always-on) - plus a fourth always-on guard scoping the five reviewer agents' Write/Edit
to their own findings-pack file, five engagement-scoped lifecycle hooks and three further
cost/UX redirect hooks (see the Claude Code features table; the lifecycle hooks no-op in dormant
sessions and fail open, and so do the redirects - detail on the redirects is in
`docs/team-operating-guide.md`). The guards run even when the
team is dormant. The newcomer-friendly version of the whole safety story is in
[`docs/OVERVIEW.md` §5](docs/OVERVIEW.md); the per-channel confidence statement (exactly what
each control does and does not guarantee) is [`docs/safety-model.md`](docs/safety-model.md);
the operational detail is below.

In one line: `guard-raw-data.py` blocks Read/Grep/Glob/Bash on `data/raw/`; `guard-code-execution.py` gates test runners, scripts and profilers behind the `.claude/.exec-consent` marker / `CST_ALLOW_EXEC`; `guard-consent-writes.py` blocks model writes of the consent marker, `settings.json` and the hook files.

<details>
<summary>🪝 <b>The raw-data guard, the code-execution gate + the consent-write gate</b>: what they do and how strong they are</summary>

**1. The raw-data guard** (`guard-raw-data.py`): *agents must never read real, unmasked data.*
Anything an agent reads is sent to the AI model, so real records (PII/MNPI) can't go that way. The
hook blocks any read/search/command whose path lands inside `data/raw/`. Point the team at masked or
synthetic data instead.

**2. The code-execution gate** (`guard-code-execution.py`): *reviewing code means reading it, not
running it.* Running untrusted code is a real risk, so commands that **execute** code (test runners,
scripts, profilers) are blocked **unless you've given consent**: a `.claude/.exec-consent` marker
or `CST_ALLOW_EXEC=1`. The team's own `scripts/` helpers are always allowed.

**3. The consent-write gate** (`guard-consent-writes.py`): *only a human can open the execution
gate.* Answering "yes" at intake expresses intent, but it does not unlock anything: the model is
blocked from writing the consent marker, the settings files, and the guard hooks themselves, so a
confused (or prompt-injected) model cannot authorise itself to run code or quietly rewrite its own
guardrails. **You** create the marker; the team gives you the exact command **with the absolute
project path** (e.g. `! touch /path/to/your-project/.claude/.exec-consent`, the `!` shell is
Git Bash on Windows too, so this works everywhere; from your **own** Windows terminal use
PowerShell `ni "C:\path\to\project\.claude\.exec-consent" -Force` or cmd
`type nul > "C:\path\to\project\.claude\.exec-consent"` instead, or the same `touch`
in any terminal); deleting it (closing the gate) and reading it stay allowed, and hook
maintenance needs the human-set `CST_ALLOW_CONFIG_EDIT=1`.

All are wired in **two** places so they fire in either mode: `hooks/hooks.json` (installed as a
plugin) and `.claude/settings.json` (this repo opened as a project), and a test keeps the two copies
identical.

**How strong are they?** For the file tools (`Read`/`Grep`/`Glob`) the guard hook fires in both
modes, and **when this repo is opened as a project** it is additionally backed by the OS-level
`permissions.deny` list in `.claude/settings.json`, so it holds. **A plugin install into a
foreign project ships the hook but not that deny list** (a plugin can carry hooks, not permissions),
so the hook is then the sole file-tool control; installers who want the belt-and-braces backstop
should copy the `Read`/`Grep`/`Glob` deny entries into their own project's `.claude/settings.json`
(see [`docs/house-rules.md`](docs/house-rules.md)). For **shell commands** the guards work by
*reading the text of the command*, a strong default and a consent record, but **not a sandbox**: a
determined user can dodge string-matching (e.g. hide a path in a variable). The real boundary for
shell is OS file permissions / keeping raw data off the box. The full bypass analysis and the
hardening backlog are in ADR-002.

</details>

<sub>[↑ Back to top](#readme-top)</sub>

## 🔒 Handling real data

**Raw data under `data/raw/` is hard-blocked**: the guard stops any agent reading it, and
anything an agent reads goes to the model provider as context. The whole safety story in one
picture:

```mermaid
flowchart LR
    Real[(real data)] --> Raw["data/raw/ 🔴<br/>agent-blocked"]
    Raw -- "python -m scripts.ingest<br/>(keyed masking, local)" --> Masked["data/masked/ 🟠<br/>pseudonymised, governed"]
    Gen["scripts.gen_synthetic /<br/>scripts.synthesise"] --> Synth["data/synthetic/ 🟢<br/>no real records"]
    Masked --> Agents[agents 🤖]
    Synth --> Agents
    Agents -- "everything they read" --> Provider([model provider ☁️])
    Raw -. "Read/Grep/Glob/Bash ⛔ guard-raw-data.py<br/>(+ permissions.deny on Read/Grep/Glob)" .-x Agents
```

Two safe ways to get data to the team:

1. **Mask it** through the pipeline (recommended for real data) → point agents at `data/masked/`;
   or **synthesise** it (safest, shareable).
2. **Provide already-safe data** (synthetic / masked / anonymised). A **startup disclaimer** has
   you confirm it carries no prohibited PII/MNPI; that's your responsibility, not the team's.

Either way, **committed examples, tests, artifacts and logs stay synthetic/masked only** (§5);
the attestation covers the analysis *inputs* you point at, not what gets written into the repo.
An **automatic masking workflow** (so you don't have to self-attest) is on the [roadmap](#-roadmap).

> Pseudonymised data is still personal data (GDPR). Masking enables local development; prefer fully
> synthetic data for anything that leaves the environment. (Plain-English version:
> [`docs/OVERVIEW.md` §5](docs/OVERVIEW.md).)

> ⚠️ **The masking pipeline is an early proof of concept**, a demonstration of the *workflow*,
> **not** a production-grade anonymiser, and not to be relied on as the sole control. It is
> **expected to be replaced** by a stronger data-preparation pipeline (local schema profiling,
> NER-based free-text redaction, validated synthetic data, and an auto-validation gate that blocks
> on residual PII), not incrementally evolved. Until then, keep real data in `data/raw/`
> (agent-blocked), prefer synthetic, and only ever feed it data your own controls have already
> masked or anonymised.

In one line: `python -m scripts.ingest` masks `data/raw/` → `data/masked/` (keyed HMAC tokens, time shift, regex redact via `config/masking-schema.yaml` + `MASKING_KEY`); `scripts.validate_masking` checks it; `scripts.synthesise` emits fully synthetic sessions. Per-channel guarantees: [`docs/safety-model.md`](docs/safety-model.md).

<details>
<summary>🔒 <b>The masking pipeline</b>: ingest · validate · synthesise (scripts + commands)</summary>

```
real ─▶ data/raw/ ──[ python -m scripts.ingest ]──▶ data/masked/ ─▶ agents / dev
        (agent-blocked)   schema-driven masking        (governed)
                                  │
                                  └─ fit a synthetic generator for anything that leaves the env
```

- **`scripts/ingest.py`**: schema-driven masking (`config/masking-schema.yaml`). Each field
  has a role: `token` (keyed HMAC, preserves linkage), `shift` (per-entity time shift,
  preserves deltas), `keep` (signal-bearing values), `generalise`, `redact` (free text).
  Key from `MASKING_KEY` in `~/.secrets`, no insecure default. ⚠️ **`redact` is regex-only**
  (email/IBAN/card/SSN/phone), fine for structured fields, **not safe for real comms/chat**
  (misses names + obfuscated IDs); swap in NER before masking real communications (roadmap).
- **`scripts/validate_masking.py`**: two modes. **Default** = a *config self-test* on a synthetic
  fixture: it proves the schema + masking logic are sound (no residual identifiers/PII in the
  fixture, the spoofing rule fires identically masked-vs-original, k-anonymity over any *declared*
  quasi-identifiers). It does **not** inspect your data. **`--in data/masked/x.jsonl`** = scans
  **your actual masked file** for residual free-text PII (string fields) + k-anonymity. *(It can't
  verify "no original identifier survived" or fidelity without the originals; by design they never
  reach it.)* Note: k-anonymity is **off until you declare `quasi_identifiers`** in the schema.
- **`scripts/synthesise.py`**: the safest tier: learns the *shape* of masked data
  (size/timing distributions + the spoofing motif at its observed rate) and emits fully
  **synthetic** sessions that share no real entity, timestamp or row. This is what's safe
  to put in front of an agent or to share outside the environment.
- **`.claude/hooks/guard-raw-data.py`**: PreToolUse hook (wired in both `.claude/settings.json`
  and `hooks/hooks.json`) that blocks any agent `Read`/`Grep`/`Glob`/`Bash` touching `data/raw/`.
  See [the safety-hooks section](#-the-safety-hooks) for what "blocks" means for
  shell commands vs the file tools.

```bash
export MASKING_KEY=...                                   # from ~/.secrets
python -m scripts.ingest --in data/raw/x.jsonl --out data/masked/x.jsonl
python -m scripts.validate_masking                       # config self-test (synthetic fixture)
python -m scripts.validate_masking --in data/masked/x.jsonl   # scan YOUR masked file for residual PII
```

</details>

<sub>[↑ Back to top](#readme-top)</sub>

## 📁 Layout

What lives where in this repository: [`docs/README.md`](docs/README.md), "Repository layout".

## 🗂️ Scripts reference

Every script under `scripts/`, what it does and when the team runs it: [`docs/scripts-reference.md`](docs/scripts-reference.md).

## 🧰 Claude Code features this team is built on

Which Claude Code features the team is built on (plugin, subagents, skills, hooks, status line) and the notes on `.claude/settings.json`: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) (bottom two sections).

## 💰 Token usage & optimisation

What an engagement costs, measured, and how the team keeps its context load down: [`docs/token-usage.md`](docs/token-usage.md).

## 🗺️ Roadmap

Where this is going: [`docs/roadmap.md`](docs/roadmap.md).

## ❓ FAQ

Measured vs inferred, the hallucination question, what the `VSIT/engagements/` folder is, who
Morgan is, how execution consent works and more - all in **[docs/FAQ.md](docs/FAQ.md)**.

<sub>[↑ Back to top](#readme-top)</sub>

## 📖 Documentation

Every document under `docs/`, by purpose: [`docs/README.md`](docs/README.md).

## ⚠️ Known issues

The user-facing limitations, in one screen. The dated narrative behind each, with what was tried
and what is still open, moved to `docs/internal/incident-log.md` on 2026-09-14 (framework review,
step 1.5); ADR-002 carries the security residual in full.

- **The Bash channel is lexically guarded, not sandboxed.** The guards are a real control for a
  cooperative agent; a determined or prompt-injected model can obfuscate a shell command past them.
  Keep real data off the machine (§5); that is the boundary.
- **A plugin install ships the hooks but not a `permissions.deny` list.** Copy the raw-data deny
  entries from this repo's `.claude/settings.json` into your project's for the OS-level backstop.
- **The first `/engage` of a session can take two to three minutes on a corporate Windows box.**
  Launch through `virt-surv go`, which pre-computes the probe; `python install_helper.py` prewarms
  the interpreter cache.
- **A heavy engagement can hit context compaction during setup.** Prefer `/engage --light` for
  small jobs; the turn-0 load is being cut (plan step 4.4) and is pinned by a test.
- **Claude Code starts slowly (20 to 27 s) on Windows for a local-scope install.** Install from the
  marketplace registry rather than a local path.
- **Cosmetics:** Morgan occasionally narrates a wrong agent name or repeats the sizing line on a
  chained engagement; some emoji render as boxes on older Windows and Edge. None affects the work.
- **Two eval cases score a correct behaviour as a failure** (async Workflow dispatch; identified
  injection attempts); backlogged, adjudicated in the baseline.
- **Daemon-routed hook calls still pay one interpreter spawn per call** (ADR-014, off by default).
- **The masking pipeline behind `/prepare-data` is a placeholder**, not an anonymisation control.
- **`main` lags `dev`**; the installer defaults to `dev` during the POC for that reason.

## 🤝 Contributing

Contributions, issues, suggestions and discussions are welcome.

1. Fork the repository and create a feature branch.
2. Keep the guardrails green: CI runs **tests + lint (ruff) + manifest validation + gitleaks +
   a no-raw-data check**; `pre-commit install` runs the secret / raw-data guards locally.
3. **Never commit secrets or real data**: tests and fixtures use synthetic/masked data only (§5).
4. Detection-logic changes need a review (`code-reviewer` + `compliance-reviewer`) and tests
   (true- *and* false-positive cases) before merge.
5. Open a pull request.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the detail.

<sub>[↑ Back to top](#readme-top)</sub>

## 📚 Built on & acknowledgements

Virtual Surv-IT explores collaborative AI engineering by combining specialised Claude Code agents
into a coordinated team, with independent review, to produce higher-quality engineering outcomes.
It is designed to follow Anthropic's published best practice for agents and multi-agent systems
(conformance audit in [`docs/agent-design.md`](docs/agent-design.md)):

- [**Building Effective Agents**](https://www.anthropic.com/engineering/building-effective-agents): patterns + "use the simplest thing that works".
- [**How we built our multi-agent research system**](https://www.anthropic.com/engineering/multi-agent-research-system): orchestrator-worker, delegation briefs, ~15× token cost, failure modes.
- [**Effective context engineering for AI agents**](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents): context isolation, compaction, agentic memory.
- [**Subagents (Claude Agent SDK)**](https://code.claude.com/docs/en/agent-sdk/subagents) · [**Claude Code subagents**](https://code.claude.com/docs/en/subagents): frontmatter, tools, model tiering, isolation.

The `code-reviewer`'s **confidence-scoring, false-positive filtering, filter-transparency and
deep-review** approach is adapted from
[**turingmind-code-review**](https://github.com/turingmindai/turingmind-code-review) (MIT, © 2026
TuringMind; see [`docs/code-review-method.md`](docs/code-review-method.md)), with our additions of
a regulated-domain audit mode and data-safety/traceability weighting.

## ⚖️ Disclaimer

Virtual Surv-IT is an **engineering productivity framework**, and it is **in active development**:
expect bugs, breaking changes and occasional unexpected behaviour. It is **not** a compliance
advisory service and is **not** a substitute for legal, regulatory or professional judgement. Its
outputs are a starting point for real engineers and reviewers; **users remain responsible for
validating all outputs before any production use.**

## 📄 License

**GNU AGPL-3.0-only.** Copyright © 2026 Daniel Edge. Full text in [`LICENSE`](LICENSE).

In plain English (the [`LICENSE`](LICENSE) text governs):

- ✅ **Use it freely, including inside a company and for commercial work.** Running, modifying and
  using it internally carries no obligation. Internal use is not "distribution".
- 🔁 **If you distribute it, or offer it to others as a network/hosted service**, you must make your
  **complete corresponding source** (including your modifications) available to those users under
  the **same AGPL-3.0** terms. This is what stops it being taken closed-source, repackaged and
  resold or hosted as a proprietary product.
- 🏦 **Internal deployment in a bank.** Employees using the plugin on their own machines, or an
  internal service your own staff use, is internal use: the network clause obliges you to offer
  the corresponding source to *those users*, which inside one organisation is the repository
  they already have. It does not oblige you to publish anything outside the organisation.
- 🚫 **No warranty** (provided "as is").
- 💼 **Want it without the AGPL source-sharing obligation** (e.g. to embed it in a proprietary
  product)? A separate **commercial licence** can be arranged: contact the author. (The author is
  the sole copyright holder and can dual-license; external contributions would be taken under a
  contributor agreement so that stays possible, see [`CONTRIBUTING.md`](CONTRIBUTING.md).)

The project bundles and adapts permissively-licensed third-party components (MIT / BSD-3 / PSF).
Those keep their own licences; their notices are in
[`THIRD-PARTY-LICENSES.md`](THIRD-PARTY-LICENSES.md). Permissive licences may be included in an
AGPL-licensed work, so there is no conflict.
