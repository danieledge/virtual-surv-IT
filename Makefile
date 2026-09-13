# Housekeeping targets (2026-09-13 framework review, steps 2.6 and 5.3). Everything here is
# local and deletes only generated or backup files; nothing touches tracked content.

.PHONY: clean prune-eval-runs check

## Remove backups, caches and stale generated trees that accumulate on a dev box.
clean:
	rm -f .claude/settings.json.bak .claude/settings.json.bak-* .claude/*.bak .claude/*.bak-* hooks/hooks.json.bak-*
	rm -rf .guard-hardening-backup-* .coverage artifacts legacy-artifacts poc
	find . -name __pycache__ -type d -not -path './.venv/*' -not -path './vendor/*' -prune -exec rm -rf {} +
	@echo "clean: backups, caches and stale trees removed (evals/runs: make prune-eval-runs)"

## Apply the eval-run retention rule (dry run first: python scripts/prune_eval_runs.py).
prune-eval-runs:
	.venv/bin/python scripts/prune_eval_runs.py --apply

## The fast local gate: lint, references, house style, orphans, PDFs.
check:
	.venv/bin/ruff check scripts/ .claude/hooks/ rules/ tests/ install_helper.py
	.venv/bin/python -m scripts.validate_references --orphans --strict-orphans
	.venv/bin/python scripts/check_pdf_links.py
	.venv/bin/python -m pytest -q tests/test_house_style.py tests/test_docs_consistency.py
