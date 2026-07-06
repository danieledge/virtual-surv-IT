# Security Policy

This project is a Claude Code plugin for building **compliance surveillance** solutions. It
deals with a regulated domain, so data-safety and code-safety are first-class concerns.

## Reporting a vulnerability

Please report security issues **privately** - do not open a public issue for a vulnerability.

- Use GitHub's **private vulnerability reporting** ("Report a vulnerability" on the Security tab), or
- email the maintainer (Daniel Edge).

Include a description, affected files/versions, reproduction steps, and impact. We aim to
acknowledge within a few days and will coordinate a fix and disclosure timeline with you.

## Scope - what to look for

This is a plugin, not a hosted service. The security-relevant surfaces are the three guard hooks
(always-on PreToolUse) plus the data-handling scripts:

- **The data-safety guard** (`.claude/hooks/guard-raw-data.py`) - blocks tool calls that target
  raw, un-masked data under `data/raw/`, so PII/MNPI (personal data / material non-public
  information) cannot reach the model provider as prompt context (`CLAUDE.md` §5). Bypasses that let raw data reach an agent are in scope.
- **The code-execution gate** (`.claude/hooks/guard-code-execution.py`) - keeps code review
  *static by default*; execution requires explicit consent (`.claude/.exec-consent`) or
  `CST_ALLOW_EXEC` (`CLAUDE.md` §7). Note: as documented in the hook, string-matching of shell
  commands is **advisory** - a strong default, not a sandbox. In repo-as-project mode the OS-level
  `permissions.deny` list backs the file-tool blocks; a plugin install ships the hook but not that
  deny list (see `docs/house-rules.md`), so the real boundary is `data/raw/` being git-ignored and
  masking-at-source.
- **The consent-write gate** (`.claude/hooks/guard-consent-writes.py`) - stops the model granting
  itself execution consent or editing harness config: it blocks model-driven writes to
  `.claude/.exec-consent`, `.claude/settings.json` and the guard hooks themselves, so consent stays
  human-only (`CLAUDE.md` §7, ADR-002 rec 5). Bypasses that let the model open the gate or neuter a
  guard are in scope.
- **The HTML renderer** (`scripts/render_html.py`) - sanitises artifact HTML with `bleach` and
  fails closed if `bleach` is unavailable, since artifacts may contain untrusted content.
- **The masking pipeline** (`scripts/ingest.py`) - tokenises/redacts PII; the key comes only
  from `MASKING_KEY` (no insecure default).

## Handling data and secrets

- All examples, fixtures and tests use **synthetic or masked** data only.
- Never commit real records, credentials, or connection strings. `data/`, `.env*`, `*.pem`,
  `*.key`, `secrets/` and `.claude/.exec-consent` are git-ignored; CI runs gitleaks and a
  raw-data check.
- "Masked" is not "anonymous" - pseudonymised data is still personal data. Prefer fully
  synthetic data for anything leaving a governed environment.

## Supported versions

This is an evolving POC; security fixes target the latest release (see `CHANGELOG.md`).
