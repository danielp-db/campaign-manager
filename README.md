# ProspectorPro

A Databricks App demo: a no-code/low-code platform for Telco marketing teams to build, approve, and run lead-generation campaigns. Marketers compose pipelines visually (Source → Filter → Derive → Join → Sink); the platform compiles the DAG to Databricks SQL, runs it on a serverless warehouse, and surfaces results as charts.

Built for the AT&T engineering team — focuses on the Databricks platform integration story (Apps + Unity Catalog + Lakebase + Jobs + DAB).

## Architecture

```
Dash + dash-cytoscape ──▶ Lakebase  (sessions only)
        │
        ▼
  Databricks SDK
        │
   ┌────┼─────────┐
   ▼    ▼         ▼
Warehouse  Jobs   UC + Volumes
(compile   (cron) (campaigns, DAGs, approvals,
 DAG → SQL)        audit, source data, uploads,
                   results)
```

## Project layout

```
ProspectorPro/
├── databricks.yml              # DAB
├── app.yaml                    # Apps manifest (entry + resources)
├── pyproject.toml
├── requirements.txt
├── resources/                  # DAB resources (per-resource files)
│   ├── catalog.yml             #   schema, volume
│   ├── app.yml                 #   ProspectorPro_app
│   ├── job_synthetic_data.yml  #   one-shot data gen Job
│   └── job_pipeline_runner.yml #   per-campaign runner (parameterized)
├── app/
│   ├── main.py                 # Dash entry
│   ├── auth.py                 # session/role plumbing
│   ├── config.py               # env + table names
│   ├── compiler/               # DAG → SQL compiler (+ tests)
│   ├── services/
│   │   ├── lakebase.py         #   sessions
│   │   ├── uc.py               #   warehouse SQL & metadata
│   │   ├── jobs.py             #   Jobs API
│   │   └── uploads.py          #   CSV/XLSX → Volume
│   ├── pages/                  # multi-page Dash routes
│   │   ├── home.py             #   campaign list
│   │   ├── campaign.py         #   detail tabs (Info/Logic/Analytics)
│   │   └── audit.py            #   audit log viewer
│   └── components/
│       ├── navbar.py
│       ├── campaign_table.py
│       ├── info_panel.py
│       ├── cytoscape_editor.py # the DAG canvas
│       ├── properties.py       # node config drawer
│       └── analytics_panel.py
├── data/
│   ├── synthetic_data_gen.py   # one-shot Telco data generator
│   ├── pipeline_runner.py      # per-campaign runner (callable from Jobs)
│   └── seed_demo.py            # 4 demo campaigns in different states
└── scripts/
    └── bootstrap.sh            # one-shot bootstrap (data + seeds)
```

## Quick start

```bash
# 1. Authenticate (one time)
databricks auth login --profile fevm-att-log-anomaly \
  --host https://fevm-att-log-anomaly.cloud.databricks.com

# 2. Bootstrap UC, generate synthetic data, seed demo campaigns
./scripts/bootstrap.sh

# 3. Run the app locally
DATABRICKS_CONFIG_PROFILE=fevm-att-log-anomaly python -m app.main
# → http://localhost:8000

# 4. Deploy to the workspace as a Databricks App (DAB)
databricks bundle deploy --profile fevm-att-log-anomaly
databricks bundle run ProspectorPro_app --profile fevm-att-log-anomaly
```

## Roles for the demo

The role switcher in the navbar toggles between **Marketer** and **Compliance Approver** — they see different action buttons on the campaign detail page. Real production would derive role from group membership on the OBO token.

## DAG node types

| Type | Purpose | Config |
|---|---|---|
| `source_uc` | Read a Unity Catalog table | `table_fqn` |
| `source_file` | Read a CSV/XLSX from the upload Volume via `read_files()` | `volume_path`, `file_format` |
| `filter` | SQL `WHERE` clause | `predicate` |
| `derive` | Add computed columns | `columns: [{name, expression}]` |
| `join` | Inner/Left/Right/Full join two upstream nodes | `join_type`, `on`, `select_columns` |
| `sink` | Materialize the final CTE to a Delta table | (none — table name is derived from the campaign id) |

The compiler walks the DAG topologically, emits one CTE per non-sink node, and wraps the terminal in `CREATE OR REPLACE TABLE … AS`. Forbidden tokens (`;`, `--`) are rejected at compile time.

See `app/compiler/tests/test_compiler.py` for examples.

## Resources used

| Resource | What for |
|---|---|
| Unity Catalog `att_log_anomaly_catalog.prospector_pro` | All campaign metadata + source + result tables |
| Volume `ProspectorPro_uploads` | CSV/XLSX dropzone for marketers |
| Lakebase instance `prospectorpro` | App session storage |
| SQL Warehouse | Compile + execute campaign DAGs |
| Job `ProspectorPro_pipeline_runner` | Scheduled runs (parameterized by `campaign_id`) |
| Job `ProspectorPro_synthetic_data` | One-time demo data generation |

## Notes for engineers reviewing this demo

- **Compiler is the interesting bit.** `app/compiler/compiler.py` is ~150 lines and produces real Databricks SQL. The tests show what the surface looks like.
- **No npm involved.** This is intentionally Python-only; corporate package-registry blocks made the React+apx path unworkable in the 2-day window.
- **Lakebase is sessions-only.** Everything else is in UC. Production would put OLTP-shaped data (campaigns, approvals, audit) in Lakebase too.
- **`Run Now` is synchronous** in the demo — it executes against the warehouse from the app process. Production would dispatch the Job. The plumbing for both paths is in `app/services/jobs.py`.
