# Eval baseline — 0.32.0 (dev → main promotion record)

Scope: deterministic-only
Date: 2026-07-29
Method: pytest + the deterministic mechanical gates only, promoted on an explicit user
decision (the human approver chose the deterministic path at the promotion gate). This
release's prompt-surface change is convention text, not behaviour: the operating guide gains
the AI-identity rule (🤖 + Virtual Surveillance IT on roster names; agent and human sign-offs
on separate lines) and its auto-fix entry. The enforcement is mechanical and unit-tested
(`AGENT-UNMARKED` / `AGENT-HUMAN-COMBINED` in `check_artifacts`), not dependent on prompt
behaviour. The ADR-009 extensions feature also ships in this release; its scripts are
structurally inert without a company `team-extensions.md` and are covered by 12 unit tests.

## Evidence

- Full pytest suite green: 648 passed, 12 skipped (includes 7 new AI-identity gate tests and
  the 12 extensions tests). `validate_manifest` clean.
- ruff lint + format clean across the CI scope; bandit 0 findings; shellcheck clean; the
  staged and live guard-hook copies remain byte-identical after the format sweep (parity
  tests green).
- Windows runner failures fixed (UTF-8 test reads, slug assertion, win32 fixture skip) - the
  full CI matrix is expected green for the first time since 0.31.0 landed.

## Limitations (honest scope)

- **No live golden-slice run.** The extensions feature's planned live golden case and the
  human guard-apply (`scripts/apply-guard-exec-allow.sh`, ADR-002 rec 5) are deferred to the
  next full-scope baseline. Until then, 0.31.0 remains the live-orchestration evidence
  record; extensions behaviour under live prompting is unevidenced.
- Deterministic-only is documented for no-prompt-change patches; this release's
  operating-guide edit is a prompt-file change promoted under an explicit user override,
  recorded here for the audit trail.

## Verdict

**PASS for promotion (deterministic scope, user-approved override)** — mechanical gates
green across the board; live evidence carried by 0.31.0 pending the next golden slice.
