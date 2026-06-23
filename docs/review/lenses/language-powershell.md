---
name: PowerShell Issues
model: sonnet
applies_to: ["*.ps1", "*.psm1", "*.psd1"]
---

> Lens structure follows **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Language-specific checks for PowerShell — ops scripts, feed-automation and Windows-side ETL in regulated surveillance systems.

## Checks

### Injection & Command Safety (PSScriptAnalyzer: PSAvoidUsingInvokeExpression)
- `Invoke-Expression` (`iex`) on any string built from external input — arbitrary code execution; there is almost never a legitimate use; flag unconditionally (CWE-78)
- `& $variable` or `Start-Process` where `$variable` derives from user input, a file path, or an environment variable without allowlist validation — command injection
- Unvalidated path segments joined with `Join-Path` or plain string concatenation fed to `Remove-Item`/`Copy-Item` — path traversal (CWE-22); validate against an expected root
- `-Command` passed to `powershell.exe`/`pwsh` from within a script — double-execution layer; audit whether it is avoidable

### Credential & Secrets Handling (PSScriptAnalyzer: PSAvoidUsingPlainTextForPassword / PSAvoidUsingConvertToSecureStringWithPlainText)
- Passwords or API keys assigned to plain `[string]` variables or passed as `-Password` string literals — must use `[SecureString]` in transit and read from environment variables or a vault; flag any `password`, `apikey`, `secret` literal assignment
- `ConvertTo-SecureString -AsPlainText -Force` on a hard-coded string — defeats `SecureString`'s purpose; source the value from `$env:` instead
- Credentials written to a log file via `Write-Host`/`Write-Output` — PII/secrets exposure in log pipelines

### Error Handling & Reliability
- Missing `$ErrorActionPreference = 'Stop'` or `-ErrorAction Stop` on critical operations — PowerShell defaults to `Continue`; a failed feed-fetch or DB write silently succeeds (PSScriptAnalyzer: `PSReviewUnusedParameter` may surface related gaps)
- Bare `try/catch` catching all errors and doing nothing — swallows ETL failures silently
- `Test-Path` check without subsequent atomic operation — TOCTOU race on shared network paths used by surveillance feeds

### Performance & Resource Management
- Loading an entire CSV/log file with `Import-Csv` or `Get-Content` into a variable for large files — use `foreach` with pipeline streaming (`Get-Content | ForEach-Object`) to avoid memory exhaustion
- Opening a SQL connection inside a loop instead of reusing a single connection with parameterised commands — connection-pool pressure at surveillance volumes
- `Select-String`/regex on multi-GB log files without a `Where-Object` pre-filter — unnecessary full-scan

### Code Quality & Idioms (PSScriptAnalyzer)
- Functions lacking `[CmdletBinding()]` and `param()` blocks — no `-WhatIf`/`-Confirm` support; risky for ops scripts that delete or move data
- Positional parameters instead of named parameters in public functions — fragile call sites; breaks silently if parameter order changes (PSScriptAnalyzer: `PSAvoidUsingPositionalParameters`)
- `Write-Host` instead of `Write-Verbose`/`Write-Output` in a module — `Write-Host` bypasses the pipeline and cannot be captured by calling scripts

## Output

Use the shared format in `docs/review/output-format.md` — diff-style fix + "why this works", confidence score, and evidence basis (📊 measured / 🧠 inferred). Defer §4/§5 regulated findings to `compliance-reviewer`.
