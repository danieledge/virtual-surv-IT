# MI / Dashboard Specification - <DASHBOARD / REPORT>

> Produced by `data-analyst`. The build-ready specification for a management-information report or
> dashboard - what it answers, the metrics and their exact calculations, sources and lineage,
> refresh and access. Built and populated on **synthetic/masked data only - no real PII/MNPI**
> (§5). Authored in `.md`, rendered to `.html`. Every figure carries its basis: 📊 measured (a
> real number computed from the data) vs 🧠 inferred (estimate/projection).

> **Document control** · ID `MI-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Dashboard / report** | <name> |
| **Purpose** | <one-line decision it supports> |
| **Audience** | <who consumes it: MLRO / desk head / regulator / ops> |
| **Refresh cadence** | <real-time / daily / weekly / monthly> |
| **Owner** | <data-analyst · business owner> |
| **Date / author** | <YYYY-MM-DD · data-analyst> |

## 1. Purpose & audience
The decisions this MI drives and for whom. State the surveillance obligation/MI need it serves
(§2) so it's traceable, not vanity metrics.

## 2. Questions it answers
The handful of concrete questions the dashboard must answer at a glance.

- Q1: <e.g. are alert volumes within budget by desk this month?>
- Q2: <e.g. what is the alert-to-SAR conversion trend?>

## 3. Metrics / KPIs
Each metric: an unambiguous definition, the **exact calculation** (so two people get the same
number), and its source. Note 📊/🧠 basis where a value is estimated rather than computed.
The alert-to-SAR/STR conversion row is mandatory for every surveillance MI spec.

| # | Metric | Definition | Numerator | Denominator | Calculation (formula / grain) | Source field(s) | Basis |
|---|---|---|---|---|---|---|---|
| 1 | Alert volume | Count of alerts raised | alerts raised | n/a | `count(alert_id) by desk, day` | `<feed.field>` | 📊 |
| 2 | False-positive rate | Alerts closed as FP / total alerts reviewed | alerts closed as FP | total alerts reviewed | `count(closed_FP) / count(reviewed)` | `<...>` | 📊 |
| 3 | **Alert-to-SAR/STR conversion** | **SARs or STRs filed as a result of an alert / alerts reviewed** | **SARs/STRs filed (alert-sourced)** | **alerts reviewed in period** | **`count(SAR_or_STR where source=alert) / count(reviewed)`** | `<...>` | 📊 |
| 4 | Analyst productivity | Alerts reviewed per analyst per day | alerts reviewed | analyst-days | `count(reviewed) / (analysts x working_days)` | `<...>` | 📊 |
| 5 | <add further metrics> | | | | | | |

**SLA / threshold-breach alerting:** for each metric above, specify the threshold that triggers
an out-of-band notification to the MI owner and the action owner.

| Metric | SLA / expected range | Breach threshold | Alert channel | Action owner |
|---|---|---|---|---|
| Alert volume | <within X% of monthly baseline> | <+/-Y%> | <email / Slack / ticket> | <role> |
| False-positive rate | <target <= X%> | <>Y%> | <...> | <...> |
| Alert-to-SAR/STR conversion | <target >= X%> | <<Y%> | <...> | <...> |
| Analyst productivity | <target >= X per day> | <<Y> | <...> | <...> |

## 4. Dimensions & filters
The axes the user slices by and the default/optional filters.

| Dimension | Source field | Default | Notes |
|---|---|---|---|

## 5. Visualisations & layout
Each panel: chart type, the metric(s)/dimension(s) it shows, and why that encoding.

| Panel | Type (line / bar / table / heatmap) | Shows | Notes |
|---|---|---|---|

## 6. Data sources & lineage
Upstream datasets, the dictionary that defines them, the pipeline that produces them, and the
masking config. Refresh dependencies/SLAs.

| Source dataset | Dictionary | Pipeline / job | Masking config | Refresh SLA |
|---|---|---|---|---|

## 7. Access, retention & governance
Who can see it (least privilege), retention period, and the reminder that masked output is still
personal data (§5) - keep it governed.

| Aspect | Value |
|---|---|
| Access / roles | <...> |
| Retention | <...> |
| Classification | masked - still personal data (§5) |

## 8. Reconciliation acceptance
Before go-live and at each scheduled review, confirm MI figures reconcile to the source systems.

| Figure | Source system / field | Reconciliation method | Acceptable tolerance | Sign-off by | Cadence |
|---|---|---|---|---|---|
| <e.g. alert count> | <alerts table / alert_id> | <count(MI) = count(source) for period> | <0 variance> | <data owner> | <daily> |
| <e.g. SAR/STR count> | <case management system> | <match on period + desk> | <0 variance> | <MLRO> | <monthly> |

## 9. Next steps
Build → `platform-engineer` / `data-analyst`; sign-off → business owner. Reconciliation
acceptance (§8) is a go-live gate.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
