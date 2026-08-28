# Run mode & the bundled scripts - full detail

> Deferred from `docs/team-operating-guide.md` (open-core split, token plan Phase 1,
> 2026-08-18). The open-core keeps the resolve-once rule and the probe's `INTERPRETER=` /
> `PLUGIN_ROOT=` contract; **read this file when** running in plugin mode against a foreign
> project, when a bundled script/doc/template path needs resolving beyond those two words,
> when `bash` is absent, or when a document input (PDF/DOCX/XLSX/CSV) arrives. The shared
> short statement is `.claude/skills/.shared/run-mode.md`.

**Interpreter re-resolution** is only for a direct skill invocation with no probe in session,
and then in the platform-aware order `run-guard.sh` itself uses: an existing
`VSIT/local/guard-interpreter` cache first, then `python`, `py`, `python3` on Windows (where a
`python3` that resolves to the Microsoft Store stub costs a multi-second hang) and `python3`,
`python`, `py` everywhere else.

**Bundled docs and templates resolve exactly like the scripts.** Every `docs/...` and
`docs/templates/...` reference in a skill or agent means the TEAM's copy: the working repo's
own file when present, else `$PLUGIN_ROOT/docs/...` (the root the step-0 probe printed).
**A template or handbook doc absent from the WORKING repo is never a blocker and never a
reason to refuse a deliverable** - resolve the plugin copy, and every delegation brief
carries the resolved absolute paths (engage step 5). If a bundled doc is genuinely
unreachable, produce the deliverable to the documented structure anyway and FLAG that the
template was unavailable (live failure 2026-07-28: an FSD was refused "because there is no
FSD document" in a plugin install - the template was in the plugin all along).

**Invoke with ONE consistent spelling - always forward slashes, always double quotes.** Git
Bash on Windows accepts forward-slash paths (`C:/Users/...`), so never emit backslash paths or
switch quote styles between invocations: every distinct spelling of the same command becomes
another permission prompt for the user, and another auto-saved rule (mixed-separator and
mixed-quote saved rules are flagged as invalid by Claude Code's validator - a real user hit
exactly this). One spelling → one approval → one clean rule.

**Don't assume `bash` exists either.** On Windows the shell tool runs Git Bash (Claude Code
requires it there; the hosting terminal being PowerShell doesn't change that) - but if a
`bash --version` probe fails at step 0, skip the `.sh` helpers (`check-review-tools.sh`) and
call the analysers directly (`ruff`/`mypy`/etc. are on PATH as executables); say what was
skipped. The Python helper scripts need only `<python>`, never bash:

- **Repo-as-project** (`scripts/render_html.py` exists in the working directory): invoke as
  `python -m scripts.<name>` / `bash scripts/<name>.sh`. Everything works.
- **Installed plugin in a foreign project**: invoke the bundled copies by path -
  `<python> "$CLAUDE_SKILL_DIR/../../../scripts/<name>.py"` (skills live at
  `<plugin>/.claude/skills/<skill>/`, so the plugin root is three levels up). The scripts are
  path-independent and write output relative to the working directory, and the execution gate
  allow-lists the team's script **basenames** for path invocation - no exec consent needed for
  them. Two caveats to state rather than discover:
  - the **masking pipeline** (`ingest`, `synthesise`) additionally needs the *user's project* to
    hold its own `config/masking-schema.yaml` (copy the plugin's as a starting template) and
    `MASKING_KEY` in the environment - offer to set that up, don't assume it;
  - the **repo's own test suite / worked example** only exist in the repo - `/demo`'s Build
    flavour and `/run-evals` want repo-as-project;
  - **file conversion** (`convert_file`) needs no pip anywhere: its libraries are vendored in
    `<plugin>/vendor/` and resolved relative to the script itself, so the bundled copy works
    from a foreign project the same as in the repo (house rule: all Excel/CSV/PDF/DOCX
    reading goes through it - `docs/house-rules.md`). One **optional system package**
    sharpens it: `poppler-utils` (`pdftotext`) recovers PDF pages the vendored pypdf can't
    extract - without it those pages are reported MISSING (see `requirements-dev.txt`).
  - **Document inputs are NEVER hand-parsed (standing rule, 2026-07-29).** The moment an
    input arrives as a PDF, DOCX, XLSX/XLS or CSV: `<python> -m scripts.convert_file
    <file>` (plugin mode: the `$PLUGIN_ROOT/scripts/` copy by path) - it is consent-free
    and allow-listed. Never `Read` the binary bytes, never shell/PowerShell one-liners
    (`Get-Content`, `ReadAllBytes`, `strings`), never retype content by eye. `--layout`
    keeps PDF columns/tables readable; `--list` inventories sheets/tables/pages. The
    conversion REPORT is evidence - its warnings (scanned pages = MISSING content, table
    caveats) carry into the engagement's artifacts, and a scanned/image-only PDF is
    **escalated to the user via the question tool** (ask for the text-bearing original or
    the upstream data) - never guessed, never transcribed by eye. Assume the corporate
    environment allows NO new installs: the vendored converter is the toolchain.
- **Never silently skip a deliverable step** because a script seems unreachable: resolve the
  path per the above, and if something genuinely can't run in this mode, say so in the close and
  in the summary email.
