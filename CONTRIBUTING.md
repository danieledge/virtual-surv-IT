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
