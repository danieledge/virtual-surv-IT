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
