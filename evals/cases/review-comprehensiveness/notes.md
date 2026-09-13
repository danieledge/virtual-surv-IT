# Why this case exists

P0 of the best-in-class review uplift (backlog #9). The owner said reviews "don't feel
comprehensive." This turns that into a number: six defects across four dimensions in one SQL
proc, scored by recall. Run it under each config to prove the uplift moved recall, not to gate a
release:

- consolidated-sonnet (pre-uplift baseline): `--team-model sonnet`, one pass.
- split-opus (P1 + P2): parallel per-facet passes at opus.
- split-opus + map (P3): the above plus the up-front skeleton.

The two table-stakes defects (SEC-INJECTION, SEC-SECRET) are `must_find`; a review that misses
either fails outright. The four subtler defects are planted-but-not-required, so the case records
depth (recall) even when it does not gate. A best-in-class review names all six.

The fixture is SYNTHETIC. The defects are planted deliberately; it is not real production SQL.
