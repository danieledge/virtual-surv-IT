# Request: alert-export de-duplication utility (synthetic)

Hi - I'm the surveillance operations lead. Our overnight transaction-monitoring batch exports
alerts to CSV, and whenever the batch restarts mid-run the downstream case-management tool
ingests duplicates. The ops analysts are triaging the same alert two or three times.

We need a small utility that cleans a daily alert export before ingestion:

1. Read a daily alert export CSV with columns:
   `alert_id, trader_id, instrument, alert_type, alert_ts, score`
2. Drop exact duplicate `alert_id` rows, keeping the row with the latest `alert_ts`.
3. Flag near-duplicates: rows with the same `trader_id` + `instrument` + `alert_type` within
   10 minutes of each other should mark the later row `suppressed=true`, with an audit column
   holding the surviving row's `alert_id` (the analysts must be able to trace every
   suppression).
4. Write the cleaned CSV next to the input, plus a one-line run summary (rows in, rows out,
   suppressed count).

Constraints: Python, standard library only, and it must be testable - the suppression window
will be challenged by our QA so we need evidence it behaves at the boundaries. All data
involved is synthetic samples we generate ourselves; no production data will be used at any
point. Please build it properly, test it, and hand it over with your usual documentation.

*(Synthetic request - the firm, batch and columns are invented.)*
