# Scenario - coverage assessment with an uncaptured comms channel

**Synthetic eval input.** All data is synthetic. See `expected.yaml` for the
planted ground truth.

## What the team is asked to do

Run a surveillance coverage assessment (`/assess-coverage`) over the attached
`channels.yaml`. The inventory lists the in-scope populations subject to
communications surveillance and the channels they use, with each channel's
capture and monitoring status.

Assess whether **every in-scope population's communications are actually
captured and monitored**. Report any uncaptured (off-channel) gaps, route each
to the right owner, and close with prioritised remediation.

## Seeded issue (for the harness - not shown to the team)

1. **Uncaptured channel.** CH-WHATSAPP is used by the Rates traders
   (POP-TRADERS) but `captured: false` / `monitored: false` - no archive, no
   lexicon, no alerts. Communications on it are entirely off-channel and
   unsurveilled.

## False-positive trap

Email, trader-turret voice and Bloomberg chat are all captured AND monitored.
A thorough assessment must NOT flag a captured-and-monitored channel as a gap.
