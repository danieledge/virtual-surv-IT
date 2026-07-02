# Contributing

Thanks for helping improve the Compliance Surveillance Engineering virtual team. This is a
Claude Code plugin (agents + skills + docs + a small Python tooling package). The notes below
keep contributions consistent with the project's own standards.

## Ground rules (non-negotiable)

- **Never commit real data or secrets.** All examples and tests use **synthetic or masked** data
  (`CLAUDE.md` §5). `data/raw/` is git-ignored and blocked from agents by a hook - keep it that way.
- **No hard-coded credentials.** Read from the environment (e.g. `MASKING_KEY`). CI runs gitleaks.
- **Detection logic must stay explainable and auditable** - documented thresholds with a rationale
  and tuning date, and a traceable link from alert → logic → obligation (`CLAUDE.md` §4).

## Local setup

```bash
pip install -r requirements-dev.txt        # pytest, PyYAML, Markdown, bleach, pre-commit
pip install -r requirements-review.txt      # optional: ruff, bandit, mypy, … (sharpen reviews)
pre-commit install                          # optional but recommended
```

## The CI pipeline

CI is GitHub Actions (`.github/workflows/ci.yml`), running on **GitHub-hosted `ubuntu-latest`
runners** - fresh, ephemeral VMs per job, nothing self-hosted. It triggers on **every push to
`main` and every pull request**, and runs **four jobs in parallel**:

| Job | What it does |
|---|---|
| **Tests (detection logic)** | Python 3.12 → `pip install -r requirements-dev.txt` → `pytest` (the full suite: rules, masking, renderer, all three safety guards driven via their JSON protocol, hook-config sync, the per-case eval contract, the DoD artifact checker) → `scripts.validate_masking` → `scripts.validate_manifest` |
| **Lint & static analysis** | `ruff check` + `ruff format --check` over `scripts/ .claude/hooks/ rules/ tests/` · `bandit` (Python security) · `shellcheck` (Bash + git hooks) |
| **Secret scan** | gitleaks over the **full history** (`fetch-depth: 0`), not just the diff |
| **No raw data committed** | fails if any `*.csv` / `*.parquet` / `*.pcap` is tracked (`CLAUDE.md` §5) |

Watch runs on the repo's **Actions** tab, or `gh run list` / `gh run watch` from a terminal.

**What CI deliberately cannot cover** (see the note in `docs/DEFINITION-OF-DONE.md`):
engagement deliverables (`artifacts/` is git-ignored - `python -m scripts.check_artifacts` is
the gate for those), and **live team quality** (prompt regressions need `/run-evals`, which
spends tokens; CI proves the eval harness *contract* - manifests well-formed, scorer
discriminating - not the team's live output).

There is also a **local layer in front of CI**: `pre-commit install` gives you gitleaks, a
raw-data file block, whitespace/private-key checks, and pytest on changes to `rules/`,
`tests/` or `scripts/`. The Claude Code safety hooks are *not* part of CI - they run inside
Claude Code sessions only.

## Before you open a PR

Run what CI runs:

```bash
pytest                                       # all unit tests must pass
python -m scripts.validate_masking           # masking safety + detection fidelity
python -m scripts.validate_manifest          # declared agents/skills resolve
ruff check scripts/ .claude/hooks/ rules/ tests/
ruff format --check scripts/ .claude/hooks/ rules/ tests/
bandit -r scripts/ .claude/hooks/ -q
shellcheck scripts/*.sh scripts/git-hooks/pre-commit scripts/git-hooks/pre-push
git ls-files '*.csv' '*.parquet' '*.pcap'    # must print nothing (no raw data tracked)
```

(Gitleaks runs via `pre-commit` locally and in CI over the full history.)

## The tooling, in plain English

What each tool is and does (all of these run automatically in CI on every push/PR):

| Tool | What it is | Covers |
|------|------------|--------|
| **pytest** | Runs the unit tests - the safety net that proves the code (detection rule, masking, renderer, the guard hooks) still behaves. | the Python in `rules/`, `scripts/`, `.claude/hooks/` |
| **ruff check** | A **linter**: flags likely mistakes - unused imports, dead variables, bug-prone patterns. | Python only (`.py`) |
| **ruff format** | A **formatter**: restyles layout (spacing, line breaks, quotes) for one consistent look. It never changes what the code *does*. | Python only (`.py`) |
| **bandit** | A **security** scanner for Python - e.g. hardcoded secrets, unsafe calls. | Python only |
| **shellcheck** | A linter for **Bash** scripts (catches shell bugs/quoting issues). Lint only - it does not reformat. | the `*.sh` + git-hook scripts |
| **validate_masking** | Proves the masking config is both **safe** (no original PII survives) and **useful** (detection still fires on masked data). `--in <file>` scans your actual masked output. | `scripts/`, `config/masking-schema.yaml` |
| **validate_manifest** | Checks the plugin manifest (`plugin.json`) matches the repo - every declared agent/skill/hook actually exists. | `.claude-plugin/` |

Two things worth knowing:

- **Ruff is Python-only.** It does not touch Bash, JSON, YAML or Markdown. Bash is linted by
  shellcheck; JSON is content-checked by `validate_manifest`; **Markdown / YAML / JSON layout is
  by hand** (e.g. the "ASCII hyphens, not en-dashes" rule is a convention, not enforced).
- **The three safety hooks are a separate thing** from this tooling - they run *inside Claude
  Code* to block raw-data reads, un-consented code execution, and model writes of the consent
  marker / settings / the hooks themselves. They're explained in `docs/house-rules.md` and
  threat-modelled in `docs/adr/ADR-002`.

## Adding or changing components

- **Agent** - add `.claude/agents/<slug>.md` with frontmatter (`name`, `description`, `model`,
  `tools`). Advisory/read-only agents must **not** hold `Write`/`Edit` (`CLAUDE.md` §7). Then
  **register it in `.claude-plugin/plugin.json`** (`agents` array) - `validate_manifest` enforces
  that the declared set matches the files on disk.
- **Model tier** - if you set or change an agent's `model:`, update the tier table in
  **`docs/agent-design.md`** in the same change. The two are expected to stay in sync.
- **Skill** - add `.claude/skills/<name>/SKILL.md` (the command name comes from the directory
  name; frontmatter needs `description` and **must include `disable-model-invocation: true`** -
  the team's dormancy rule: skill descriptions never load into ordinary sessions, and workflows
  are chained by reading the routed skill's file, not via the Skill tool). The plugin loads the
  whole skills directory.
- **Template** - add `docs/templates/<name>.md` carrying the document-control header
  (id / version / revision-history / owner / status / classification / as-of) defined in
  `docs/WAYS-OF-WORKING.md`, and reference it from the skill that produces it.
- **Artifacts** are authored in Markdown and rendered to standalone HTML with
  `python -m scripts.render_html` - produce both `.md` and `.html`.

## Developing in this repo: don't double-load the roster

If you register this repo as a **local directory marketplace** (`/plugin marketplace add
/path/to/virtual-surv-IT`), every session inside the repo loads the team **twice**: once bare
from project scope (`.claude/agents/`, `.claude/skills/`) and once namespaced
(`compliance-surveillance-team:...`) from the auto-loaded plugin manifest. Directory-source
marketplaces load in place whenever the cwd is the plugin repo, and `enabledPlugins` does not
suppress them - so the duplicate roster sits in context on every session here.

Don't fix this by moving the agent/skill files out of `.claude/`: repo-as-project mode (the
no-install path), the hand-pick install instructions, and the bundled-script resolution rule
(`$CLAUDE_SKILL_DIR/../../../scripts/`, see `docs/team-operating-guide.md` §Run mode) all
depend on the current layout. Instead, keep no standing local-directory registration of this
repo:

- remove it if present: `/plugin marketplace remove virtual-surv-it` (typed by you - `/plugin`
  is interactive), then restart the session;
- to test **plugin mode** from a foreign project, use `claude --plugin-dir
  /path/to/virtual-surv-IT` there (temporary, not saved), or add the marketplace **from
  GitHub** in that project. Consumer installs are unaffected either way - they only ever load
  the one namespaced copy.

## Safety hooks

`.claude/hooks/guard-raw-data.py` (blocks raw-data reads), `guard-code-execution.py` (gates
code execution) and `guard-consent-writes.py` (blocks model writes of the consent marker,
settings and the hooks themselves) are security controls. Their wiring is duplicated by design
between `hooks/hooks.json` (plugin scope) and `.claude/settings.json` (project scope) and the
two must stay byte-identical - `tests/test_hooks_in_sync.py` enforces this. **Editing the hook
files from inside a Claude session requires the human-set `CST_ALLOW_CONFIG_EDIT=1`** (the
consent-write guard blocks model edits of them - by design). See `docs/house-rules.md` and
`docs/adr/ADR-002`.

## Conventions

- House style is **ASCII hyphens**, not en/em dashes, in committed text.
- Keep `CLAUDE.md` lean (always-on context); put detail in `docs/`.
