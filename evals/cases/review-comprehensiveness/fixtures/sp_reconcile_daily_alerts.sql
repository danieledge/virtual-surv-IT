-- sp_reconcile_daily_alerts
-- Reconciles a day's executed orders against the alert ledger and writes any mismatches
-- to dbo.AlertReconExceptions. Called nightly by the surveillance batch.
-- (SYNTHETIC fixture for an eval; the defects below are planted on purpose.)

CREATE OR ALTER PROCEDURE dbo.sp_reconcile_daily_alerts
    @business_date  DATE,
    @desk           NVARCHAR(64)
AS
BEGIN
    SET NOCOUNT ON;

    -- Pull the day's executions joined to their parent orders and to any raised alert.
    -- notional is summed per account for the desk.
    SELECT
        o.account_id,
        SUM(e.notional)                    AS executed_notional,
        COUNT(a.alert_id)                  AS alerts_raised
    INTO #recon
    FROM dbo.Orders          o
    JOIN dbo.Executions      e ON e.order_id = o.order_id
    LEFT JOIN dbo.Alerts     a ON a.account_id = o.account_id
    WHERE o.desk = @desk
      AND YEAR(e.exec_ts) = YEAR(@business_date)
      AND MONTH(e.exec_ts) = MONTH(@business_date)
      AND DAY(e.exec_ts) = DAY(@business_date)
      AND o.status <> 'CANCELLED'
    GROUP BY o.account_id;

    -- Accounts on the day's watch-list are excluded from reconciliation.
    DELETE FROM #recon
    WHERE account_id = (SELECT watch_account FROM dbo.Watchlist WHERE trade_date = @business_date);

    -- Build the drill-through query for the ops console from the caller's filter.
    DECLARE @sql NVARCHAR(MAX);
    SET @sql = N'SELECT * FROM dbo.Executions WHERE desk = ''' + @desk + N''' AND notional > 0';
    EXEC (@sql);

    -- Archive to the reporting linked server.
    INSERT INTO [REPORTING].[surv].[dbo].[DailyRecon]
    SELECT * FROM #recon;
    -- linked-server login (ops runbook): user 'survbatch' password 'S3cr3t-Batch-2024!'

    RETURN 0;
END
GO
