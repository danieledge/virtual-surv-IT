# Extending the team: practical setup guide

Add company-specific capability to the team: your own analysis tooling, workflow steps
(raise a Jira), publishing targets, reference sources and standing instructions. Follow the
steps in order; each has a verification. Everything happens in YOUR working project, never
in the plugin.

**The one hard rule up front: extensions are ADDITIVE ONLY** (ADR-009). Nothing here can
waive a disclaimer, gate, guard or the code chain; close actions are offers you approve.

---

## Step 1 - create the extensions contract

```bash
mkdir -p docs
cp <plugin>/docs/templates/team-extensions.md docs/team-extensions.md   # or copy from GitHub
```

Open it and delete every section you don't need yet. A minimal useful start:

```markdown
# Team extensions - ACME

## Standing instructions

- Cite our control IDs (CTRL-xxx) wherever a finding maps to one.
```

**Verify:**

```bash
python3 -m scripts.extensions show     # plugin install: python3 <plugin>/scripts/extensions.py show
```

Expected: a `TEAM-EXTENSIONS:` block echoing your sections, ending with the additive-only
notice. From now on every `/engage` open surfaces this automatically.

## Step 2 - register your own analyser (replacing a bundled default)

Add to `docs/team-extensions.md`:

````markdown
## Analyser registry

```json
{"analysers": [
  {"name": "cx", "command": "cxcli scan --format sarif -o {workspace}/data/cx.sarif {target}",
   "probe": "cxcli", "lenses": ["security"], "replaces": ["bandit", "semgrep"],
   "output": "sarif", "severity_map": {"error": "critical", "warning": "warning"}}
]}
```
````

**Verify:**

```bash
python3 -m scripts.extensions check
```

Expected: `cx  found  (cxcli)` - or `MISSING`, meaning install the binary or fix `probe`.
Commands must be plain argv: any `; | & $ >` refuses the entry (you'll see
`EXTENSIONS-INVALID` - that's the smuggling defence working).

During reviews the team now runs your tool for the security lens, and `replaces` means
findings are NOT degraded because bandit/semgrep are absent. SARIF output flows through:

```bash
python3 -m scripts.convert_sarif artifacts/<ws>/data/cx.sarif --slug <slug> --scope "src/"
python3 -m scripts.validate_findings artifacts/<ws>/data/findings-<slug>.json
```

Expected: a schema-valid findings pack, 📊 measured, rendered into the standard review.

## Step 3 - allow an interpreter-wrapped tool (only if you have one)

Plain binaries (step 2) need nothing more. A tool invoked *through* an interpreter
(`python our_scanner.py`) hits the execution gate. Two routes, either works:

- grant execution consent at the engagement's intake when asked, or
- **allowlist it permanently** (human-only act): in the environment you launch Claude Code
  from, or your project's `.claude/settings.json` `env` block:

```json
{ "env": { "CST_COMPANY_ALLOW": "python3 tools/our_scanner.py|python scripts/publish_pack.py" } }
```

Literal prefixes, `|`-separated, end each at the `.py` boundary. Registering a prefix
asserts YOU trust that tool.

**Verify** (from a fresh session): ask the team to run the wrapper; it should execute
without a consent prompt, while `python anything_else.py` still gets gated.

## Step 4 - add workflow steps (Jira) and publishing targets (Confluence / a share)

Wire your MCP server once, in the project's `.mcp.json`:

```json
{ "mcpServers": { "atlassian": { "command": "npx", "args": ["-y", "@atlassian/mcp-server"] } } }
```

Then declare the steps as close actions in `docs/team-extensions.md`:

```markdown
## Close actions

- Raise a Jira in project SURV via the atlassian MCP: summary = engagement verdict,
  description = delivery-report summary, label `virt-team`.
- Copy the engagement workspace to \\share\surveillance\packs\<slug>-<date>\.

## Integrations

- atlassian MCP: Jira project SURV, Confluence space SURV-DOC.
```

**Verify:** run any small engagement to close. Expected: the actions are previewed at the
go-ahead gate, then OFFERED after the summary email; the Jira/Confluence call additionally
shows the harness permission prompt. Nothing runs silently, nothing runs mid-engagement,
and publishing only ever touches the ✅ closed pack (no secrets, masked/synthetic rules
travel with it).

## Step 5 - point agents at your reference sources

- Files: check them into the project (`docs/vendor/xyz-kb/`) and add a standing
  instruction: *"consult docs/vendor/xyz-kb/ before inferring platform behaviour; cite doc
  + section."*
- Remote KBs: another MCP server entry, referenced under **Integrations**.
- ⚠️ Anything an agent reads goes to the model provider - the masked/synthetic/no-secrets
  rules apply to KB content exactly as to data.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Extensions not mentioned at engage open | File must be `docs/team-extensions.md` in the WORKING project; run the Step 1 verify |
| `EXTENSIONS-INVALID: ... metacharacters - REFUSED` | Registry command contains `; \| & $` etc. - make it plain argv; chain nothing |
| Tool shows `MISSING on PATH` | Install it, or fix `probe` to the actual binary name |
| Wrapper blocked by the execution gate | It's interpreter-wrapped: grant consent at intake, or add a `CST_COMPANY_ALLOW` prefix (Step 3) |
| Findings degraded to 🧠 despite your tool | Ensure `replaces` names the bundled tools your tool supersedes |
| Close action ran nothing | They're offers - approve at the gate; outward actions also need the permission prompt |
| Team refuses an instruction in your contract | It asked for a waiver (skip QA / skip disclaimers / auto-publish) - extensions are additive only, by design |

## Reference

- Contract template + field-by-field docs: [`templates/team-extensions.md`](templates/team-extensions.md)
- Design + threat analysis (why the parser never executes, why prefixes are literal, what
  the adversarial golden case covers): [`adr/ADR-009-company-extensions.md`](adr/ADR-009-company-extensions.md)
- No contract at all? Plain `CLAUDE.md` steering still works for everything above - the
  contract makes it structured, discoverable and eval-tested.
