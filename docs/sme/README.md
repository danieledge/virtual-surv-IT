# SME knowledge packs

Three domain knowledge packs, converted from the former SME subagents (`tm-sme`,
`trade-surveillance-sme`, `comms-surveillance-sme`) on 2026-08-17 - assessment
recommendation 5: knowledge-only advisors are reference material, not headcount, so a
consult is now an in-line read instead of a subagent spawn (no per-consult setup cost, no
spawn latency, and a 13-agent roster routes more reliably than 16).

**How to consult a pack (any agent, the PM included):**

- Read the relevant pack **just-in-time** - never at open, never all three at once.
- Follow its consultation protocol and produce its output format; **tag every insight
  📊 observed / 🧠 inferred** exactly as before (CLAUDE.md §6).
- In artifacts, **cite the pack** (e.g. "per `docs/sme/trade-surveillance.md`"), never a
  persona - there is no agent behind these names any more, and a named check must always
  have an agent behind it.
- The old boundaries stand: packs advise, builders build. A consult that turns into
  implementation hands a spec to `rules-developer` / `ml-engineer` exactly as the SME
  agents did. Never request or echo raw record content (§5) - schemas and synthetic
  examples only.
- **One escalation rule:** if the consult IS the deliverable (a standalone typology
  opinion the user will rely on), the PM challenges it exactly as it challenged an SME
  return - the independence that matters (QA, model validation, the reviewer trio) still
  comes from real agents.

| Pack | Covers |
|---|---|
| `tm-monitoring.md` | Transaction monitoring / AML: typologies, detection logic, thresholds, segmentation, SAR/STR rationale |
| `trade-surveillance.md` | Market abuse: spoofing, layering, wash trades, insider dealing; behavioural signatures and benign exclusions |
| `comms-surveillance.md` | E-comms/voice: lexicons, NLP risk flags, FP drivers, privacy and proportionality |

(The former personas - Hassan, Camila and Cleo - are retired with thanks; historical
demo artifacts that name them remain accurate records of the runs that produced them.)
