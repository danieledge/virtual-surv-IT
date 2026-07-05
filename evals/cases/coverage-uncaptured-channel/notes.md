# Grading notes (NOT shown to the team - do not pass this file to the workflow)

## Seeded issue (for the harness - not shown to the team)

1. **Uncaptured channel.** CH-WHATSAPP is used by the Rates traders
   (POP-TRADERS) but `captured: false` / `monitored: false` - no archive, no
   lexicon, no alerts. Communications on it are entirely off-channel and
   unsurveilled.

## False-positive trap

Email, trader-turret voice and Bloomberg chat are all captured AND monitored.
A thorough assessment must NOT flag a captured-and-monitored channel as a gap.
