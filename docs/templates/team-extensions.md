# Team extensions - <COMPANY / PROJECT NAME>

> **The company extensions contract (ADR-009).** Place a copy of this file at
> `docs/team-extensions.md` IN YOUR WORKING PROJECT and the team reads it at every engage
> open (`python -m scripts.extensions show` in the step-0 probe). Everything here is
> **additive**: extensions can add instructions, tools and steps - they can never waive a
> disclaimer, skip the code chain, weaken a guard or self-grant consent. Outward-facing
> actions (tickets, uploads) are always offered at gates, never silent.
> Sections are recognised by their exact H2 headings; delete any you don't need.

## Standing instructions

*Free-form additions to the operating rules, honoured alongside the team handbook (your
project CLAUDE.md also works for these; this section keeps them with the other extensions).*

- <e.g. "Cite our internal control IDs (CTRL-xxx) wherever a finding maps to one.">
- <e.g. "Address the requester as 'ops lead' in summary emails.">

## Close actions

*Offered by Morgan AFTER the summary email at every ✅ close (and shown at the go-ahead gate
so nothing is a surprise). Each is an OFFER - the user approves at the gate; outward actions
are additionally permission-prompted by the harness.*

- <e.g. "Raise a Jira in project SURV via the Atlassian MCP: summary = engagement verdict,
  description = delivery-report summary, label `virt-team`.">
- <e.g. "Copy the engagement workspace to `\\share\surveillance\packs\<slug>-<date>/`.">

## Analyser registry

*Company tools the review lenses use INSTEAD of (or alongside) the bundled defaults. The
team script only checks the binary exists on PATH (`shutil.which`) - it NEVER executes
registry commands itself; the session invokes them like any tool, under the normal
execution rules (plain binaries run free; interpreter-wrapped commands need the
human-curated `CST_COMPANY_ALLOW` prefix list in your protected settings env). Commands
must be plain argv (no `; | & $ \\``) or validation refuses the entry. Registering a tool
asserts YOU trust its binary.*

```json
{
  "analysers": [
    {
      "name": "example-scanner",
      "command": "cxcli scan --format sarif -o {workspace}/data/cx.sarif {target}",
      "probe": "cxcli",
      "lenses": ["security"],
      "replaces": ["bandit", "semgrep"],
      "output": "sarif",
      "severity_map": {"error": "critical", "warning": "warning", "note": "style"}
    }
  ]
}
```

*Fields: `name` + `command` required. `probe` = binary checked on PATH (defaults to the
command's first word). `lenses` = which review lens it serves. `replaces` = bundled tools it
supersedes (the inventory then reports the lens as covered instead of "default missing").
`output: sarif` outputs convert to a findings pack via
`python -m scripts.convert_sarif <file> --slug <slug> --scope "<scope>"` so findings stay
📊 measured with the tool report as on-disk evidence.*

## Integrations

*Named MCP servers / endpoints the close actions and instructions refer to, so briefs can
cite them precisely.*

- <e.g. "Atlassian MCP (`.mcp.json` entry `atlassian`): Jira project SURV, Confluence space SURV-DOC.">
