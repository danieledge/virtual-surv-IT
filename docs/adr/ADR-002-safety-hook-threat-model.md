# ADR-002: Safety-hook threat model and additive hardening

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-002` · Version `0.2` · Status `Draft`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-07-01`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-29 | project review (red-team) | Initial draft |
> | 0.2 | 2026-07-01 | setup audit (user-authorised) | Crash paths fail closed; launcher version probe; launcher no-Python trade-off recorded; rec-7 status corrected |
> | 0.3 | 2026-07-01 | setup audit (user-authorised) | Rec 5 implemented: `guard-consent-writes.py` blocks model writes of the consent marker + settings; consent granting is human-only |
> | 0.3.1 | 2026-07-01 | setup audit (user-authorised) | Live false positive fixed (stderr redirect ≠ marker write); self-protection added: model Write/Edit of `.claude/hooks/*` and `hooks/hooks.json` blocked (Bash stays advisory for these paths); maintenance via `CST_ALLOW_CONFIG_EDIT=1` |

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

> **Live posture note (updated 0.3):** `.claude/.exec-consent` does not currently exist in this
> repo - the gate is closed. Since 0.3 the model **cannot create it**: `guard-consent-writes.py`
> (rec 5) blocks Write/Edit/Bash writes of the marker and of `.claude/settings*.json`. Consent is
> granted only by the human (`! touch .claude/.exec-consent`, a terminal, or `CST_ALLOW_EXEC=1`);
> the model may still *delete* the marker (closing the gate is fail-safe) and read it. The
> maintenance override for deliberate config-editing sessions is the human-set
> `CST_ALLOW_CONFIG_EDIT=1`. This was demonstrated live on 2026-07-01: the guard blocked the very
> session that authored it from writing the marker.
>
> **On session-scoping (considered, superseded):** stamping the marker with a session id (so
> parallel same-project sessions don't inherit each other's consent) was considered alongside
> rec 5, but a human-created marker carries no session identity to verify, and the stronger
> property - *no model can open the gate at all* - makes the marker an explicit human, per-project
> decision. Accepted residual: consent remains project-scoped and persists until the human (or a
> "No" at intake) removes it; parallel sessions in the same project share it *by human choice*.

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

## Hook exit-code semantics and the launcher (added 0.2)

Claude Code treats hook **exit 2 as block, exit 0 as allow, and *any other* exit code —
including 1, the conventional Unix failure code — as a NON-blocking error: the tool call
proceeds.** That makes every *crash* path in a guard a fail-open path. The 2026-07-01 setup
audit found two concrete instances, both fixed the same day (user-authorised, per Decision 2):

1. **Import-time crash on older Pythons.** `guard-code-execution.py` used PEP 604 (`str | None`)
   and both guards used PEP 585 (`list[str]`) annotations, which raise at def-time on
   Python ≤ 3.9 — traceback → exit 1 → every command proceeds, gate silently inert. Fixed with
   `from __future__ import annotations`; both guards additionally wrap `main()` so **any**
   unexpected exception now exits 2 (fail closed). The deliberate exit-0 for a malformed
   (non-JSON) payload is retained and now covered by regression tests, as is the
   valid-JSON-but-not-a-dict crash path (`tests/test_guards.py`).
2. **The launcher's interpreter population.** `run-guard.sh` (added after 0.1; not previously
   recorded here) tries `python3`, `python`, `py` and now **version-probes for ≥ 3.9**
   (`Path.is_relative_to`) before exec'ing, skipping interpreters that would crash at runtime.
   **Recorded trade-off:** if *no* suitable Python exists, the launcher exits 0 (allow). For the
   raw-data guard the `permissions.deny` list remains the backstop; **for the execution gate
   there is no backstop** (no `Bash()` deny entries), so on a Python-less host the execution
   gate is inert. Accepted for now because hard-blocking every tool call on a Python-less host
   would brick the session for a control that is advisory-by-design (see Decision 1); revisit if
   rec 5 lands or a `Bash()` deny becomes viable.

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
sound; since 0.3 the marker file is **no longer model-writable** (rec 5, `guard-consent-writes.py`) -
its Bash rules are still lexical/advisory like the other guards, but the Write/Edit path check is a
strong control. For **raw data**, only
filesystem permissions / not-on-box (rec 9) actually contain a hostile Bash command. This matches
the accepted-residual-risk notes already in the hooks and `docs/house-rules.md`.

## Implementation status & follow-up

| Item | Detail |
|------|--------|
| Implementation status | **partially implemented (2026-06-29, updated 2026-07-01).** Done: Tier-1 recs 1-4 in `guard-code-execution.py` (segment-split, anchored `_TEAM_ALLOW`, block `python -c`/`-`/`node -e`/`ruby -e`/`perl -e`/`php -r`/`bash -c`, versioned-interpreter fix, broader runners), backed by 7 new `tests/test_guards.py` cases; Tier-2 rec 6 (absolute-path `Grep`/`Glob` deny variants in `.claude/settings.json`); Tier-2 rec 7 **first half** (the raw guard now checks the real Grep `glob` param alongside the legacy `include`, `guard-raw-data.py`); crash-path fail-closed + launcher version probe (see §exit-code semantics above, 2026-07-01). Tier-1 rec 5 **implemented (2026-07-01)**: `guard-consent-writes.py` (new hook, dual-wired in `hooks/hooks.json` + `.claude/settings.json`, matcher `Write|Edit|MultiEdit|NotebookEdit|Bash`) blocks model writes of `.claude/.exec-consent` and `.claude/settings*.json`; deletion + read-only inspection allowed; human override `CST_ALLOW_CONFIG_EDIT`; 14 tests in `tests/test_guard_consent.py`; `/engage` and `/demo` now have the **user** create the marker (`! touch .claude/.exec-consent`). *Rec-5 remainder deferred:* the "warn on new files under `scripts/`" half (a new script written by the model becomes runnable via `_TEAM_ALLOW`; needs `permissionDecision: ask` semantics to avoid breaking legitimate build deliverables). **Also deferred:** Tier-2 rec 7 second half (path-less `Grep`/`Glob`), rec 8, Tier-3 (the OS/ACL boundary). |
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
