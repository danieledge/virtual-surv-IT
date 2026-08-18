# Scenario (synthetic): alert volumes dropped - why?

The surveillance ops lead reports: "our spoofing scenario used to produce a steady
trickle of alerts; since early August it has gone almost quiet. Why?"

Daily alert counts by segment (synthetic MI extract):

| Date | Large-cap alerts | Small-cap alerts | Total |
|---|---|---|---|
| 2026-08-01 | 4 | 5 | 9 |
| 2026-08-02 | 5 | 4 | 9 |
| 2026-08-03 | 4 | 6 | 10 |
| 2026-08-04 | 5 | 5 | 10 |
| 2026-08-05 | 4 | 1 | 5 |
| 2026-08-06 | 5 | 0 | 5 |
| 2026-08-07 | 4 | 1 | 5 |
| 2026-08-08 | 5 | 0 | 5 |

Daily order-event feed volumes (millions of events), same window:

| Date | Large-cap | Small-cap |
|---|---|---|
| 2026-08-01 | 2.1 | 1.4 |
| 2026-08-04 | 2.2 | 1.4 |
| 2026-08-05 | 2.1 | 1.5 |
| 2026-08-08 | 2.2 | 1.4 |

Change log (from the platform team):
- 2026-08-03: routine OS patching on the ingestion hosts (no config change).
- **2026-08-05: threshold set v2.4 deployed** - "raised the outsized multiple for
  small-cap instruments from 5x to 8x to reduce analyst noise".
- No other deployments or feed changes in the window.

*(Everything above is synthetic.)*
