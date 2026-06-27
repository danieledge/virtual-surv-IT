# Rubric: surveillance coverage assessment (`/assess-coverage`)

Scores a coverage assessment 0.0-1.0 + pass/fail. Deterministic scorer handles which planted
gaps were found; this rubric covers the rest.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Gap detection** | Every seeded gap found - an unmonitored typology, **and** a dead/missing feed (the MW79 blind spot). *(deterministic: recall + must-find)* | 0.40 |
| **Feed-health reasoning** | States, per feed, whether it's live / complete / timely - not just "feeds exist". Catches the silent-drop. | 0.20 |
| **Typology→scenario→feed map** | A traceable map, not prose; each in-scope risk linked to a scenario and the feeds it needs. | 0.15 |
| **Routing** | Each gap routed to the right owner (feed gap → platform-engineer; data gap → data-quality-reviewer; missing scenario → rules-developer). | 0.10 |
| **Obligation cited** | Each in-scope risk tied to the obligation it serves. | 0.10 |
| **No dead-end** | Closes with prioritised remediation + a recommendation. | 0.05 |

**Pass:** all must-find gaps found, weighted score >= 0.75.
**Auto-fail:** the seeded dead/missing feed missed (that's the headline failure mode this exists to catch).
