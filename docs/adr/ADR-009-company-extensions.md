# ADR-009: Company extensions - additive instructions, tools and steps, never waivers (accepted)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-009` · Version `0.1` · Status `Accepted`
> · Classification `Internal` · Owner `Morgan (PM)` · As-of `2026-07-28`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-28 | user requirement (company-specific capabilities) | Accepted & implemented: extensions contract + parser, SARIF converter, staged company allowlist |

| | |
|---|---|
| **Status** | **Accepted / implemented** (0.32 batch; guard change staged, human-applied) |
| **Date** | 2026-07-28 |
| **Deciders** | Morgan (orchestrator), human approver |
| **Traceability** | ADR-002 (guard threat model - the allowlist and never-execute rules below), README §Extending the team (the composition recipes this formalises); user examples: alternate analysers, vendor KBs, raise-a-Jira, publish the pack |

## Context

Organisations adopting the team need company-specific capability: their own analysis
tooling in place of the bundled open-source defaults, their own reference sources, workflow
steps (raise a Jira) and publishing targets (a share, Confluence), plus standing
instructions unique to them. Composition (project CLAUDE.md + MCP + own skills) covers much
of this but leaves gaps: the analyser inventory doesn't know company tools (findings get
mislabelled as degraded), tool output has no consistent mapping into the findings pipeline,
interpreter-wrapped company tools hit the execution gate, and instructions-as-prose are
undiscoverable and untestable.

## Decision

1. **One contract file in the working project**: `docs/team-extensions.md` (template
   shipped) with recognised sections - Standing instructions, Close actions, Analyser
   registry (a fenced ```json block), Integrations. The engage step-0 probe surfaces it
   (`scripts.extensions show`); absent file = zero cost.
2. **Extensions are ADDITIVE ONLY** - the load-bearing rule, stated in the template, the
   skill, the operating guide, and structurally true (the parser has no waiver
   vocabulary). Nothing in an extensions file can waive a disclaimer, gate, guard or the
   code chain; close actions are OFFERS previewed at the go-ahead gate and executed only on
   approval after the standard close completes; outward-facing actions additionally carry
   the harness permission prompt.
3. **The analyser registry** declares company tools per review lens with `replaces:`
   semantics (the lens counts as covered; findings are not degraded because a bundled
   default is absent), a PATH-presence probe, and an output format. **`scripts.extensions`
   NEVER executes registry content**: presence checks are `shutil.which` only, and any
   command containing shell metacharacters is refused at validation - an allow-listed
   script that executed a model-writable file would be a guard bypass, so the capability is
   structurally absent (pinned by an AST test).
4. **SARIF normalisation** (`scripts.convert_sarif`): deterministic conversion of any
   SARIF-emitting tool's report into the standard findings pack (schema-validated), with a
   company severity map, `standard` = tool:ruleId, and the report retained on disk so
   findings carry 📊 measured. Fields SARIF cannot supply say so explicitly (triage
   required) rather than inventing specifics.
5. **The company tool allowlist** (staged guard change, human-applied per ADR-002 rec 5):
   `CST_COMPANY_ALLOW` - '|'-separated LITERAL command prefixes, read by the execution
   guard from the launch environment / settings `env` block. Both surfaces are human-only
   (the model cannot set env for the hook subprocess; settings edits are blocked by the
   consent-write guard). Literal prefix match, no regex, segments still split first so
   chained commands are inspected independently; empty/unset changes nothing. Recommended
   practice: end each prefix at the `.py` boundary. Registering a prefix asserts the HUMAN
   trusts that tool.
6. **New team-script basenames** (`extensions`, `convert_sarif`) staged into
   `_TEAM_SCRIPT_NAMES` for plugin-mode path invocation, per the standing rule.

## Consequences

- The four company scenarios become first-class: alternate tooling (registry + SARIF +
  allowlist), reference sources (instructions + integrations sections; data-safety rules
  extend to KB content), workflow steps and publishing (close actions, gated).
- Attack surface analysed: the contract file is model-writable by design (it lives in the
  user's repo under their review); every pathway from it to execution passes through either
  the unchanged execution guard or a human approval, and the parser itself is inert.
  Residual: a user who pastes a malicious extensions file from elsewhere is trusting it -
  same trust boundary as their own CLAUDE.md.
- The live golden case for extensions (registered fake tool + close-action offer) is
  deferred to the 0.32 promotion prep, alongside applying the staged guard.

## Alternatives considered

- Prose-only steering via CLAUDE.md (status quo): works but undiscoverable, untestable,
  mislabels degraded findings - kept as the fallback, formalised by this contract.
- Letting `scripts.extensions` run registry probes/commands: rejected outright (guard
  bypass; see Decision 3).
- Regex company allowlist: rejected for literal prefixes (regex in a human-edited env var
  invites over-broad matches).
