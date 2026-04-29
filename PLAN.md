# ProspectorPro — Build Plan

Last updated: 2026-04-28
Owner: Daniel Perez
Audience: AT&T App Developers (engineering side, marketer-UX literate)
Time budget: 2 days

## Goal

Demoable Telco marketing campaign platform with low-code/no-code DAG pipeline builder, deployed as a Databricks App on `fevm-att-log-anomaly.cloud.databricks.com`.

## Architecture

```
Dash (Plotly) + dash-cytoscape ──▶ Lakebase (sessions ONLY)
                  │
                  ▼
            Databricks SDK
  ┌───────────────┼──────────────────┐
  ▼               ▼                  ▼
SQL Warehouse  Jobs API         UC + Volumes
(compile DAG)  (scheduled       (campaigns, DAGs,
               runs)             approvals, audit,
                                 source data, uploads,
                                 results)
```

> **Stack pivot (2026-04-28):** Original plan was React + Vite + React Flow via `apx`. The corporate Jamf MDM blocks all public package registries (npm, yarn, pypi, maven), so `bun install` cannot run. Switched to Dash + dash-cytoscape — Python-only, installs from existing `~/.cache/uv` wheels, no npm. Same DAG→SQL→Warehouse story; lower-polish editor.

## Scope decisions

| Topic | Decision |
|---|---|
| Pipeline execution | Compile DAG → SQL → Statement Execution API on warehouse |
| DAG editor | dash-cytoscape (Python) |
| State storage | Lakebase = sessions only. UC = everything else |
| Synthetic data | Generated via Spark + Faker job |
| Compliance approval | Two roles: `marketer` + `compliance_approver`, switchable via UI dropdown |
| Scheduled runs | Real Databricks Job (`ProspectorPro_pipeline_runner`) parameterized by campaign_id |
| File uploads | CSV + XLSX via `read_files()` (Excel may fall back to CSV-only if time runs out) |

## Data model

**Lakebase**
- `prospectorpro_sessions` (id, user_email, role, data jsonb, expires_at)

**UC: `att_log_anomaly_catalog.prospector_pro`**

App metadata
- `ProspectorPro_campaigns`
- `ProspectorPro_pipeline_definitions`
- `ProspectorPro_approvals`
- `ProspectorPro_audit_log`
- `ProspectorPro_uploads`

Synthetic source data
- `ProspectorPro_subscribers`, `ProspectorPro_accounts`, `ProspectorPro_usage`, `ProspectorPro_devices`, `ProspectorPro_support_tickets`

Volume: `ProspectorPro_uploads` (CSV/XLSX dropzone)

Per-campaign sinks: `ProspectorPro_campaign_<id>_results`

## DAG node types (MVP)

`source_uc` · `source_file` · `filter` · `derive` · `join` · `sink`

Each node → CTE. Sink → `CREATE OR REPLACE TABLE … AS SELECT *`. File sources via `read_files()`.

## 2-day timeline

**Day 1 — foundation + backend**
1. DAB scaffold, Lakebase instance, app.yaml — 1.5h
2. UC catalog/schema/volume + synthetic data Job — 1.5h
3. Dash skeleton, Lakebase session store, role switcher — 1.5h
4. DAG → SQL compiler + unit tests — 2h (critical path)
5. Service layer: campaigns, approvals, uploads, runs — 1.5h

**Day 2 — UI + polish**
1. Dash multi-page shell, campaign list with status tabs — 1.5h
2. Campaign detail page: Info tab + Approvals panel — 1.5h
3. Cytoscape DAG editor — 6 node types, properties drawer — 3h (critical path)
4. Analytics tab: 3 prebuilt Plotly charts — 1h
5. Scheduling UI + Job wire-up — 0.5h
6. Seed 3–4 demo campaigns + walkthrough script — 0.5h

## Risks

1. **Excel via `read_files`** finicker than CSV. Fallback: CSV-only.
2. **Cytoscape DAG editor in 3h** is achievable but properties-panel polish may slip. Fallback: ship 4 nodes (source_uc, filter, derive, sink), defer join + source_file.
3. **Warehouse cold start** could lag the demo. Mitigation: "Preview SQL" panel so compilation story works without execution.
4. **uv cache miss** — if a needed Dash extension isn't in `~/.cache/uv`, we'll see install failures. Mitigation: vet dependencies before committing.

## Project layout

```
ProspectorPro/
  databricks.yml
  resources/{app,catalog,lakebase,job_pipeline_runner,job_synthetic_data}.yml
  app/
    main.py                 # Dash entry
    auth.py                 # session/role middleware
    pages/                  # campaign list, detail, editor, analytics
    components/             # cytoscape graph, properties panel, charts
    services/               # uc.py, lakebase.py, jobs.py
    compiler/               # dag_to_sql.py + tests
  data/synthetic_data_gen.py
  app.yaml                  # Databricks Apps manifest
  pyproject.toml
  PLAN.md, SPEC.md, README.md
```

All assets prefixed `ProspectorPro_`. Patterns from apps-cookbook.dev (Python tracks).

## References

- https://databricks.github.io/appkit/docs/
- https://apps-cookbook.dev/
- https://github.com/fpatano/visualquerybuilder
- https://docs.databricks.com/aws/en/query/formats/excel
- https://docs.databricks.com/aws/en/query/formats/csv
