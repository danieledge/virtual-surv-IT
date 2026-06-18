# Compliance Surveillance Virtual Team — Install

A Claude Code subagent set mirroring a compliance development team across transaction
monitoring, trade surveillance and communications surveillance.

## Layout

```
CLAUDE.md                     # shared team handbook (example defaults — customise as needed)
.claude/agents/               # 10 subagents
  requirements-analyst.md     # BA            (build)
  tm-sme.md                   # AML SME       (advisory, read-only)
  trade-surveillance-sme.md   # SME           (advisory, read-only)
  comms-surveillance-sme.md   # SME           (advisory, read-only)
  rules-developer.md          # developer     (build)
  data-analyst.md             # analyst       (build)
  ml-engineer.md              # AI/ML         (build)
  model-validator.md          # independent validation (advisory, read-only)
  cloud-architect.md          # cloud         (advisory + light build)
  compliance-reviewer.md      # review/QA     (advisory, read-only)
```

## Install

1. Copy `CLAUDE.md` to your repo root (merge if you already have one).
2. Copy the `.claude/agents/` folder into your repo. Commit both so the whole team shares them.
3. Restart Claude Code (subagents load at session start), then run `/agents` to confirm they appear.
4. (Optional) `CLAUDE.md` §2/§3 ship with example defaults so the team works immediately.
   Replace the example jurisdictions and stack with your own when you have them.

## Using them

Automatic: just describe the task — Claude matches on each agent's `description`.

Explicit / chained:
```
Use requirements-analyst to turn this MAR spoofing requirement into a spec,
have trade-surveillance-sme review the detection logic, then rules-developer
implement it and compliance-reviewer check the audit trail.
```

Parallel (optional, experimental, token-heavy): enable agent teams by adding
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` to your settings.json, then ask Claude to
spawn a team with a lead.

## Worked example & repo layout

A complete reference scenario ships with the repo so the conventions are concrete:

```
rules/spoofing.py            # MAR spoofing detection (deterministic, explainable)
scripts/gen_synthetic.py     # synthetic order-flow generator (§5 — no real data)
tests/test_spoofing.py       # true-positive + false-positive cases (§4)
docs/scenarios/spoofing.md   # audit trail: alert → logic → obligation
docs/templates/              # scenario spec, scenario doc, model-validation report
.claude/commands/new-scenario.md   # /new-scenario — runs the spec→SME→build→review chain
.github/workflows/ci.yml     # runs tests + gitleaks + a no-raw-data check
.pre-commit-config.yaml      # local secret / raw-data guardrails
```

Quickstart:

```bash
pip install -r requirements-dev.txt
pytest                                   # 5 passing tests
python -m scripts.gen_synthetic --kind spoofing --out data/synthetic/spoofing.jsonl
pre-commit install                       # optional: enable local guardrails
```

Add a new detection with `/new-scenario <requirement>`, which chains
requirements-analyst → SME → rules-developer → compliance-reviewer per the handbook.

## Notes on the config

- Advisory agents are restricted to read-only tools (`Read, Grep, Glob`, sometimes `Bash`)
  so they physically cannot alter detection logic.
- Build agents have write access (`Read, Write, Edit, Bash, Grep, Glob`).
- SMEs and reviewers use `memory: project` to accumulate house typologies and tuning
  decisions across sessions (stored under `.claude/agent-memory/`).
- Models: deep-reasoning roles use `opus`, build/analysis roles use `sonnet`. Change the
  `model:` field freely.
