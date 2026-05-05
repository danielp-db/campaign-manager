# ProspectorPro

A Databricks App demo: a low-code platform for Telco marketing teams to build, approve, and run lead-generation campaigns. Marketers compose pipelines by stacking named SQL steps (Dataset → Filter → Field → Select → Join → Union → Aggregate → Custom). The platform compiles the step list to a single Databricks SQL statement, runs it on a serverless warehouse, and renders results in-page.

Built for the AT&T engineering team — focuses on the Databricks platform integration story (Apps + Unity Catalog + Lakebase + SQL Warehouse + Genie + Foundation Models + DAB).

Live URL: https://prospectorpro-7474654469252811.aws.databricksapps.com

## Architecture

```
                Dash + dash-bootstrap-components
                              │
       ┌──────────────────────┼─────────────────────────────┐
       ▼                      ▼                             ▼
   Lakebase              Databricks SDK                Genie Space
   (Postgres)                  │                       (text-to-SQL)
   sessions +     ┌────────────┼──────────────┐
   app metadata   ▼            ▼              ▼
                Warehouse    Jobs API     UC + Volumes
                (compile     (cron        (source data,
                 step list →  driven       per-campaign
                 SQL +        runs)        result tables,
                 ai_query                  CSV/XLSX
                 cron LLM)                 dropzone)
```

App metadata (campaigns, pipeline definitions, approvals, audit log, uploads) lives in Lakebase Postgres for sub-100ms reads. Source data, per-campaign result tables, and uploaded files live in Unity Catalog. The SQL warehouse compiles + runs every campaign; foundation-model calls (`ai_query`) and Genie spaces handle the AI features.

## Project layout

```
ProspectorPro/
├── databricks.yml                   # DAB
├── app.yaml                         # Apps manifest (entry + resources + env)
├── pyproject.toml / requirements.txt
├── resources/                       # DAB resource files
│   ├── catalog.yml                  #   schema, volume
│   ├── app.yml                      #   ProspectorPro_app
│   ├── job_synthetic_data.yml       #   one-shot data-gen Job
│   └── job_pipeline_runner.yml      #   per-campaign runner Job
├── app/
│   ├── main.py                      # Dash entry, auto-bootstrap, auto-seed
│   ├── auth.py                      # session/role plumbing
│   ├── config.py                    # env + table names
│   ├── compiler/
│   │   ├── pipeline.py              #   step models + SQL CTE compiler
│   │   └── tests/test_pipeline.py   #   19 unit tests
│   ├── services/
│   │   ├── lakebase.py              #   Postgres connection w/ OAuth tokens
│   │   ├── metadata.py              #   campaigns / approvals / audit (Postgres)
│   │   ├── columns.py               #   column resolution per step
│   │   ├── uc.py                    #   warehouse SQL access
│   │   ├── runner.py                #   compile + execute a campaign
│   │   ├── ai_cron.py               #   text-to-cron via ai_query + builder
│   │   ├── genie.py                 #   Genie Space text-to-SQL wrapper
│   │   ├── jobs.py                  #   Jobs API for scheduled runs
│   │   ├── uploads.py               #   CSV/XLSX → UC Volume
│   │   └── demo_seed.py             #   4 demo campaigns + DAGs
│   ├── pages/
│   │   ├── home.py                  #   campaign list with status / mode tabs
│   │   ├── campaign.py              #   detail tabs (Info / Logic / Analytics)
│   │   └── audit.py                 #   audit log viewer
│   └── components/
│       ├── navbar.py
│       ├── campaign_table.py
│       ├── info_panel.py            #   stats + Run/Schedule + Approvals
│       ├── logic_panel.py           #   step buttons + step list + Genie modal
│       ├── step_forms.py            #   modal form bodies per step type
│       └── analytics_panel.py
├── data/
│   ├── synthetic_data_gen.py        # one-shot Telco data generator
│   ├── pipeline_runner.py           # per-campaign runner (Jobs entry-point)
│   └── seed_demo.py                 # CLI seeder + materializer
└── scripts/
    └── bootstrap.sh                 # one-shot bootstrap (data + seeds)
```

## Quick start

```bash
# Authenticate once
databricks auth login --profile fevm-att-log-anomaly \
  --host https://fevm-att-log-anomaly.cloud.databricks.com

# Generate synthetic source data (250K subscribers + 4 supporting tables)
./scripts/bootstrap.sh

# Deploy as a Databricks App
DATABRICKS_BUNDLE_ENGINE=direct databricks bundle deploy --profile fevm-att-log-anomaly
DATABRICKS_BUNDLE_ENGINE=direct databricks bundle run ProspectorPro_app --profile fevm-att-log-anomaly
```

`DATABRICKS_BUNDLE_ENGINE=direct` is required while the bundled-Terraform PGP key is expired upstream.

The deployed app self-bootstraps on first start: it ALTERs the Lakebase schema to add any missing columns, migrates legacy data, and seeds 4 demo campaigns if the campaigns table is empty.

## Roles

The navbar dropdown toggles between **Marketer** and **Compliance Approver**. Switching roles re-renders the campaign detail page.

| Role | What they can do |
|---|---|
| Marketer | Create / edit campaigns, build pipelines, edit run mode, edit schedule, **▶ Run Now** (materializes to UC). Run is disabled until status is `approved`. |
| Compliance Approver | Approve / Reject pending campaigns. **🔎 Preview Run** compiles + executes the pipeline read-only and renders rows in-page; **does not write to UC**. Cannot edit run mode or schedule. |

Production would derive role from group membership on the OBO token (`x-forwarded-access-token`).

## Logic tab — step types

Pipelines are an ordered list of named steps. Each step compiles to one CTE in the final SQL; the last step's output is what gets materialized.

| Type | Adds | Compiles to |
|---|---|---|
| **Dataset** | A leaf step over a UC table or uploaded file | `SELECT * FROM <table>` or `SELECT * FROM read_files(...)` |
| **Filter** | A WHERE predicate (column + operator + value) | `SELECT * FROM <upstream> WHERE col op value` |
| **Field** | A computed column from a SQL expression | `SELECT *, (expr) AS new_col FROM <upstream>` |
| **Select Field** | Column projection + aliases | `SELECT col1, col2 AS alias FROM <upstream>` |
| **Join** | Multi-key inner/left/right/full join | `SELECT lhs.*, rhs.* FROM L JOIN R ON …` |
| **Union** | UNION ALL of two upstream steps | `SELECT * FROM L UNION ALL SELECT * FROM R` |
| **Aggregate** | GROUP BY + SQL aggregation expressions | `SELECT cols, agg AS alias … GROUP BY cols` |
| **Custom Transformation** | A user-authored CTE body | the SQL verbatim, stripped of trailing `;` |

The compiler walks the steps in order, emits CTEs by name, and wraps the terminal in `CREATE OR REPLACE TABLE … AS`. Forbidden tokens (`;`, `--`) are rejected at compile time, except a single trailing `;` on Custom steps which is silently stripped (LLM/SQL-editor habit).

UI niceties:
- **Add Dataset** modal previews the top 10 rows of the selected UC table inline.
- **Filter / Aggregate / Join** column dropdowns auto-populate from the upstream step's actual columns. UC datasets resolve via `information_schema`; derived steps via `LIMIT 0` on the warehouse.
- Each step card on the canvas has a **📋 Cols** link — click to expand and see what columns it produces.
- **🔍 Preview SQL** shows the compiled CTE chain.
- **👁 Preview Logic** runs the preview SQL and renders the top 50 rows of the final step in-page (no UC write).
- **▶ Run Now** materializes to a Delta table named `ProspectorPro_campaign_<id>_results`.

## ✨ Generate with Genie

The Logic tab has a **✨ Generate with Genie** button. The modal asks for a plain-English description, sends it to `ProspectorPro_genie` (a Genie Space pre-configured over the 5 source tables), and renders the returned SQL pretty-printed via `sqlparse`. **Use as Custom Step** appends it as a `CustomStep` so you can immediately Save / Preview / Run. Genie's trailing `;` is stripped.

## Run mode

Each campaign has an explicit `run_mode`:

| Mode | UI |
|---|---|
| **Ad Hoc** (default) | Schedule UI hidden. Pipeline runs only when Marketer clicks Run Now. |
| **Scheduled** | Schedule builder appears. The compiled cron is shown live and persisted as `schedule_cron`. |

The Marketer toggles via a radio at the top of the Run & Schedule card. Switching to Ad Hoc auto-clears `schedule_cron`.

## Schedule builder

Three tabs feed a single canonical cron value (shown as a read-only code block above Save/Clear):

- **Builder** — Repeat dropdown (Hourly / Daily / Weekly / Monthly). Hour / Minute / Day-of-week / Day-of-month inputs show or hide based on frequency.
- **✨ AI** — free-text "describe a schedule" + Convert button. Calls `ai_query('databricks-meta-llama-3-3-70b-instruct', '…')` via the warehouse with a few-shot prompt. The returned cron is sanitized + validated.
- **Custom cron** — raw 7-field Quartz input (escape hatch).

## Compliance approval flow

Status enum: `draft` → `pending_approval` → `approved` | `rejected`. The approval card on the Info tab shows different actions per role:

- Marketer + Draft / Rejected → **Submit for Approval**
- Compliance + Pending Approval → reviewer comment + **Approve** / **Reject**

Each transition writes:
- `prospectorpro.campaigns.status` (UPDATE)
- `prospectorpro.approvals` (append-only history)
- `prospectorpro.audit_log` (append-only)

Each button has its own dedicated callback (Dash 2.18 silently drops multi-Input callbacks where some Inputs aren't currently rendered).

## Resources used

| Resource | What for |
|---|---|
| UC `att_log_anomaly_catalog.prospector_pro` | Source tables (`ProspectorPro_*`), per-campaign result tables, file Volume |
| UC Volume `ProspectorPro_uploads` | CSV/XLSX dropzone for file-source datasets |
| Lakebase instance `prospectorpro`, schema `prospectorpro` | App sessions + all campaign metadata (campaigns, pipeline_definitions, approvals, audit_log, uploads) |
| SQL Warehouse `Serverless Starter` | Compile + execute every pipeline; back the column-resolution `LIMIT 0` queries; back `ai_query` for the AI cron mode |
| Genie Space `ProspectorPro_genie` (id `01f14754a2b81492beef965eb83559f8`) | Natural-language to SQL over the 5 source tables |
| Foundation Model endpoint `databricks-meta-llama-3-3-70b-instruct` | Text-to-cron LLM call via `ai_query` |
| Job `ProspectorPro_pipeline_runner` | Scheduled runs (parameterized by `campaign_id`) — wired but not auto-triggered in the demo |

## Notes for engineers reviewing this demo

- **Compiler.** `app/compiler/pipeline.py` is ~250 lines, generates real Databricks SQL via `WITH` + `CREATE OR REPLACE TABLE`, and is covered by 19 tests in `app/compiler/tests/test_pipeline.py`. Forbidden-token check is the only injection guard — predicates and expressions otherwise pass through verbatim. Production should parse and re-emit them.
- **Lakebase auth.** `app/services/lakebase.py` always mints a short-lived OAuth token via `WorkspaceClient.database.generate_database_credential()` and passes it as `PGPASSWORD` — no static passwords. Works whether the app is local (Daniel's user) or deployed (the app's service principal).
- **Run Now is synchronous.** The Logic-tab and Info-tab Run buttons call `runner.run_campaign()` in-process. Scheduled runs would dispatch `ProspectorPro_pipeline_runner` Job via Jobs API. The plumbing for both paths is in `app/services/{runner,jobs}.py`.
- **No npm.** Corporate Jamf MDM blocks public package registries (`registry.npmjs.org`, `pypi.org`, etc.). The original React+apx plan was scrapped because `bun install` couldn't run; Dash + dash-bootstrap-components is Python-only and the Apps platform's pypi mirror handles the install at deploy time.
- **Direct deploy required.** `databricks bundle deploy` needs `DATABRICKS_BUNDLE_ENGINE=direct` until the bundled Terraform's PGP key is rotated upstream.
- **Self-healing migrations.** Every app boot runs `metadata.ensure_tables()` which `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for any new fields and backfills sensible defaults — so iterating on the schema doesn't require manual SQL.
- **Status persistence quirks.** Approval buttons each have their own single-Input callback because Dash 2.18's multi-Input callbacks silently drop when any Input isn't currently rendered (e.g., Marketer can't see Approve, so a callback declaring all three buttons would never fire for the Submit button). Lesson learned the hard way during the demo build.
