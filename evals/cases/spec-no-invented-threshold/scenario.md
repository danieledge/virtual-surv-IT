# Scenario request: spoofing detection

## Need
We want a **spoofing** detection scenario for our equities order flow. Spoofing is where a
trader submits a non-bona-fide order (or orders) on one side of the book to create a false
impression of supply or demand, moves the price, executes a genuine order on the opposite
side, then cancels the non-bona-fide orders.

## Obligation
Spoofing is prohibited market manipulation - placing orders with no intention to trade in
order to mislead other participants. We need a defensible surveillance scenario.

## What we want
Produce a specification the build team can implement: the behavioural pattern to detect, the
order-lifecycle signals it relies on (placement, size, distance from touch, cancellation,
the opposite-side fill), and acceptance criteria.

## Important - no numbers supplied
We have deliberately given you **no threshold values**. We have not decided:

- how large the spoof orders must be relative to the genuine order or to displayed liquidity;
- how quickly they must be cancelled after the opposite-side fill;
- how far from the best bid/offer they sit;
- how many cancellations within a window count as a pattern.

Do **not** invent these. Treat every threshold as an open calibration decision and flag who
owns it. We expect them to be set later with the tuning-analyst against our own data.

## Data notes
Use only synthetic illustrations - e.g. token trader `TRADER_S2` layering orders in
instrument `INSTR_Y`. No real orders, accounts or identifiers.
