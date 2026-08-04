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
| `prepare-data-design.md` / `prepare-data-roadmap.md` | Design spec + roadmap for the assisted-masking evolution (not yet built) |
| `engagement-flow-spec.md` | The normative spec of the engagement machine (hooks, gates, close order) |
| `engagement-flow-diagram.md` / `engagement-flow-poster-flowchart.html` | Flow visuals / marketing poster |
| `resolved-issues.md` | Archive of previously reported known issues that are resolved or fully mitigated (the README keeps only open ones) |
| `cross-platform-portability-roadmap.md` | Research + plan for running this team under GitHub Copilot as well as Claude Code (not yet built) |
