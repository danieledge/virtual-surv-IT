# docs/internal/ - maintainer documentation (not loaded by the plugin)

The split (2026-07-29, user request during the workflow-robustness remediation):

- **`docs/` (parent)** holds what the TEAM actually loads or follows at runtime - the
  operating guide, scope-and-stack, house rules, the DoD, review method + `review/`,
  `templates/`, `adr/`, coding standards, WAYS-OF-WORKING, agent-design, `scenarios/`
  (the demo rule's audit trail), `demos/` (pointed at by `/demo`) - plus the small
  user-facing set (OVERVIEW, FAQ, glossary, EXTENDING) linked from the README.
- **`docs/internal/` (here)** holds documentation ABOUT the product that nothing at
  runtime reads: research and evidence bases, design specs and roadmaps, flow
  diagrams/posters, and point-in-time eval baselines.

Rule of thumb for new documents: if a skill, script, hook or template references it, or a
working-project engagement is expected to read it, it goes in `docs/`; if only a maintainer
of THIS repo reads it, it goes here.

Contents:

| File | What it is |
|---|---|
| `research-virtual-team.md` | The research base behind the team design (referenced as rationale by skills/hooks, never loaded) |
| `evidence-base.md` | Claim-by-claim evidence inventory from the verification engagement |
| `eval-baseline-2026-07-06.md` | Point-in-time eval baseline (later baselines live in `evals/`) |
| `prepare-data-design.md` / `prepare-data-roadmap.md` | Design spec + roadmap for the assisted-masking evolution (**partly built**: the roadmap's format-adapter item is largely `scripts/convert_file.py`, which handles xlsx, xls, csv, pdf, docx, eml and msg) |
| `engagement-flow-spec.md` | The normative spec of the engagement machine (hooks, gates, close order) |
| `engagement-flow-diagram.md` / `engagement-flow-poster-flowchart.html` | Flow visuals / marketing poster |
| `resolved-issues.md` | Archive of previously reported known issues that are resolved or fully mitigated (the README keeps only open ones) |
| `cross-platform-portability-roadmap.md` | Research + plan for running this team under GitHub Copilot as well as Claude Code (not yet built) |
| `large-context-review-splitting-plan.md` | Design record for component-wise review splitting - fixes corp-proxy timeouts on large-context reviewer calls and improves review focus generally (implemented; behaviour lives in `docs/team-operating-guide.md`) |
| `cache-contract.md` | What each cache under `VSIT/local/` promises, and its TTL |
| `incident-log.md` | Append-only record of live failures and what fixed them |
| `windows-test-vm-access.md` | How to reach the Windows test VM (git-ignored) |
| `whole-plugin-review-2026-08-05.md` | Full-product review, point-in-time |
| `dev-briefing-2026-08-10-plugin-engineering-challenges.md` | What is hard about building this, for a new maintainer |
| `resolved-issues.md` | Archive of README known-issues entries that are now closed |

**Dated working documents are NOT listed individually here** (corrected 2026-09-10: the
table above claimed to be the contents and named nine files while the directory held
thirty-five, which is what happens to any hand-maintained inventory of a growing folder).
Three families, each file carrying its own status line:

- **`plan-*.md`** - a design worked out before building it. **The status line is the
  contract**: when the thing ships, that line says so, names the version and names the
  module. Six of these still said "nothing built" about shipped features until 2026-09-10,
  which is worse than being merely old, because a reader consulting a plan to find out what
  the system does is told the opposite of the truth.
- **`backlog-*.md`** - work parked deliberately, with the reason and what would unblock it.
- **Dated audits and reviews** (`*-audit-*.md`, `*-review-*.md`, `*-baseline-*.md`) -
  point-in-time records. These are archives: they are supposed to accumulate and should
  not be "tidied up".

Several files here are **git-ignored** by deliberate choice, so a fresh clone shows fewer
files than a working checkout. Check before assuming something is missing.
