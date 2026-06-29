# Contributing

Thanks for helping improve the Compliance Surveillance Engineering virtual team. This is a
Claude Code plugin (agents + skills + docs + a small Python tooling package). The notes below
keep contributions consistent with the project's own standards.

## Ground rules (non-negotiable)

- **Never commit real data or secrets.** All examples and tests use **synthetic or masked** data
  (`CLAUDE.md` §5). `data/raw/` is git-ignored and blocked from agents by a hook — keep it that way.
- **No hard-coded credentials.** Read from the environment (e.g. `MASKING_KEY`). CI runs gitleaks.
- **Detection logic must stay explainable and auditable** — documented thresholds with a rationale
  and tuning date, and a traceable link from alert → logic → obligation (`CLAUDE.md` §4).

## Local setup

```bash
pip install -r requirements-dev.txt        # pytest, PyYAML, Markdown, bleach, pre-commit
pip install -r requirements-review.txt      # optional: ruff, bandit, mypy, … (sharpen reviews)
pre-commit install                          # optional but recommended
```

## Before you open a PR

Run what CI runs:

```bash
pytest                                       # all unit tests must pass
python -m scripts.validate_masking           # masking safety + detection fidelity
python -m scripts.validate_manifest          # declared agents/skills resolve
ruff check scripts/ .claude/hooks/ rules/ tests/
bandit -r scripts/ .claude/hooks/ -q
shellcheck scripts/*.sh scripts/git-hooks/pre-commit scripts/git-hooks/pre-push
```

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
- **The two safety hooks are a separate thing** from this tooling - they run *inside Claude Code*
  to block raw-data reads and un-consented code execution. They're explained in
  `docs/house-rules.md` and threat-modelled in `docs/adr/ADR-002`.

## Adding or changing components

- **Agent** — add `.claude/agents/<slug>.md` with frontmatter (`name`, `description`, `model`,
  `tools`). Advisory/read-only agents must **not** hold `Write`/`Edit` (`CLAUDE.md` §7). Then
  **register it in `.claude-plugin/plugin.json`** (`agents` array) — `validate_manifest` enforces
  that the declared set matches the files on disk.
- **Model tier** — if you set or change an agent's `model:`, update the tier table in
  **`docs/agent-design.md`** in the same change. The two are expected to stay in sync.
- **Skill** — add `.claude/skills/<name>/SKILL.md` (frontmatter `name` matching the dir +
  `description`). The plugin loads the whole skills directory.
- **Template** — add `docs/templates/<name>.md` carrying the document-control header
  (id / version / revision-history / owner / status / classification / as-of) defined in
  `docs/WAYS-OF-WORKING.md`, and reference it from the skill that produces it.
- **Artifacts** are authored in Markdown and rendered to standalone HTML with
  `python -m scripts.render_html` — produce both `.md` and `.html`.

## Safety hooks

`.claude/hooks/guard-raw-data.py` (blocks raw-data reads) and `guard-code-execution.py`
(gates code execution) are security controls. Their wiring is duplicated by design between
`hooks/hooks.json` (plugin scope) and `.claude/settings.json` (project scope) and the two must
stay byte-identical — `tests/test_hooks_in_sync.py` enforces this. See `docs/house-rules.md`.

## Conventions

- House style is **ASCII hyphens**, not en/em dashes, in committed text.
- Keep `CLAUDE.md` lean (always-on context); put detail in `docs/`.
