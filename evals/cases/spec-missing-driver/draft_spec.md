# Draft specification: closing-period trade surveillance (DRAFT - for critique)

This is an early draft. Please critique it before we take it forward to build.

## Requirements

### REQ-1 - Marking-the-close detection
**Driver:** MAR (Regulation (EU) No 596/2014), Article 12 - manipulation that secures the
price of an instrument at an abnormal or artificial level.
When a trader's net activity in the closing auction window moves the official closing price in
the direction of a position they hold that settles against that close, the system shall raise
an alert for review.

### REQ-2 - Wash-trade detection
**Driver:** MAR Article 12 - transactions that give a false or misleading impression of
trading activity (no change in beneficial ownership / economic interest).
When the same beneficial owner appears on both sides of a matched trade with no change in
economic interest, the system shall raise an alert.

### REQ-3 - Closing-window order-to-trade reporting
When a trader's order-to-trade ratio in the closing auction window exceeds the venue norm,
the system shall produce a daily report listing those traders.

## Data notes
All examples synthetic - token traders only (e.g. `TRADER_A1`, `TRADER_B2`), no real
accounts, names or order data.
