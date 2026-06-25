# MI / Dashboard Specification — <DASHBOARD / REPORT>

> Produced by `data-analyst`. The build-ready specification for a management-information report or
> dashboard — what it answers, the metrics and their exact calculations, sources and lineage,
> refresh and access. Built and populated on **synthetic/masked data only — no real PII/MNPI**
> (§5). Authored in `.md`, rendered to `.html`. Every figure carries its basis: 📊 measured (a
> real number computed from the data) vs 🧠 inferred (estimate/projection).

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

| # | Metric | Definition | Calculation (formula / grain) | Source field(s) | Basis |
|---|---|---|---|---|---|
| 1 | <Alert volume> | <count of alerts raised> | `count(alert_id) by desk, day` | `<feed.field>` | 📊 |
| 2 | <Alert-to-SAR %> | <SARs / alerts> | `count(sar)/count(alert)` | `<...>` | 📊 |

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
personal data (§5) — keep it governed.

| Aspect | Value |
|---|---|
| Access / roles | <...> |
| Retention | <...> |
| Classification | masked — still personal data (§5) |

## 8. Next steps
Build → `platform-engineer` / `data-analyst`; sign-off → business owner. Define the acceptance
check (figures reconcile to source) before go-live.
