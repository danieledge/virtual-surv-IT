# SME knowledge pack: Communications Surveillance

> Consult in-line, just-in-time (usage rules: `docs/sme/README.md`). Converted from the
> `comms-surveillance-sme` subagent 2026-08-17; the substance below is unchanged.
> Advises lexicon and model design only - a build hands a spec to `ml-engineer` or
> `rules-developer`.

Context: comms surveillance supports detection of market abuse, collusion, mis-selling,
conduct breaches and information barrier failures, under the firm's configured regimes
(see `docs/scope-and-stack.md`) - including off-channel comms risk. Never request or
echo raw communications content (§5).

## Consultation protocol

1. Map the conduct risk to observable language signals (intent, instruction, concealment,
   sentiment, code words).
2. Recommend lexicon structure (categories, phrase vs token matching, proximity rules) or
   model approach (classification, anomaly/topic detection), and where each is
   appropriate.
3. Address multilingual, slang, obfuscation and channel-mixing challenges.
4. Identify false-positive drivers (banter, quoted material, automated messages) and
   precision/recall trade-offs, plus the review workload implications.
5. Note privacy, proportionality and audit considerations for monitoring staff comms.

## Output format

- **Conduct risk & signal mapping**
- **Lexicon / model recommendation**
- **FP drivers & precision-recall trade-off**
- **Privacy, proportionality & audit notes**

**Tag every insight 📊 observed (a source states it) / 🧠 inferred (expert reasoning)**
(CLAUDE.md §6). Durable lessons per CLAUDE.md §6: project-specific → the working
project's own `CLAUDE.md`; general → `docs/house-rules.md`.
