# ProspectorPro — Demo Walkthrough

A 7-minute demo for AT&T app developers. URL once deployed: `https://prospectorpro-7474654469252811.aws.databricksapps.com`

## Setup state (already done)

- UC schema: `att_log_anomaly_catalog.prospector_pro` (5 source tables, 250K subscribers, per-campaign result tables)
- Lakebase instance: `prospectorpro` — both **sessions** (`prospectorpro.sessions`) and **app metadata** (`prospectorpro.campaigns`, `pipeline_definitions`, `approvals`, `audit_log`, `uploads`). Page loads now hit Postgres, not the warehouse.
- 4 demo campaigns seeded automatically by the app on first start:

| ID | Name | Status | Leads |
|---|---|---|---|
| C0001 | Holiday Upsell Wave 1 | Draft | — |
| C0002 | Texas High-Value Retention | Pending Approval | — |
| C0003 | Enterprise Upgrade Eligibility Q3 | Approved | 41,666 |
| C0004 | Daily Churn-Risk Refresh | Scheduled | 97,500 |

## Demo flow (talking points in **bold**)

### 1. Landing page (1 min)

- Open the app URL → land on Campaign list with status tabs.
- **"This is a Databricks App. Pure Python — Dash, dash-cytoscape, plotly. Deployed via DAB."**
- Show the 4 campaigns. Click status tabs (All / Draft / Pending Approval / Approved / Scheduled).
- **"All campaign metadata lives in Unity Catalog. Sessions live in Lakebase."**

### 2. Approved campaign — the full story (2 min)

- Click `Enterprise Upgrade Eligibility Q3`.
- **Info tab**: campaign metadata, **Run & Schedule** card with `▶ Run Now`, cron input, and recent run history; **Compliance Approval** card with the audit trail.
- Click **Run Now** → executes the saved pipeline against the warehouse, updates leads/sub-account counts in Lakebase, appends a row to `audit_log`. Recent runs section refreshes.
- **Logic tab**: a 6-node DAG — `Subscribers → filter (tenure ≥ 24, Enterprise) → join with Accounts → derive ltv_estimate → sink`.
- Click any node → properties drawer on right.
- Click **Preview SQL** → shows the compiled CTE chain that ran on the warehouse.
- **"This is a real Databricks SQL statement. The compiler is ~150 lines of Python in `app/compiler/`. Each node becomes a CTE; the sink is `CREATE OR REPLACE TABLE`."**
- **Analytics tab**: Plotly bar chart (region), pie (segment), histogram (ARPU). All read from the materialized results table.

### 3. Compliance approval flow (1.5 min)

- Back to home, click `Texas High-Value Retention` (pending).
- **Role: Marketer** (default) — the campaign is "awaiting compliance review", no buttons.
- **Switch role to Compliance Approver** in the navbar.
- Page re-renders → now you see Approve / Reject buttons.
- Hit **Approve** with a comment. Status flips to Approved. Audit log records it.
- **"Two-role demo. Real production would derive role from group membership on the OBO token from `x-forwarded-access-token`."**

### 4. Build a new campaign live (2 min)

- Home → **+ New Campaign**.
- Info tab: name it `Live Demo Campaign`, save.
- Logic tab:
  1. Add Node: id `subs`, type `Source · UC Table`. Click node, set table_fqn to `att_log_anomaly_catalog.prospector_pro.ProspectorPro_subscribers`. Apply.
  2. Add Node: id `f1`, type `Filter`. Click → predicate: `region = 'California' AND churn_score > 0.7`. Apply.
  3. Add Node: id `out`, type `Sink`.
  4. Add Edge: subs → f1, then f1 → out.
- Click **Preview SQL** → see the compiled SQL.
- Click **Run Now** → executes against the warehouse, shows N rows produced.
- Switch to Analytics tab → charts render from the new results table.

### 5. The Databricks integration story (30s)

- **DAB**: `databricks bundle deploy` ships the App, the Lakebase resource binding, the Job, and the catalog/schema/volume.
- **Lakebase**: only sessions. Connection uses OAuth tokens minted via `WorkspaceClient.database.generate_database_credential()` — no static passwords.
- **UC**: source tables, all metadata, and per-campaign result tables. Service principal has `USE_CATALOG`, `SELECT`, `MODIFY` on the target schema.
- **SQL Warehouse**: every DAG run is a single SQL statement on serverless.
- **Audit Log** (top nav): every action is captured in a Delta table.

## Resetting state between runs

```bash
# Re-seed campaigns to their initial states
DATABRICKS_CONFIG_PROFILE=fevm-att-log-anomaly python -m data.seed_demo

# Or wipe and rebuild everything
DATABRICKS_CONFIG_PROFILE=fevm-att-log-anomaly python -m data.synthetic_data_gen
DATABRICKS_CONFIG_PROFILE=fevm-att-log-anomaly python -m data.seed_demo
```

## Things to flag if asked

- **Why Dash and not React?** Original plan was React + apx + React Flow. Corporate Jamf MDM blocks all public package registries (npm, yarn, pypi) → bun couldn't install. Pivoted to Dash + dash-cytoscape — Python-only, ships in the same window. The Apps platform pulls deps from the internal pypi mirror at deploy time, which works fine.
- **Why is "Run Now" synchronous?** For demo immediacy. The Job (`ProspectorPro_pipeline_runner`) is wired up in the bundle for scheduled runs; flipping Run Now to dispatch via Jobs API is a 5-line change in `pages/campaign.py`.
- **Why is sessions the only thing in Lakebase?** Customer ask. OLTP-shaped data (campaigns, approvals, audit) belongs in Lakebase in production — it's currently in UC Delta tables, which is fine for low-throughput campaign metadata but doesn't scale to thousands of marketers writing concurrently.
