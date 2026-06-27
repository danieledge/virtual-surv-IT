# Scenario request: detect marking-the-close

## Need
Our trade surveillance team has a gap: we do not currently detect **marking-the-close**,
where a trader enters orders or trades near the end of a trading session to push the
official closing price in a favourable direction (for example, to flatter the valuation of
a derivatives position that settles against that close).

## Obligation
This is market manipulation under **MAR (Regulation (EU) No 596/2014), Article 12** -
behaviour that gives, or is likely to give, false or misleading signals as to the price of a
financial instrument, including securing the price at an abnormal or artificial level. We need
a surveillance scenario that the compliance team can defend to the regulator.

## What we want
Turn this into a specification we can hand to the build team. It should:

- make the link from the detection back to the obligation explicit and traceable;
- state the requirements clearly enough to test;
- describe what a genuine alert looks like AND what a benign end-of-day pattern looks like
  (so we are not drowned in false positives from ordinary closing-auction activity).

## What we do NOT have yet
We have **not** agreed any numeric values - the size of orders, how close to the close
counts as "near the close", or the price-move that should trip the alert. Those need calibrating
against our own venues and instruments. Please do not guess them.

## Data notes
All example records must be synthetic. A worked example might be a single trader (token
`TRADER_A1`) placing buy orders in the closing auction window of instrument `INSTR_X`; do not
use any real names, accounts or order data.
