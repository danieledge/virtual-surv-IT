# The safety model - one page, per channel

What the safety controls actually guarantee, channel by channel, in one place. The claims
below are sourced from the README (safety hooks, handling real data, known issues),
[`SECURITY.md`](../SECURITY.md) and ADR-002;
this page adds no new claims and strengthens none. Where a telling elsewhere is shorter,
this page is the reference.

The three guards are `.claude/hooks/guard-raw-data.py` (no agent read of
`data/raw/` - **always on, in every session**: data protection never follows invocation),
`guard-code-execution.py` (no execution of the code under review without human consent -
**armed only in sessions that invoked the team** since 2026-08-17, keyed on the
`VSIT/engagements/.team-session.json` stamp `/engage` step 0 writes; a dormant session runs its
own tests as plain Claude Code) and `guard-consent-writes.py` (the model cannot grant
itself consent or edit the harness config - the consent marker, hook files, git execution
config and the session stamp stay write-protected **in every session**, since a dormant
session must not pre-forge or disarm what a later engaged session inherits; only the
`settings*.json` tier is scoped to team-invoked sessions). A hook payload carrying no
session id cannot be told apart from an engaged session, and the scoped gates then fail
toward ARMED - the safety direction. They are wired in both `hooks/hooks.json` (plugin install) and
`.claude/settings.json` (repo as project), and a test keeps the two copies identical. A
guard that crashes exits 2 and blocks (fail closed); two limits are deliberate and
documented in ADR-002: a malformed payload or a host with no Python at all leaves the
guards inert, which is exactly why the OS-level backstop below matters.

## Confidence, per channel

| Channel | Control | Confidence statement |
|---|---|---|
| File-read tools (`Read`/`Grep`/`Glob`), **repo opened as project** | The raw-data guard hook, backed by the OS-level `permissions.deny` entries in `.claude/settings.json` | The strongest channel: the hook fires and the deny list backs it, so the block on `data/raw/` genuinely holds even if the hook is inert. |
| File-read tools, **plugin install into a foreign project** | The guard hook alone | A plugin can carry hooks but not a `permissions.deny` list, so the hook is the sole file-tool control. Installers who want the belt-and-braces backstop copy the `Read`/`Grep`/`Glob` `data/raw/**` deny entries into their own project's `.claude/settings.json` ([`docs/house-rules.md`](house-rules.md)). |
| **Bash** (shell commands) | Lexical checks over the command text, in all three guards | Lexically guarded, **not a sandbox**: there is no `Bash(...)` deny backstop, and string-matching is trivially dodged by a determined actor (indirection, variables, subshells - the bypass classes are enumerated in ADR-002). A strong default and a consent record for a cooperative agent; the real boundary for shell is OS file permissions and keeping raw data off the box. |
| **Write/Edit** (file writes) | The consent-write gate | The model is blocked from writing or editing the consent marker, `settings*.json` and the guard hook files themselves, so a confused or prompt-injected model cannot authorise itself or rewrite its own guardrails. Hook maintenance needs the human-set `CST_ALLOW_CONFIG_EDIT=1`. The Bash channel caveat above applies to shell-driven writes. |
| **Execution** (running code under review) | The code-execution gate, opened only by a human | Static by default. Execution needs the `.claude/.exec-consent` marker or `CST_ALLOW_EXEC=1`, and both are human-only: the model cannot create the marker (the consent-write gate blocks it) and the environment variable lives where the model cannot reach. The intake "yes" is intent, not the grant. The team's own vendored `scripts/` tooling is allow-listed and runs consent-free. |

## The honest closing line

The guards are a real control for a **cooperative** agent, not a boundary against an
**adversarial** one (README known issues; ADR-002 records this as accepted residual, with
the hardening backlog). The real boundary is architectural: `data/raw/` is git-ignored, a
CI job fails on tracked data files, masking happens at source (`scripts/ingest.py`, keyed,
no insecure default) or data is fully synthetic - and the strongest posture of all is
keeping real data off the machine entirely.
