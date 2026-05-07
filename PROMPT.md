# ProspectorPro — Build Prompt

The spec I'd hand to a fresh agent (or engineer) to reproduce this app cleanly, with the lessons learned baked in.

---

## Goal

Build a **Databricks App** demo of a low-code Telco campaign-builder for AT&T's app-developer engineering team. Marketers compose lead-generation pipelines by stacking named SQL steps; the platform compiles them to a single SQL statement, runs them on a serverless warehouse, and surfaces results.

The audience is **engineers, not marketers** — they will study the source. Optimize for clean Databricks-platform integration over UI polish.

## Time budget

2 days end-to-end, including DAB deployment and a working live demo URL.

## Hard constraints

- **No npm / no public pypi.** The host machine has Jamf-managed `/etc/hosts` entries that route `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, etc. to `127.0.0.1`. `bun install` and uncached `pip install` will fail. The Databricks Apps build platform **does** have a private pypi mirror, so `requirements.txt` works at deploy time. Plan accordingly:
  - Stack must be installable from local uv cache OR pre-installed in the Apps runtime.
  - Don't attempt React + bun toolchains.
- **Bundle deploy via direct engine.** The CLI's bundled-Terraform PGP key is expired. Use `DATABRICKS_BUNDLE_ENGINE=direct databricks bundle deploy` for everything.
- **Workspace.** `https://fevm-att-log-anomaly.cloud.databricks.com` (profile `fevm-att-log-anomaly`).
- **Catalog/schema.** Everything goes under `att_log_anomaly_catalog.prospector_pro`.
- **Asset prefix.** Every asset (table, volume, app, job) is prefixed `ProspectorPro_`.

## Stack

- **Frontend + backend:** Dash 2.18 + dash-bootstrap-components (both pre-installed in Apps runtime). No JS/React.
- **Persistence:** Lakebase Postgres for everything OLTP-shaped (sessions, campaign metadata, approvals, audit log, uploads). Unity Catalog for source tables, per-campaign result tables, and uploaded files via Volumes.
- **Compute:** SQL Warehouse (serverless) for compiling + executing campaign pipelines and for `LIMIT 0` schema lookups.
- **AI:** Foundation Model `databricks-meta-llama-3-3-70b-instruct` via `ai_query` (text-to-cron). Genie Space over the source tables (text-to-SQL).
- **Deployment:** Databricks Asset Bundle (DAB).
- **Lakebase auth:** mint short-lived OAuth tokens via `WorkspaceClient.database.generate_database_credential()` and pass as `PGPASSWORD`. No static passwords. Same code path works for the local user and the deployed app's service principal.

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
                 step list →  driven       result tables,
                 SQL +        runs)        CSV/XLSX
                 ai_query                  dropzone)
                 cron LLM)
```

## Data model

### Unity Catalog · `att_log_anomaly_catalog.prospector_pro`

**Source tables** (synthesized at bootstrap from `range()` + deterministic randoms; ~250K subscribers across 5K accounts with parent/sub hierarchy):

- `ProspectorPro_subscribers` — id, account_id, plan, tenure_months, arpu, churn_score, age, region, segment, last_activity_at
- `ProspectorPro_accounts` — id, parent_account_id, name, type (parent/sub), industry, employee_count
- `ProspectorPro_usage` — subscriber_id, month, calls_minutes, data_gb, sms_count
- `ProspectorPro_devices` — id, subscriber_id, model, manufacturer, age_months, eligible_for_upgrade
- `ProspectorPro_support_tickets` — id, subscriber_id, opened_at, resolved_at, sentiment, category

**Per-campaign result tables:** `ProspectorPro_campaign_<id>_results` (created on Run).

**Volume:** `ProspectorPro_uploads` for user CSV/XLSX uploads (read via `read_files()`).

### Lakebase Postgres · schema `prospectorpro`

| Table | Shape |
|---|---|
| `sessions` | session_id PK, user_email, role, created_at, expires_at, last_seen_at |
| `campaigns` | id PK, name, priority, organization, owner, **status** (`draft`/`pending_approval`/`approved`/`rejected`), **run_mode** (`ad_hoc`/`scheduled`), schedule_cron, lead_count, sub_account_count, results_table, last_run_at, last_run_status, created_at, updated_at |
| `pipeline_definitions` | (campaign_id, version) PK, dag_json (JSONB), created_by, created_at |
| `approvals` | approval_id PK, campaign_id, status, reviewer, comment, created_at |
| `audit_log` | id PK, campaign_id, actor, action, payload (JSONB), ts; index on (campaign_id, ts DESC) |
| `uploads` | upload_id PK, file_name, volume_path, file_format, inferred_schema (JSONB), uploaded_by, uploaded_at |

**Bootstrapping is self-healing:** every app boot runs `CREATE SCHEMA IF NOT EXISTS prospectorpro`, `CREATE TABLE IF NOT EXISTS …` for all of the above, then `ALTER TABLE … ADD COLUMN IF NOT EXISTS …` for any newer columns, and a one-time backfill (e.g., legacy DAG-format pipeline_definitions get wiped so the new step format takes over). `GRANT ALL ON SCHEMA prospectorpro TO PUBLIC` — both Daniel and the SP need access.

## Compiler — step list, not DAG

A pipeline is an ordered list of named steps. Each step compiles to one CTE in the final SQL. Steps reference earlier steps **by name** — no edges, no graph topology to manage.

Pydantic discriminated union, `op` field:

| `op` | Required fields | Compiles to |
|---|---|---|
| `dataset` | `name`, `source` (`uc`/`file`), `table_fqn` or (`file_path`, `file_format`) | `SELECT * FROM <table>` or `SELECT * FROM read_files(...)` |
| `filter` | `name`, `from`, `column`, `operator`, `value` | `SELECT * FROM <from> WHERE col op value` (numeric stays unquoted; `IS NULL`/`IS NOT NULL` ignore value; `IN` takes a comma list) |
| `field` | `name`, `from`, `new_field_name`, `expression` | `SELECT *, (expr) AS new_field_name FROM <from>` |
| `select` | `name`, `from`, `columns: [{column, alias}]` | `SELECT col1, col2 AS alias FROM <from>` |
| `join` | `name`, `left`, `right`, `join_type`, `keys: [{left, right}]` | `SELECT lhs.*, rhs.* FROM L AS lhs <type> JOIN R AS rhs ON lhs.k=rhs.k AND …` (use `lhs.`/`rhs.` aliases — `left`/`right` are reserved keywords) |
| `union` | `name`, `left`, `right` | `SELECT * FROM L UNION ALL SELECT * FROM R` |
| `aggregate` | `name`, `from`, `group_by: [col]`, `aggregations: [str]` | `SELECT cols, agg AS alias … GROUP BY cols` (aggregations are full SQL exprs) |
| `custom` | `name`, `sql` | the SQL verbatim, with one trailing `;` stripped (LLM/editor habit) |

**Final compilation:**
```sql
CREATE OR REPLACE TABLE <results_table> AS
WITH
  <step1.name> AS (<step1 sql>),
  <step2.name> AS (<step2 sql>),
  ...
SELECT * FROM <last_step.name>
```

**Validation:**
- Step names must be valid identifiers, unique.
- References (`from`, `left`, `right`) must point at earlier steps.
- Forbidden tokens (`;`, `--`) anywhere in user-provided strings — except a single trailing `;` on Custom steps which is silently stripped.
- `results_table` must be 3-part `catalog.schema.table`.

**Preview SQL** (no materialization): same compilation but `SELECT * FROM <step> LIMIT 200`, optionally targeting an arbitrary intermediate step.

**Tests:** ~19 pytest tests covering each step type, validation paths, alias roundtripping, and forbidden-token rejection.

## UI

### Top-level

- Multi-page Dash app: `/` (campaigns), `/campaign/<id>` (detail), `/audit` (audit log).
- Navbar with brand, page links, **Role dropdown** (Marketer / Compliance Approver), and user email.
- Session is a `dcc.Store(storage_type='local')` synced to Lakebase `sessions`. Role changes write to the store and re-render the campaign page.

### Home page

- Tabbed campaign list: **All / Draft / Pending Approval / Approved / Ad Hoc / Scheduled / Running / Done**.
- Tab id `'scheduled'` and `'ad_hoc'` filter on `run_mode`; everything else filters on `status`.
- Each row: name link, status badge, **mode badge** (Ad Hoc / Scheduled), priority, organization, owner, leads, sub-accounts, last run timestamp.
- **+ New Campaign** button → `/campaign/new`. The campaign id store is pinned to the real UUID after first creation so re-renders don't keep spawning new drafts.

### Campaign detail

Three tabs: **Info / Logic / Analytics**.

#### Info tab

- Editable metadata row (name, priority, organization, owner) + Save Info.
- 4 stat cards: Leads, Sub-Accounts, Last Run, Last Run Status.
- **Run & Schedule card:**
  - **Run mode radio** (Marketer only): Ad Hoc · run on command / Scheduled · cron-driven.
  - **Run button** — role-aware:
    - Marketer: green **▶ Run Now**, disabled until `status='approved'` (with tooltip).
    - Compliance: outlined info **🔎 Preview Run**, enabled if pipeline exists; runs preview SQL and renders rows but does **not** write to UC.
  - **Schedule UI** (Marketer + Scheduled mode only) — see § Schedule builder.
  - **Recent runs** table (top 10 from audit_log where action LIKE `pipeline_run_%`).
- **Compliance Approval card:**
  - Marketer + Draft/Rejected → **Submit for Approval** button.
  - Compliance + Pending → reviewer comment + **Approve** / **Reject**.
  - **Each button has its own dedicated callback.** Dash 2.18 silently drops a multi-Input callback when some declared Inputs aren't currently rendered, and the three approval buttons are mutually exclusive across role/status — so a single shared callback with all three Inputs would never fire.
  - Approval history table.

#### Logic tab

- Action buttons: **+ Dataset · + Filter · + Field · + Select Field · + Join · + Union · + Aggregate · + Custom Transformation · ✨ Generate with Genie**.
- A shared modal swaps body per operation. Form bodies use pattern-matched ids `{role: 'step-form', key: <field>}` so a single submit callback reads `State({"role": "step-form", "key": ALL}, "value")`.
- Step list: vertical card stack with index, op badge, step name, one-line summary, **OUTPUT** badge on the last card. Each card has **📋 Cols** (toggle to expand and show columns from `app/services/columns.py`), **Edit** (re-opens modal pre-filled), **✕** (delete).
- Column dropdowns (`column`, `group_by`, `left_key`, `right_key`) populate live when the user picks a `from`/`left`/`right` dataset. Implemented via a single callback with `Input({"role": "step-form", "key": ALL}, "value")` and dispatch on `ctx.triggered_id.key` — declaring named Inputs for each works ONLY when all of them exist in the layout, which they don't (Filter has `from` but no `left`).
- Action bar: **💾 Save Pipeline · 🔍 Preview SQL · 👁 Preview Logic · ▶ Run Now** (the last is also role-gated). Preview SQL shows the compiled `WITH … SELECT`. Preview Logic actually executes it as `LIMIT 50` and renders rows.
- Add Dataset modal includes a top-10-rows preview of the selected UC table (warehouse query, `dcc.Loading` spinner).

#### Analytics tab

- Reads `campaign.results_table`. If null → "No results yet" alert.
- Three Plotly charts when columns are present: bar (`region`), pie (`segment`), histogram (`arpu`). Falls back to a top-1000 sample table if none of those columns exist.

### ✨ Generate with Genie

- Modal with description textarea + step-name input.
- **Ask Genie** → calls `WorkspaceClient.genie.start_conversation_and_wait(space_id=PROSPECTORPRO_GENIE_SPACE_ID, content=description)` and pulls the first `attachment.query.query`.
- Pretty-print with `sqlparse.format(reindent=True, keyword_case='upper', indent_width=2, wrap_after=80)`. Strip trailing `;`. Render in a code block inside the modal.
- **Use as Custom Step** → append a `CustomStep` to the pipeline. Auto-disambiguate the step name on collision.

## Schedule builder (Marketer + Scheduled mode)

Three sub-tabs feeding a single canonical cron displayed as a read-only code block, with **Save Schedule** + **Clear**:

- **Builder** — Repeat dropdown (Hourly / Daily / Weekly / Monthly). Hour / Minute / Day-of-week / Day-of-month inputs show or hide based on frequency. Quartz cron emitted directly.
- **✨ AI** — free text + Convert button. Calls `ai_query('databricks-meta-llama-3-3-70b-instruct', '<few-shot prompt + description>')` via the warehouse, validates the response shape, writes to the cron store.
- **Custom cron** — raw 7-field Quartz input (escape hatch).

Cron values are persisted to `campaigns.schedule_cron`. The actual scheduled execution is wired but not auto-triggered in the demo (production would be one Job clone per campaign with that cron, or a sweeper Job).

## Self-bootstrap on first start

`app/main.py`'s `_bootstrap()`:
1. `lakebase.ensure_session_table()` — creates `prospectorpro.sessions`.
2. `metadata.ensure_tables()` — creates all metadata tables, runs ALTERs, GRANTs.
3. `metadata.migrate_drop_legacy_dag_definitions()` — wipes any node/edge-format definitions so the new step list format takes over (idempotent, no-op once migrated).
4. `demo_seed.seed_if_empty()` — inserts 4 demo campaigns + their pipeline definitions if `campaigns` is empty:
   - C0001 Holiday Upsell Wave 1 — Draft, Ad Hoc, no DAG yet.
   - C0002 Texas High-Value Retention — Pending Approval, 2-step filter chain.
   - C0003 Enterprise Upgrade Eligibility Q3 — Approved, 6-step pipeline (datasets, two filters, join, derive).
   - C0004 Daily Churn-Risk Refresh — Approved + Scheduled (cron `0 0 6 * * ?`), simple churn filter.

## DAB structure

```
databricks.yml
app.yaml
resources/
  catalog.yml              # schema + volume
  app.yml                  # ProspectorPro_app, with resources block:
                           #   - warehouse (sql_warehouse, CAN_USE)
                           #   - lakebase (database, CAN_CONNECT_AND_CREATE)
                           #   - pipeline-job (job, CAN_MANAGE_RUN)
  job_synthetic_data.yml   # one-shot, parameterized notebook task
  job_pipeline_runner.yml  # parameterized by campaign_id
```

`app.yaml` env:
```
PROSPECTORPRO_CATALOG = att_log_anomaly_catalog
PROSPECTORPRO_SCHEMA = prospector_pro
PROSPECTORPRO_VOLUME = ProspectorPro_uploads
PROSPECTORPRO_LAKEBASE_INSTANCE = prospectorpro
PROSPECTORPRO_GENIE_SPACE_ID = <id>
DATABRICKS_WAREHOUSE_ID = valueFrom: warehouse
PROSPECTORPRO_PIPELINE_JOB_ID = valueFrom: pipeline-job
```

## Resource provisioning (one-time)

1. Create Lakebase instance: `databricks database create-database-instance prospectorpro --capacity CU_1 --node-count 1 --enable-pg-native-login`.
2. Create UC schema + Volume via DAB.
3. Create Genie Space via the data-rooms internal API: `POST /api/2.0/data-rooms/` with the 5 source tables. Grant `CAN_RUN` to the app's service principal via `PUT /api/2.0/permissions/genie/<space_id>`.
4. Grant the app SP `USE_CATALOG` on the catalog, `USE_SCHEMA + CREATE_TABLE + MODIFY + SELECT + READ_VOLUME + WRITE_VOLUME` on the schema, and `CAN_USE` on the warehouse.

## Pitfalls (lessons learned, in order)

1. **Don't pick a stack that needs npm.** I burned ~45 minutes on apx + bun + React Flow before pivoting to Dash + dash-cytoscape (and ultimately to a form-driven step list).
2. **Use `DATABRICKS_BUNDLE_ENGINE=direct`** from the very first deploy, not after the first PGP error.
3. **Lakebase tokens, not passwords.** The platform may inject `PGHOST`/`PGUSER` but not `PGPASSWORD`. Always mint a token via `WorkspaceClient.database.generate_database_credential()`.
4. **Type-cast nullable PG params.** `WHERE %s IS NULL` confuses psycopg's type inference — use `%s::TEXT IS NULL`.
5. **Reserved aliases.** Spark SQL rejects `AS left` / `AS right`. Use `lhs`/`rhs` and rewrite user-typed `left.col` → `lhs.col`.
6. **Re-render explodes new drafts.** `_render_detail` re-fires on every `campaign-refresh` increment. If the URL is `/campaign/new` and you `_load_or_create("new")`, you create a fresh campaign on every approve/save/run. Pin the new id back into the campaign-id store after the first creation.
7. **Defensive n_clicks guard.** Action callbacks fire on layout re-mount with `n_clicks=None`. `prevent_initial_call=True` doesn't always cover dynamically re-mounted components. Always add `if not n_clicks: return no_update`.
8. **Multi-Input callbacks with mutually-exclusive Inputs silently fail.** Dash 2.18 with `suppress_callback_exceptions=True` drops a callback whose Inputs aren't all currently rendered. Split into one callback per button when buttons are role-gated.
9. **Stop the legacy data from haunting you.** The pipeline format went through one breaking change (DAG → step list). Detect and wipe legacy rows on bootstrap so old campaigns can't render with a now-incompatible compiler.
10. **Trailing `;`.** Genie always returns SQL with a trailing semicolon. Strip it both client-side (in the Genie callback) and compiler-side (CustomStep cleaner) — old saved steps unblock themselves on next compile.
11. **Don't commit `.claude/`.** Add to `.gitignore` from day 1.

## Demo flow (target)

1. Open URL. Land on campaigns list.
2. Click **C0003 Enterprise Upgrade Eligibility Q3** → Logic tab. Step list shows 6 steps. Click **📋 Cols** to expand. Click **🔍 Preview SQL**. Click **👁 Preview Logic** → see real rows.
3. Switch role to Compliance. Click **C0002 Texas High-Value Retention** → Approve. Click **🔎 Preview Run** → see rows (no UC write).
4. Switch back to Marketer. **▶ Run Now** is now enabled → click → results table created in UC. Analytics tab populates.
5. New campaign: + **Dataset** (subscribers) → + **Filter** (region = California, churn_score > 0.7) → + **Sink isn't needed; last step is the output**. Save → Submit → switch role → Approve → switch back → Run.
6. ✨ **Generate with Genie**: "Find subscribers in Florida with high ARPU" → Use as Custom Step → Save → Run.
7. Schedule a campaign via the AI tab: "every Monday at 9 AM" → Convert → cron preview shows `0 0 9 ? * MON` → Save Schedule.

## Out of scope (intentional)

- Real cron firing (the schedule_cron is stored, not connected to a sweeper Job).
- Multi-key Join via UI (only one key pair via the dropdowns; extras via the optional textarea or Custom Transformation).
- Production-grade SQL injection guards (we reject only `;` and `--`).
- Production WSGI server (Dash dev server is fine for the demo).
- File upload UI (uploads live in the UC Volume; the form just points at a path).
- Versioned pipeline editor (definitions are versioned in the table but the UI only reads the latest).
- Proper RBAC (role is a Lakebase column, not a derivation from group membership on `x-forwarded-access-token`).
