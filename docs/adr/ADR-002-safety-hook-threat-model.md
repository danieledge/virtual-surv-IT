# ADR-002: Safety-hook threat model and additive hardening

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-002` · Version `0.5` · Status `Accepted (implemented)`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-07-05`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-29 | project review (red-team) | Initial draft |
> | 0.2 | 2026-07-01 | setup audit (user-authorised) | Crash paths fail closed; launcher version probe; launcher no-Python trade-off recorded; rec-7 status corrected |
> | 0.3 | 2026-07-01 | setup audit (user-authorised) | Rec 5 implemented: `guard-consent-writes.py` blocks model writes of the consent marker + settings; consent granting is human-only |
> | 0.3.1 | 2026-07-01 | setup audit (user-authorised) | Live false positive fixed (stderr redirect ≠ marker write); self-protection added: model Write/Edit of `.claude/hooks/*` and `hooks/hooks.json` blocked (Bash stays advisory for these paths); maintenance via `CST_ALLOW_CONFIG_EDIT=1` |
> | 0.4 | 2026-07-02 | human-applied (the consent-write gate blocks model edits of the guards; the user copied the prepared files in) | Exec-guard `_TEAM_ALLOW` accepts the plugin's bundled scripts by path (basename-whitelisted - enables full plugin-mode operation from foreign projects; a hostile file *named* like a team script in a `scripts/` dir would pass: accepted lexical residual). Two live false positives fixed: `make` anchored to segment start (blocked commit messages containing the word), `sh <file>.sh` given a lookbehind (multi-file `shellcheck a.sh b.sh` was blocked). Both guards' block messages now print the absolute marker path from `CLAUDE_PROJECT_DIR`. |
> | 0.4.1 | 2026-07-02 | human-applied (reported from a live Windows plugin install) | Windows correctness: `_TEAM_ALLOW` path separators accept backslashes (`[/\\]` - slash-only regexes blocked `python C:\...\scripts\render_html.py`); the `py` launcher added to the interpreter token (it was invisible to the guard - `py evil.py` was NOT blocked and `py -m scripts.x` was NOT allowed); raw-data marker gains the `data\raw\` backslash variant for Bash string matching. |
> | 0.4.2 | 2026-07-05 | human-applied via `apply-guard-hardening.sh` | Recs 10-13 applied: anchored `pytest`/`unittest`, broader runner list (cargo/swift/bundle exec/jest/vitest/php/julia/lua), consent guard gains read-only `jq` + read-only `git` safe verbs and a `find -exec/-delete` block, raw guard gains a word-bounded case-insensitive marker (no-trailing-slash + case-fold), plugin-mode fail-open comments softened, `data/raw` write-protect + `python3 -m scripts.ingest` twin in settings, `pwsh` allow entry removed. Regression: `tests/test_guard_hardening.py`. |
> | 0.5 | 2026-07-05 | evening setup review + truth audit (PREPARED 2026-07-05; human applies via `apply-guard-fixes.sh`) | Rec 14 recorded (four defects: multi-`.py` launcher false positive, unanchored `pwsh`/`powershell`, `pre-commit` consent-free execution path incl. `.pre-commit-config.yaml` write-protect, pytest allow-entry contradiction); Tier-2 backlog recs 15-16 added (parent-rooted/wildcard Grep vs `data/raw`; secrets deny-protected on `Read` only); staleness fixed (status to Accepted, Context three-hook present, rec 7/8/13 texts, test count 14 to 17, pin-cites, launcher trade-off extended to the consent-write gate). Regression: `tests/test_guard_fixes.py`. |

| | |
|---|---|
| **Status** | Accepted (implemented; open backlog items are recorded below) |
| **Date** | 2026-06-29 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | Obligation: data-safety (CLAUDE.md §5) + static-by-default execution (§7); `docs/house-rules.md` |

## Context

Three always-on PreToolUse hooks are the plugin's headline safety controls:
`.claude/hooks/guard-raw-data.py` (block reads of raw PII under `data/raw/`),
`.claude/hooks/guard-code-execution.py` (block code execution without consent) and, since 0.3,
`.claude/hooks/guard-consent-writes.py` (block the model granting itself execution consent or
editing harness config / the guards themselves). A red-team of the original two was performed.
The finding that frames everything: **the guards are advisory lexical filters, not
enforcement boundaries.** They raise the bar for a *cooperative* agent but stop a *motivated* one
only where the OS `permissions.deny` layer backs them up - and that layer covers `Read`/`Grep`/
`Glob` but leaves the `Bash` tool almost entirely uncovered. The hooks' own docstrings
(`guard-code-execution.py:26-30`, `guard-raw-data.py:14-22`) and `docs/house-rules.md:79-83`
already concede this as accepted residual risk; this ADR records the decision and the hardening
backlog explicitly.

Two structural facts dominate:

- **As of 0.1, `Write`/`Edit` were in neither hook's matcher**, so the model could author a
  script, or write the consent marker itself, then run it through an allowed path. Since 0.3 the
  third hook (`guard-consent-writes.py`, matcher `Write|Edit|MultiEdit|NotebookEdit|Bash`) closes
  the marker/config half of that; the "author a script under `scripts/` and run it via
  `_TEAM_ALLOW`" half remains the deferred rec-5 remainder.
- **`permissions.deny` has zero `Bash(...)` entries** (`.claude/settings.json:4-16`). Every
  Bash-based bypass below has no OS backstop - only the soft hook.

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

- **Positive:** the security posture is documented and accurate; the hardening backlog shrinks the
  *accidental / easy* bypass surface materially; auditors get a truthful control description.
- **Negative / accepted:** the irreducible residual risk (below) remains until a real sandbox or
  filesystem-ACL boundary is added; the backlog is work; some lexical hardening may marginally
  increase false-positive blocks on benign commands (tune with the allow-list).

## Hardening backlog (ranked, additive only)

**Tier 1 - closes the widest holes, lexical:**
1. **Segment-split Bash before matching (both hooks)** - split on `;`, `&&`, `||`, `|`, newlines;
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

**Tier 2 - the OS boundary (`permissions.deny`):**
6. Add absolute-path `Grep`/`Glob` deny variants mirroring `Read`
   (`/*/data/raw/**`, `/**/data/raw/**`).
7. Treat path-less `Grep`/`Glob` as in-scope in the raw guard (search root defaults to cwd, which
   contains `data/raw`; broadened by rec 15), and check the real Grep `glob` param - **the `glob`
   half is done** (the hook reads both `glob` and the legacy `include` since 2026-06-29).
8. Extend the secret denies (`.env`, `*.pem`, `secrets/`) to absolute / non-`./` forms - **done**
   (the absolute-path `Read` deny variants are committed in `.claude/settings.json`). Residual:
   they cover `Read` only - no `Grep`/`Glob` secret denies, and neither guard covers secret reads
   via Bash (rec 16).

**Tier 3 - the only thing that actually contains Bash:**
9. Filesystem ACLs / uid-separation so the agent process cannot open `data/raw/`, or keep raw data
   off the box entirely. This is the real boundary; everything above is belt-and-braces over it.

**Logged 2026-07-05 (setup audit); APPLIED 2026-07-05 by the human via `apply-guard-hardening.sh`
(full suite + ruff green).** The guard logic and `.claude/settings.json` are model-blocked (rec 5 /
house-rule "don't edit the guards"), so these were recorded here and applied by a human maintenance
run, not changed in-session. Regression coverage: `tests/test_guard_hardening.py`.
10. **Plugin-mode backstop is absent, and three fail-open paths still cite it.** A plugin ships
    `hooks/hooks.json` but not a `permissions.deny` list, so in a foreign-project install the
    raw-data *hook* is the sole file-tool control. Yet `guard-raw-data.py` (malformed-JSON exit 0),
    `run-guard.sh` (no-Python exit 0) and the unresolved-launcher case (`sh` exits 127 = non-blocking)
    all fail open citing "the deny list remains the hard boundary" - true only in repo-as-project
    mode. Additive fix: (a) tell installers to recreate the deny entries (done - `docs/house-rules.md`,
    README §safety-hooks); (b) soften those three comments so they don't assert a backstop that may be
    absent. Extends the exec-gate concession in §exit-code-semantics to the raw-data guard.
11. **Consent-write guard false positives (read-only inspection is meant to be allowed).** `git` and
    `jq` are not in `_SAFE_VERB`, so `git check-ignore .claude/.exec-consent` and
    `jq '.x' .claude/settings.json` - pure reads - default-deny, contradicting the docstring. `\bpytest\b`
    and `\bunittest\b` in `guard-code-execution.py` are unanchored, so a commit message or prose
    containing the word blocks (the exact class already fixed for `make`). Additive fixes: anchor
    `pytest`/`unittest` to segment start like `make`; allow read-only `jq`, and read-only `git`
    subcommands only (`git` must **not** be blanket-safe - `git checkout`/`git stash`/`git restore`
    mutate). Accept-or-fix, not silently leave.
12. **Newly-noted lexical bypass classes** (all consistent with the "string-matching is advisory"
    residual, listed so they aren't re-discovered): trailing-slash-free raw markers
    (`cd data/raw && cat *`, `cp -r data/raw /tmp`), `find … -exec sed -i` slipping the safe-verb
    list, a symlinked-`settings.json` two-step (the Write/Edit check is string-only, not realpath),
    case-folded paths on case-insensitive filesystems, and exec-runner misses (`cargo run`,
    `swift run`, `bundle exec`, bare `jest`/`vitest`, `julia`, `lua`, `php <file>.php`,
    interpreter-via-heredoc). Tier-3 (rec 9) is the real containment for all of these.
13. **`settings.json` allow-list vs exec guard contradiction (resolved 2026-07-05,
    `apply-guard-hardening.sh`).** `Bash(pwsh -Command Invoke-ScriptAnalyzer:*)` was allow-listed
    as a static analyser while the exec guard's blanket `\bpwsh\b|\bpowershell\b` blocked every
    pwsh call pre-consent, so the "allowed" analyser could never run without consent. The
    misleading allow entry was removed; PowerShell static analysis runs under the §7 exec gate.
    The same contradiction for the three pytest allow entries is rec 14(d).

**Logged 2026-07-05 (evening setup review + truth audit); PREPARED 2026-07-05, pending human
application via `apply-guard-fixes.sh` (the guards and `.claude/settings.json` are model-blocked,
rec 5 / house rule "don't edit the guards"). Regression tests: `tests/test_guard_fixes.py`
(written to FAIL until the fixes are applied).**
14. **Four defects found live during the 2026-07-05 audits:**
    - **(a) Multi-`.py` launcher false positive.** `_PY` includes bare `py`, so in any command
      naming two `.py` paths the trailing "py" of the first filename parsed as the Windows `py`
      launcher "running" the second - `git diff -- a.py b.py`, `git add` over two rule files,
      multi-file `grep`/`wc` were all reproduced blocking read-only commands during the audits,
      breaking static review over multiple Python files. Third instance of the prose/argument FP
      class this ADR has fixed twice (`make`-in-prose, `shellcheck a.sh b.sh`); same fix shape: a
      negative lookbehind `(?<![\w.-])` so the bare `py` alternative only matches as a standalone
      token. The file-run pattern also gains `(?:\s+-\S+)*` so the versioned launcher form
      `py -3 foo.py` is caught - it previously slipped past unblocked.
    - **(b) Unanchored `pwsh`/`powershell`.** `\bpwsh\b` blocked the word inside a grep pattern
      or prose (observed live on a benign grep, 2026-07-05). Fix: anchored to segment start with
      optional env-var prefixes, exactly as `pytest` was anchored (rec 11).
    - **(c) `pre-commit` was a consent-free execution path.** `Bash(pre-commit run:*)` was
      allow-listed, no `_EXEC_PATTERNS` entry matched pre-commit, and `.pre-commit-config.yaml`
      was model-writable - a session could add `entry: <anything>, language: system` and execute
      it pre-consent via `git commit` or `pre-commit run`. Fix: an anchored `pre-commit` exec
      pattern, `.pre-commit-config.yaml` added to the consent guard's protected set
      (write-protect only; read-only inspection stays allowed), and the allow entry removed.
      **Adjacent unfixed class (recorded residual):** git external-diff/merge drivers -
      `.git/config` is model-writable and a configured external driver executes on plain
      `git diff`/merge; same shape as (c), no fix in this pass.
    - **(d) pytest allow entries repeated the rec-13 contradiction.** `Bash(pytest:*)`,
      `Bash(python -m pytest:*)` and `Bash(python3 -m pytest:*)` were allow-listed while the exec
      guard blocks all three pre-consent, so the entries could never take effect and misled
      readers of `settings.json`. Removed; the exec gate (consent marker / `CST_ALLOW_EXEC`) is
      the control either way.

**Tier-2 backlog additions (logged 2026-07-05 from the same audit; NOT fixed in this pass):**
15. **Parent-rooted / wildcard-spelled `Grep` reaches `data/raw` content.** A `Grep` rooted at a
    parent directory (`path="data"`, path-less, or wildcard spellings like `data/r*/**`) reads
    `data/raw` content past both the hook's path checks and the literal deny patterns - broader
    than the path-less `Grep`/`Glob` deferral recorded under rec 7, and in plugin mode there is
    no deny list at all (rec 10).
16. **Secrets are deny-protected on `Read` only.** `Grep(pattern="KEY=", path=".env")` egresses
    secret lines; there are no `Grep`/`Glob` deny entries for `.env` / `*.pem` / `secrets/`, and
    neither guard checks secret paths. Extends rec 8's residual.

## Hook exit-code semantics and the launcher (added 0.2)

Claude Code treats hook **exit 2 as block, exit 0 as allow, and *any other* exit code -
including 1, the conventional Unix failure code - as a NON-blocking error: the tool call
proceeds.** That makes every *crash* path in a guard a fail-open path. The 2026-07-01 setup
audit found two concrete instances, both fixed the same day (user-authorised, per Decision 2):

1. **Import-time crash on older Pythons.** `guard-code-execution.py` used PEP 604 (`str | None`)
   and both guards used PEP 585 (`list[str]`) annotations, which raise at def-time on
   Python ≤ 3.9 - traceback → exit 1 → every command proceeds, gate silently inert. Fixed with
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
   gate is inert - and so is the **consent-write gate** (noted 2026-07-05): it also has no
   `permissions.deny` backstop, so on a Python-less host model writes of the consent marker,
   `settings.json` and the guards themselves would proceed unguarded.
   Accepted for now because hard-blocking every tool call on a Python-less host
   would brick the session for a control that is advisory-by-design (see Decision 1); revisit if
   rec 5 lands or a `Bash()` deny becomes viable.

## Alternatives considered

- **Represent the hooks as a preventive control / "good enough".** Rejected: it misrepresents the control to an
  auditor and gives false comfort; a motivated actor bypasses the lexical layer trivially.
- **Try to make the lexical matcher complete.** Rejected as impossible: string-matching arbitrary
  shell is undecidable (env indirection `X=python;$X f`, `$(…)`, `eval`, `base64|sh`, heredocs).
- **Remove the hooks (rely only on `permissions.deny` + discipline).** Rejected: the hooks add
  real value as consent-recording and a cooperative-agent nudge, and cover tool forms the deny
  list misses.

## Residual risk (cannot be closed lexically)

After Tiers 1-2, the irreducible core remains: env-var indirection, command substitution, `eval`,
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
| Implementation status | **partially implemented (2026-06-29, updated 2026-07-01).** Done: Tier-1 recs 1-4 in `guard-code-execution.py` (segment-split, anchored `_TEAM_ALLOW`, block `python -c`/`-`/`node -e`/`ruby -e`/`perl -e`/`php -r`/`bash -c`, versioned-interpreter fix, broader runners), backed by 7 new `tests/test_guards.py` cases; Tier-2 rec 6 (absolute-path `Grep`/`Glob` deny variants in `.claude/settings.json`); Tier-2 rec 7 **first half** (the raw guard now checks the real Grep `glob` param alongside the legacy `include`, `guard-raw-data.py`); crash-path fail-closed + launcher version probe (see §exit-code semantics above, 2026-07-01). Tier-1 rec 5 **implemented (2026-07-01)**: `guard-consent-writes.py` (new hook, dual-wired in `hooks/hooks.json` + `.claude/settings.json`, matcher `Write|Edit|MultiEdit|NotebookEdit|Bash`) blocks model writes of `.claude/.exec-consent` and `.claude/settings*.json`; deletion + read-only inspection allowed; human override `CST_ALLOW_CONFIG_EDIT`; 17 tests in `tests/test_guard_consent.py`; `/engage` and `/demo` now have the **user** create the marker (`! touch .claude/.exec-consent`). *Rec-5 remainder deferred:* the "warn on new files under `scripts/`" half (a new script written by the model becomes runnable via `_TEAM_ALLOW`; needs `permissionDecision: ask` semantics to avoid breaking legitimate build deliverables). **Also deferred:** Tier-2 rec 7 second half (path-less `Grep`/`Glob`; broadened by rec 15), rec 8's `Grep`/`Glob` half (rec 16), Tier-3 (the OS/ACL boundary). Recs 10-13 applied 2026-07-05 (`apply-guard-hardening.sh`, `tests/test_guard_hardening.py`); rec 14 PREPARED 2026-07-05 pending `apply-guard-fixes.sh` (`tests/test_guard_fixes.py`). |
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
