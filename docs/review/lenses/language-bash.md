---
name: Bash Issues
model: sonnet
applies_to: ["*.sh", "*.bash"]
---

> Lens structure follows **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Language-specific checks for Bash - pipeline orchestration, deploy hooks and feed-wrappers in regulated surveillance systems.

## Checks

### Injection & Quoting (shellcheck: SC2086 / SC2046)
- Unquoted variable expansions (`$var`, `$(cmd)`) in any context where word-splitting or glob expansion can occur - shell injection vector and silent breakage on filenames with spaces (SC2086); quote everything: `"$var"`
- `eval` on any string containing external input - arbitrary command execution (CWE-78); flag `eval` unconditionally unless the string is a verified compile-time constant
- Command substitution result used directly as a command name or path (`$(get_tool_path)`) without validation - command injection if the sourced value is attacker-influenced
- `$@`/`$*` passed unquoted to a sub-command - argument injection; use `"$@"` always

### Error Handling & Safety
- Missing `set -euo pipefail` (or equivalent per-command `-e`/`|| exit`) at script top - silent continuation after a failed feed-fetch, DB load, or file move; in surveillance pipelines a silently skipped step is a missed-alert risk
- Ignoring the exit status of a critical command (no `|| { log_error …; exit 1; }`) - same risk as above; shellcheck SC2181 flags indirect `$?` checks as a smell
- `rm -rf` on a path built from a variable without first asserting the variable is non-empty - catastrophic data loss if the variable is unset (`rm -rf /$EMPTY_VAR/`)
- `trap` not set for `ERR`/`EXIT` in scripts that create temp files or hold locks - resource leak on unexpected exit

### Secrets & Credentials
- Credentials passed as positional arguments to a subprocess - visible in `ps` output and shell history (CWE-214); use environment variables or a file descriptor (`--password-file`)
- `export SECRET=<literal>` or `echo "apikey=<literal>"` in script body - secret in source and potentially in logs; read from `$ENV_VAR` sourced from `~/.secrets`
- Writing sensitive values to a world-readable temp file (`/tmp/`) without `mktemp` and `chmod 600` - exposure to other local processes

### Robustness & Portability (shellcheck / shfmt)
- `#!/bin/sh` shebang with bash-only syntax (`[[ ]]`, `local`, arrays) - silent misparse on systems where `/bin/sh` is dash/ash; use `#!/usr/bin/env bash` and `shellcheck -s bash`
- Parsing `ls` output (`for f in $(ls *.log)`) - breaks on filenames with spaces/newlines; use glob directly (`for f in *.log`) or `find … -print0 | xargs -0`
- Here-docs or multi-line strings with inconsistent indentation in a `<<-` block - shfmt detects these; fix before commit to avoid review noise masking real issues

### Performance
- `cat file | grep pattern` - useless `cat`; use `grep pattern file` to avoid spawning an extra process per invocation (shellcheck SC2002); matters in tight loops over surveillance log sets
- `while read line; do … done < <(cmd)` replaced by a subshell pipe - variables set inside a pipeline subshell are lost; prefer process substitution `< <(cmd)` to keep state in the main shell

## Output

Use the shared format in `docs/review/output-format.md` - diff-style fix + "why this works", confidence score, and evidence basis (📊 measured / 🧠 inferred). Defer §4/§5 regulated findings to `compliance-reviewer`.
