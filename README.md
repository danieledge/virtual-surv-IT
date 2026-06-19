# Compliance Surveillance Engineering — Virtual Team

A **virtual compliance surveillance *engineering* team made of AI assistants** — it doesn't
*do* compliance, it **builds the surveillance solutions and technology** behind detecting
money laundering, market manipulation and trader misconduct. Detection rules are just one
deliverable: it equally builds **data pipelines / ETL, transformation and utility scripts
(Python, Scala, Java, PowerShell, Bash), reconciliation and reporting jobs, tooling**, or
simply **reviews** existing code. It runs in
[Claude Code](https://claude.com/claude-code) as a set of 11 focused "subagents": some are
subject-matter experts who only advise, others engineer and test the solutions, and the work
flows between them like a real engineering team.

> 🟢 **New to AI agents and LLMs? Read [`docs/OVERVIEW.md`](docs/OVERVIEW.md) first** — a
> plain-English tour of what this is, who the team are, and how it keeps confidential data
> away from the AI. No prior knowledge needed.

```mermaid
flowchart LR
    You([You: describe the need]) --> RA[requirements-analyst]
    RA --> SME{domain expert<br/>reviews}
    SME --> Dev[rules-developer<br/>builds + tests]
    Dev --> Rev[compliance-reviewer<br/>signs off]
    Rev --> Done([approved detection ✅])
```

**The safety rule in one line:** real data is never shown to the AI — it's either *masked*
(identities scrambled, behaviour kept) or fully *synthetic* (made up), and an automatic
guard blocks any agent from reading raw records. See
[How real data is handled](#handling-real-data-masking-pipeline).

## Quick start — using the team

```bash
# 1. Get it into your project (new project, or merge into an existing repo)
git clone https://github.com/danieledge/virtual-surv-IT.git
cd virtual-surv-IT
pip install -r requirements-dev.txt      # pytest, plus Markdown for .md→.html artifacts

# 2. Open in Claude Code (the 11 agents + slash commands load on start)
claude
```

Then just **talk to the PM** — describe whatever you've got:

```
/engage I need to detect wash trades in our equities flow
/engage here's a PowerShell script, review it and tell me if it'd survive an audit
/engage build this from the attached FSD
```

The PM (the main session) then:
1. **Asks you clarifying questions** and waits for your answers — it won't guess scope,
   jurisdiction, data or success criteria.
2. **Offers a menu of deliverables** to pick from (BRD, FSD, ADRs, RTM, review report,
   audit pack…).
3. **Agrees a plan** with you (the Engagement Brief), then **runs the right specialists**.
4. **Hands back deliverables in both `.md` and `.html`** under `artifacts/`.

Prefer to drive a specific step yourself? Use the focused commands:
`/write-brd` · `/brd-to-fsd` · `/deep-review` · `/audit-review` · `/build-solution` ·
`/new-scenario` (see [Using them](#using-them)).

> Don't have Claude Code yet? Install it from <https://claude.com/claude-code>, then run
> `claude` inside this folder. New to agents/LLMs? Read
> [`docs/OVERVIEW.md`](docs/OVERVIEW.md) first.

## Layout

```
CLAUDE.md                     # shared team handbook (example defaults — customise as needed)
.claude/agents/               # 11 subagents
  requirements-analyst.md     # BA            (build)
  tm-sme.md                   # AML SME       (advisory, read-only)
  trade-surveillance-sme.md   # SME           (advisory, read-only)
  comms-surveillance-sme.md   # SME           (advisory, read-only)
  rules-developer.md          # developer     (build)
  data-analyst.md             # analyst       (build)
  ml-engineer.md              # AI/ML         (build)
  model-validator.md          # independent validation (advisory, read-only)
  cloud-architect.md          # cloud         (advisory + light build)
  code-reviewer.md            # multi-language code review (advisory, read-only)
  compliance-reviewer.md      # review/QA     (advisory, read-only)
```

## Meet the agents

Eleven specialists, each defined by a short job description in `.claude/agents/`. They split
into **🧠 advisors** (read-only — they review and recommend but cannot change code, which
keeps them independent) and **🔧 builders** (they engineer and test the detection systems).

### 🔧 Builders — they engineer the surveillance technology

- **`requirements-analyst`** — turns a regulatory or business need into a clear,
  implementable spec (user stories, acceptance criteria, true/false-positive cases) before
  any code is written.
- **`rules-developer`** — implements and refactors deterministic detection rules and
  scenario logic for transaction monitoring and trade surveillance, from a validated spec.
- **`data-analyst`** — tuning, false-positive analysis, threshold calibration, coverage
  testing, plus data-quality, reconciliation and reporting/MI work.
- **`ml-engineer`** — builds ML/AI-based detection where rules aren't enough (anomaly
  detection, NLP for comms, behavioural scoring, alert triage).
- **`cloud-architect`** — designs **and builds** the data pipelines and platform: ingestion,
  ETL, streaming/batch transformation, transformation/utility scripts (Python, Scala,
  PowerShell, Bash), infra/IaC, retention/immutability, data residency, resilience.

> Routing by deliverable, not habit: a detection rule → `rules-developer`; an ETL pipeline or
> a PowerShell transform → `cloud-architect`; a reconciliation/reporting job → `data-analyst`;
> an ML model → `ml-engineer`. The PM picks; see CLAUDE.md §6.

### 🧠 Advisors — they guide and sign off (read-only)

- **`tm-sme`** — transaction-monitoring / AML expert: detection scenarios, typologies,
  thresholds, segmentation, SAR/STR rationale.
- **`trade-surveillance-sme`** — market-abuse expert: spoofing, layering, wash trades,
  marking the close, insider dealing, front running.
- **`comms-surveillance-sme`** — communications-surveillance expert: lexicons, NLP risk
  policies, e-comms and voice monitoring mapped to conduct risk.
- **`model-validator`** — **independent** validation of any statistical/ML model
  (soundness, performance, bias, stability, explainability). Independent of `ml-engineer`
  by design, so it's free to challenge.
- **`code-reviewer`** — comprehensive code review across **Python, Scala, Java, PowerShell
  and Bash**. Drives the established linters/analysers for each language (ruff/mypy/bandit,
  Checkstyle/SpotBugs/PMD, scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, plus Semgrep) —
  not reinvented rules — and adds judgment on top.
- **`compliance-reviewer`** — final QA after any change: auditability, the
  alert→logic→obligation trace, secrets/PII, and test coverage.

> Why read-only matters: an advisor that could quietly edit the thing it's reviewing isn't a
> real independent check. The restriction is enforced by the tools each agent is granted —
> advisors get `Read, Grep, Glob` only — not by convention.

## Install

1. Copy `CLAUDE.md` to your repo root (merge if you already have one).
2. Copy the `.claude/agents/` folder into your repo. Commit both so the whole team shares them.
3. Restart Claude Code (subagents load at session start), then run `/agents` to confirm they appear.
4. (Optional) `CLAUDE.md` §2/§3 ship with example defaults so the team works immediately.
   Replace the example jurisdictions and stack with your own when you have them.

## Using them

It's one **dynamic, agile delivery team** with a single front door: the **PM**. Throw it a
problem, code to review, or requirements to build, and it clarifies, lets you pick the
deliverables, then orchestrates the specialists.

```
/engage <a problem, code to review, or a set of requirements>
```

The PM asks clarifying questions (and waits for your answers), offers a **menu of documentary
artifacts** to choose from, summarises everything in an Engagement Brief, then oversees
delivery. Focused commands for each entry point:

| Command | Use it for | Pattern |
|---|---|---|
| `/engage` | anything — the front door | PM intake + dynamic routing |
| `/write-brd` | idea → Business Requirements (BABOK + EARS) | prompt chaining |
| `/brd-to-fsd` | BRD → Functional Spec (ISO 29148 + Gherkin) | prompt chaining |
| `/deep-review` | detailed code review (bugs, security, architecture, impact) | dimension fan-out + scoring |
| `/audit-review` | existing code → robust & audit-ready? | evaluator–optimizer loop |
| `/build-solution` | full requirements → end-to-end build | orchestrator–workers |
| `/new-scenario` | a single detection scenario | spec → SME → build → review |

Every deliverable is produced in **`.md` and `.html`** (via `scripts/render_html.py`) for
easy distribution. See **[`docs/WAYS-OF-WORKING.md`](docs/WAYS-OF-WORKING.md)** for the
frameworks, the artifact menu and the traceability spine.

You can also just describe a task in plain English (Claude matches on each agent's
`description`), or enable experimental agent teams via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
for genuinely parallel workstreams.

## Worked example & repo layout

A complete reference scenario ships with the repo so the conventions are concrete:

```
rules/spoofing.py            # MAR spoofing detection (deterministic, explainable)
scripts/gen_synthetic.py     # synthetic order-flow generator (§5 — no real data)
tests/test_spoofing.py       # true-positive + false-positive cases (§4)
docs/scenarios/spoofing.md   # audit trail: alert → logic → obligation
docs/WAYS-OF-WORKING.md      # frameworks, workflows, artifact menu, traceability spine
docs/templates/              # engagement brief, BRD, FSD, ADR, RTM, review report, scenario, model-validation
scripts/render_html.py       # render any .md artifact to standalone .html for distribution
.claude/commands/            # /engage, /write-brd, /brd-to-fsd, /audit-review, /build-solution, /new-scenario
.github/workflows/ci.yml     # runs tests + gitleaks + a no-raw-data check
.pre-commit-config.yaml      # local secret / raw-data guardrails
```

Quickstart:

```bash
pip install -r requirements-dev.txt
pytest                                   # 16 passing tests
python -m scripts.gen_synthetic --kind spoofing --out data/synthetic/spoofing.jsonl
pre-commit install                       # optional: enable local guardrails
```

Add a new detection with `/new-scenario <requirement>`, which chains
requirements-analyst → SME → rules-developer → code-reviewer → compliance-reviewer per the
handbook.

## Code-review tooling

The `code-reviewer` agent drives standard analysers — it doesn't reinvent rules. The Python
ones are in `requirements-review.txt` (kept separate so the core test install stays lean).
The rest install via the OS / build tooling:

| Language | Install |
|---|---|
| Python | `pip install -r requirements-review.txt` (ruff, black, mypy, bandit, pip-audit, semgrep) |
| Bash | `apt install shellcheck` · `go install mvdan.cc/sh/v3/cmd/shfmt@latest` |
| PowerShell | `pwsh -c 'Install-Module PSScriptAnalyzer -Scope CurrentUser'` |
| Java | `checkstyle`, `pmd`, `spotbugs` via your build tool (Maven/Gradle) or `brew`/`apt` |
| Scala | `scalafmt`, `scapegoat`/`wartremover` via sbt plugins |
| Any | Semgrep (`pip`) for multi-language; gitleaks for secrets |

The agent runs whatever is present and reports which analysers were unavailable — nothing is
silently skipped. None of these are required to *use* the team; they sharpen `code-reviewer`.

## Handling real data (masking pipeline)

Agents must never see raw records — anything an agent reads goes to the model provider as
prompt context. So real data only enters through a masking pipeline, and agents sit
downstream of it:

```
real ─▶ data/raw/ ──[ python -m scripts.ingest ]──▶ data/masked/ ─▶ agents / dev
        (agent-blocked)   schema-driven masking        (governed)
                                  │
                                  └─ fit a synthetic generator for anything that leaves the env
```

- **`scripts/ingest.py`** — schema-driven masking (`config/masking-schema.yaml`). Each field
  has a role: `token` (keyed HMAC, preserves linkage), `shift` (per-entity time shift,
  preserves deltas), `keep` (signal-bearing values), `generalise`, `redact` (free text).
  Key from `MASKING_KEY` in `~/.secrets` — no insecure default.
- **`scripts/validate_masking.py`** — gate that proves a config is safe *and* useful: no
  residual identifiers/PII, k-anonymity over quasi-identifiers, **and** the spoofing rule
  fires identically on masked vs. original data (fidelity).
- **`scripts/synthesise.py`** — the safest tier: learns the *shape* of masked data
  (size/timing distributions + the spoofing motif at its observed rate) and emits fully
  **synthetic** sessions that share no real entity, timestamp or row. This is what's safe
  to put in front of an agent or to share outside the environment.
- **`.claude/hooks/guard-raw-data.py`** — PreToolUse hook (wired in `.claude/settings.json`)
  that blocks any agent `Read`/`Bash` touching `data/raw/`.

```bash
export MASKING_KEY=...                                   # from ~/.secrets
python -m scripts.ingest --in data/raw/x.jsonl --out data/masked/x.jsonl
python -m scripts.validate_masking                       # exit 0 = safe + faithful
```

> Pseudonymised data is still personal data (GDPR). Masking enables local development;
> prefer fully synthetic data for anything that leaves the environment.

## Notes on the config

- Advisory agents are restricted to read-only tools (`Read, Grep, Glob`, sometimes `Bash`)
  so they physically cannot alter detection logic.
- Build agents have write access (`Read, Write, Edit, Bash, Grep, Glob`).
- SMEs and reviewers use `memory: project` to accumulate house typologies and tuning
  decisions across sessions (stored under `.claude/agent-memory/`).
- Models: deep-reasoning roles use `opus`, build/analysis roles use `sonnet`. Change the
  `model:` field freely.

## Credits

- The `code-reviewer`'s **confidence-scoring, false-positive filtering, filter-transparency
  and deep-review** approach is adapted from
  [**turingmind-code-review**](https://github.com/turingmindai/turingmind-code-review)
  (MIT, © 2026 TuringMind). See [`docs/code-review-method.md`](docs/code-review-method.md).
  Our additions: regulated-domain audit mode and data-safety/traceability weighting.
