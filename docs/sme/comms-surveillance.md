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

## Under-alerting diagnosis (consult on "why no alert?" - `/why-no-alert` walks the chain)

Comms-specific absence causes: **channel capture gaps** (the conversation happened on an
uncaptured or personal channel - the classic off-channel finding); **language/locale
lexicon gaps** (the lexicon covers English, the conversation didn't); **transcription
quality** (voice never transcribed, or transcribed too poorly to match); **participant
scoping** (the speaker wasn't in the monitored population, or a shared/delegate mailbox
fell outside it); **attachment and embedded content blindness** (the phrase lived in an
image, spreadsheet or forwarded chain the pipeline never text-extracted). Check capture
BEFORE lexicon: a perfect lexicon over an unmonitored channel alerts on nothing.
