# Review tooling: caveats and history for the best-effort analysers

> Moved out of `.claude/agents/code-reviewer.md` on 2026-09-13 (framework review, step 4.4):
> the prompt keeps the rules that apply on every review (the eight supported tools, the
> `osv-scanner --offline` rule, `gitleaks` scoped to the target); this page keeps the
> per-tool caveats and the record of what was removed and why. The mechanics of which tools
> are on, off or required live in `scripts/check-review-tools.sh`'s header.

The rest of the table (TypeScript/Scala/Java/PowerShell) is best-effort/presence-only, not
individually configurable, and each has a caveat:
- `eslint`/`tsc --noEmit` need `node_modules` populated to resolve imports/plugins cleanly -
  if it's absent, skip both rather than running and reporting unresolved-import noise as
  findings; mark TypeScript coverage 🧠 inferred-only for that review.
- `checkstyle`/`pmd` are safe **only as standalone CLI binaries** (brew/apt install). Never
  invoke them via `mvn`/`gradle` (network dependency resolution, and both are blocked outright
  by the code-execution guard as build/test execution) or raw `java -jar`/`java -cp` (same
  guard, any `java` invocation beyond `--version`/`--help` is treated as running code).
- `error-prone`, `spotbugs`+`find-sec-bugs`, `scalac -Xlint`, `wartremover` are **not driven at
  all** (removed 2026-08-04, same bar as semgrep/pip-audit below) - each needs a full compiled
  build via `mvn`/`gradle`/`sbt`, which both reaches the network for dependencies and is
  blocked by the execution guard. Java/Scala deep static analysis is 🧠 inferred-only until a
  network-free alternative exists.
- `pwsh`+`Invoke-ScriptAnalyzer` is listed for completeness but **effectively dead today**: the
  execution guard treats any `pwsh`/`powershell` invocation as code execution (ADR-002), so it
  only runs once a human has opened the §7 consent gate. PowerShell review stays 🧠
  inferred-only before that.

**`semgrep` and `pip-audit` are deliberately NOT used, even if installed** (removed
2026-08-04: both make unconditional network calls with no reliable offline mode and caused
repeated live corp-proxy hangs - quiet/offline flags were tried and measured insufficient,
see git history). Neither is listed in `scripts/check-review-tools.sh`'s probe, so neither
ever shows as "available" - **do not invoke them even if you notice they happen to be on
PATH.** Python security coverage is `bandit` only for now; SQL and the language-agnostic
"Any" row lose dedicated security-analyser coverage until a network-safe replacement exists -
flag this explicitly as 🧠 inferred-only coverage for those, same as any other missing tool.

## The review tooling, as the README told it

> Moved out of README.md on 2026-09-14 (framework review, step 6.8).


The `code-reviewer` agent drives standard analysers; it doesn't reinvent rules. None are required
to *use* the team; they sharpen reviews. **Without them, reviews still run, but degrade to
inference-only (🧠) instead of tool-backed measured (📊) findings** (the 🔬 tooling-coverage line
says what couldn't run).

<details>
<summary>🔍 <b>Analyser install per language</b> (optional; sharpens <code>code-reviewer</code>)</summary>

**Most of them are installed for you.** The installer's *Language analysers* step (part of
"Install/update or reconfigure"; rerun it on an existing install to pick them up) fetches every
analyser that needs no admin rights and no extra runtime: `bashate` and `ast-grep` by pip,
`gitleaks`, `shfmt` and `shellcheck` as release binaries into a per-user directory the installer
manages, and `eslint` + `tsc` by npm when node is already on the machine. The *Dependency
scanner* step does the same for `osv-scanner` and its offline vulnerability database. No Go
toolchain, package manager or elevated shell is needed for any of them, and the step explains
what it fetched and from where. The ones it deliberately leaves alone need a runtime (a JDK,
coursier or PowerShell), which is a decision for you, not a convenience the installer should
take; they stay hints.

**Seven tools are officially supported and individually configurable** - each proven to run
single-file, dependency-free and network-free (the same bar `semgrep`/`pip-audit` failed and were
removed for):

| Tool | Language / role | How you get it |
|---|---|---|
| `ruff`, `mypy`, `bandit`, `black` | Python lint/types/security/format | `pip install -r requirements-review.txt` - one command, the only manual step |
| `sqlfluff` | SQL lint | same file |
| `gitleaks` | secret scan (any language) | installed for you (release binary) |
| `shfmt` | Bash format | installed for you (release binary) |

Turn any of the seven `on`/`off` per project (`install_helper.py`'s "Project preferences" step,
or `VSIT/config/preferences.json`'s `review_tools` key directly), or set a default for every
project on this machine (same step, "save as default" → `~/.config/virt-surv-it/installer.json`'s
`default_review_tools`). `auto` (the default) means "use it if present, skip silently if not". A
security team can disable all seven centrally with the env var `CST_NO_EXTERNAL_TOOLS=1`.
`install_helper.py --check-tools` (or the interactive menu's Diagnostics → "Check analyser output
cleanliness") live-tests each one against a throwaway synthetic file before you rely on it -
catching a hanging/network-blocked tool the same way this caught semgrep/pip-audit. The full
diagnostic also lists every analyser below as installed or missing, with what a missing one
costs (inferred 🧠 findings in that language, never a broken review).

**The rest are best-effort, presence-only, not individually configurable:**

| Language | How you get it | Caveat |
|---|---|---|
| Bash | `shellcheck` (lint) and `bashate` (style): installed for you | - |
| Any (structural search) | `ast-grep`: installed for you | used by the reviewers to find implementations and callers by AST pattern |
| TypeScript / JavaScript | `eslint` + `tsc`: installed for you when node is already present, otherwise a hint | needs `node_modules` populated, or skipped |
| Java | `checkstyle`, `pmd` - hint only, needs a JDK | standalone CLI only - **never** via Maven/Gradle or raw `java -jar` (both blocked as code execution) |
| Scala | `scalafmt` - hint only, via `coursier`/sbt | format-only; semantic `scalafix` rules need a prior compile, not driven |
| PowerShell | `pwsh -c 'Install-Module PSScriptAnalyzer -Scope CurrentUser'` - hint only | effectively dead today - see note below |

Not driven at all (removed 2026-08-04, alongside semgrep/pip-audit): Java's `error-prone` and
`spotbugs`+`find-sec-bugs`, Scala's `scalac -Xlint` and `wartremover` - all need a full compiled
build via `mvn`/`gradle`/`sbt`, which both reaches the network and is blocked by the
code-execution guard. Java/Scala deep static analysis is 🧠 inferred-only until a network-free
alternative exists.

> **PowerShell note:** the execution gate treats any `pwsh` invocation as code execution, so
> `Invoke-ScriptAnalyzer` only runs once a human has opened the CLAUDE.md §7 consent gate; the
> settings allow-list entry for it was removed for exactly this reason. Before consent, PowerShell
> review stays static (🧠).

The agent runs whatever is present and enabled, and reports which analysers were unavailable or
disabled; nothing is silently skipped.

</details>

<sub>[↑ Back to top](../README.md#readme-top)</sub>
