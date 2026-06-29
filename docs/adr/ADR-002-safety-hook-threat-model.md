# ADR-002: Safety-hook threat model and additive hardening

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-002` · Version `0.1` · Status `Draft`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-06-29`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-29 | project review (red-team) | Initial draft |

| | |
|---|---|
| **Status** | proposed |
| **Date** | 2026-06-29 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | Obligation: data-safety (CLAUDE.md §5) + static-by-default execution (§7); `docs/house-rules.md` |

## Context

Two always-on PreToolUse hooks are the plugin's headline safety controls:
`.claude/hooks/guard-raw-data.py` (block reads of raw PII under `data/raw/`) and
`.claude/hooks/guard-code-execution.py` (block code execution without consent). A red-team of
both was performed. The finding that frames everything: **both are advisory lexical filters, not
enforcement boundaries.** They raise the bar for a *cooperative* agent but stop a *motivated* one
only where the OS `permissions.deny` layer backs them up — and that layer covers `Read`/`Grep`/
`Glob` but leaves the `Bash` tool almost entirely uncovered. The hooks' own docstrings
(`guard-code-execution.py:24-28`, `guard-raw-data.py:14-22`) and `docs/house-rules.md:124-128`
already concede this as accepted residual risk; this ADR records the decision and the hardening
backlog explicitly.

Two structural facts dominate:

- **`Write`/`Edit` are not in either hook's matcher** (`hooks/hooks.json:5,14`;
  `.claude/settings.json` matchers are `Read|Grep|Glob|Bash` and `Bash`). So the model can author
  a script, or write the consent marker itself, then run it through an allowed path.
- **`permissions.deny` has zero `Bash(...)` entries** (`.claude/settings.json:4-16`). Every
  Bash-based bypass below has no OS backstop — only the soft hook.

> **Live posture note:** `.claude/.exec-consent` currently exists in this repo (created for
> plugin self-development; git-ignored, not committed). While present, `_exec_authorised()`
> returns true and the execution gate is intentionally **open for this repo**. Remove the marker
> to restore the gate.

## Decision

1. **Represent the hooks accurately.** They are a *defence-in-depth and consent-recording* layer
   and a strong nudge for a cooperative agent. They must **not** be represented to an auditor as a
   control that *prevents* raw-data egress or unauthorised execution by a determined actor.
2. **Adopt the ranked, additive hardening backlog below** (no change to either hook's core intent;
   string-matching stays advisory). Hook-code changes are gated on the team's own review process.
3. **Name the real boundary.** The only mechanism that actually contains a hostile Bash command is
   the OS/filesystem: least-privilege file permissions so the agent's process cannot read
   `data/raw/`, or keeping raw data off the host entirely. The "`permissions.deny` is the real
   boundary" claim in `guard-raw-data.py:18-19` holds for `Read`/`Grep`/`Glob` but **not for Bash**.

## Consequences

- **Positive:** the security posture is documented and honest; the hardening backlog shrinks the
  *accidental / easy* bypass surface materially; auditors get a truthful control description.
- **Negative / accepted:** the irreducible residual risk (below) remains until a real sandbox or
  filesystem-ACL boundary is added; the backlog is work; some lexical hardening may marginally
  increase false-positive blocks on benign commands (tune with the allow-list).

## Hardening backlog (ranked, additive only)

**Tier 1 — closes the widest holes, lexical:**
1. **Segment-split Bash before matching (both hooks)** — split on `;`, `&&`, `||`, `|`, newlines;
   evaluate each segment independently so `_TEAM_ALLOW` exempts only the matching *segment*, not
   the whole line (kills the "allowed-substring-anywhere" bypass) and the raw guard inspects each
   piped sub-command.
2. **Anchor `_TEAM_ALLOW`** to segment start instead of `.search()` anywhere
   (`guard-code-execution.py:78-81,116`).
3. **Block inline-code / stdin forms and drop the `-c` exemption** (`:72-73`): `python … -c`,
   `python … -` (stdin/heredoc), `bash -c`, `sh -c`, `zsh -c`, `node -e`, `ruby -e`, `perl -e`,
   `deno eval`, `php -r`.
4. **Fix the interpreter regex** `python3?` → `python(3(\.\d+)?)?` (so `python3.11 evil.py` is
   caught) and broaden the runner list: `uv run`, `poetry run`, `pipenv run`, `tox`, `nox`,
   `make`, `just`, `docker run`, `pnpm`, `tsx`, `Rscript`, `source`/`. file`.
5. **Gate `Write`/`Edit`** with a new PreToolUse matcher that blocks writing/editing
   `.claude/.exec-consent` and `.claude/settings*.json` (closes consent self-grant) and warns on
   new files under `scripts/` (which `_TEAM_ALLOW` would then run).

**Tier 2 — the OS boundary (`permissions.deny`):**
6. Add absolute-path `Grep`/`Glob` deny variants mirroring `Read`
   (`/*/data/raw/**`, `/**/data/raw/**`).
7. Treat path-less `Grep`/`Glob` as in-scope in the raw guard (search root defaults to cwd, which
   contains `data/raw`), and check the real Grep `glob` param (the hook currently reads `include`,
   `guard-raw-data.py:95`, which is a dead check).
8. Extend the secret denies (`.env`, `*.pem`, `secrets/`) to absolute / non-`./` forms; note
   neither guard covers secret reads via Bash.

**Tier 3 — the only thing that actually contains Bash:**
9. Filesystem ACLs / uid-separation so the agent process cannot open `data/raw/`, or keep raw data
   off the box entirely. This is the real boundary; everything above is belt-and-braces over it.

## Alternatives considered

- **Represent the hooks as a preventive control / "good enough".** Rejected: dishonest to an
  auditor and false comfort; a motivated actor bypasses the lexical layer trivially.
- **Try to make the lexical matcher complete.** Rejected as impossible: string-matching arbitrary
  shell is undecidable (env indirection `X=python;$X f`, `$(…)`, `eval`, `base64|sh`, heredocs).
- **Remove the hooks (rely only on `permissions.deny` + discipline).** Rejected: the hooks add
  real value as consent-recording and a cooperative-agent nudge, and cover tool forms the deny
  list misses.

## Residual risk (cannot be closed lexically)

After Tiers 1–2, the irreducible core remains: env-var indirection, command substitution, `eval`,
`base64 | sh`, heredocs, and dynamic path assembly can always reconstruct a blocked operation from
unblocked tokens. For **execution**, only the `CST_ALLOW_EXEC` env-var path (which the model cannot
set for the hook subprocess) plus a real sandbox on synthetic data and trusted-code discipline is
sound; the marker file remains soft until Write/Edit is gated (rec 5). For **raw data**, only
filesystem permissions / not-on-box (rec 9) actually contain a hostile Bash command. This matches
the accepted-residual-risk notes already in the hooks and `docs/house-rules.md`.

## Implementation status & follow-up

| Item | Detail |
|------|--------|
| Implementation status | **partially implemented (2026-06-29).** Done: Tier-1 recs 1-4 in `guard-code-execution.py` (segment-split, anchored `_TEAM_ALLOW`, block `python -c`/`-`/`node -e`/`ruby -e`/`perl -e`/`php -r`/`bash -c`, versioned-interpreter fix, broader runners), backed by 7 new `tests/test_guards.py` cases; Tier-2 rec 6 (absolute-path `Grep`/`Glob` deny variants in `.claude/settings.json`). **Deferred:** Tier-1 rec 5 (gate `Write`/`Edit` on the consent marker / settings - needs a new hook + dual wiring), Tier-2 recs 7-8, Tier-3 (the OS/ACL boundary). |
| Implementing agent / team | `platform-engineer` (hooks + settings), human approver for the OS/ACL boundary |
| Target completion | Tier-1 rec 5 next; Tier-3 is a deployment-guidance item |
| Follow-up actions | implement the `Write`/`Edit` consent-marker gate (rec 5); add Tier-2 recs 7-8; document the Tier-3 filesystem boundary in deployment guidance; `tests/test_guards.py` is the regression net |
| Linked tickets / PRs | - |

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
