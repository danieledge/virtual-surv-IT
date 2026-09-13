We have a SQL stored procedure, `sp_reconcile_daily_alerts.sql`, that runs in the nightly
surveillance batch. It reconciles a day's executed orders against the alert ledger and writes
mismatches to an exceptions table.

Please open an engagement and run a **Deep** code review of it. This is going into a regulated
production surveillance pipeline, so I want it thorough: correctness, security, performance, and
anything architectural that would bite us in operations. Write the review up in the engagement
workspace so I can hand it to the developer.
