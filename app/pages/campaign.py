"""Campaign detail page — Info / Logic / Analytics tabs.

Logic tab uses the new step-list pipeline editor (`logic_panel`) — buttons add
typed steps via a shared modal; each step is a named CTE in the compiled SQL.
"""
from __future__ import annotations

import re
import uuid

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.auth import ROLE_COMPLIANCE, ROLE_MARKETER
from app.components.analytics_panel import analytics_panel
from app.components.info_panel import info_panel
from app.components.logic_panel import logic_panel, step_list
from app.components.step_forms import OP_LABELS, render_form_body
from app.compiler import Pipeline, compile_pipeline, compile_pipeline_preview
from app.compiler.pipeline import CompileError
from app.config import SETTINGS
from app.services import columns, metadata, runner, uc

dash.register_page(__name__, path_template="/campaign/<campaign_id>", name="Campaign")


# --- page lifecycle ------------------------------------------------------


def _new_campaign_skeleton(campaign_id: str, owner: str) -> dict:
    return {
        "id": campaign_id,
        "name": "New campaign",
        "priority": "medium",
        "organization": "",
        "owner": owner,
        "status": "draft",
        "schedule_cron": None,
        "lead_count": None,
        "sub_account_count": None,
        "results_table": None,
        "last_run_at": None,
        "last_run_status": None,
    }


def _load_or_create(campaign_id: str, owner: str) -> tuple[dict, dict]:
    if campaign_id == "new":
        cid = str(uuid.uuid4())[:8]
        c = _new_campaign_skeleton(cid, owner)
        metadata.insert_campaign(c)
        return metadata.get_campaign(cid) or c, {"steps": []}
    c = metadata.get_campaign(campaign_id) or _new_campaign_skeleton(campaign_id, owner)
    pdef = metadata.get_latest_pipeline_definition(campaign_id)
    pipeline_data = pdef["dag"] if pdef else {"steps": []}
    if not isinstance(pipeline_data, dict) or "steps" not in pipeline_data:
        pipeline_data = {"steps": []}
    return c, pipeline_data


def layout(campaign_id: str = "new", **_):
    return html.Div(
        [
            dcc.Store(id="campaign-id-store", data=campaign_id),
            dcc.Store(id="campaign-refresh", data=0),
            dcc.Loading(html.Div(id="campaign-shell"), type="dot"),
        ]
    )


@callback(
    Output("campaign-shell", "children"),
    Input("campaign-id-store", "data"),
    Input("campaign-refresh", "data"),
    State("session-store", "data"),
)
def _render_detail(campaign_id: str, _refresh, session: dict | None):
    role = (session or {}).get("role", ROLE_MARKETER)
    owner = (session or {}).get("user_email", "demo@databricks.com")
    campaign, pipeline_data = _load_or_create(campaign_id, owner)
    cid = campaign["id"]
    approvals = metadata.list_approvals(cid)
    recent = metadata.recent_runs(cid, limit=10)

    info = info_panel(campaign, approvals, role, recent_runs=recent)
    editor = logic_panel(pipeline_data)
    analytics = analytics_panel(campaign)

    tabs = dbc.Tabs(
        id="campaign-tabs",
        active_tab="info",
        children=[
            dbc.Tab(html.Div(info, className="pt-3"), label="Info", tab_id="info"),
            dbc.Tab(html.Div(editor, className="pt-3"), label="Logic", tab_id="logic"),
            dbc.Tab(html.Div(analytics, className="pt-3"), label="Analytics", tab_id="analytics"),
        ],
    )

    return html.Div(
        [
            dcc.Store(id="campaign-loaded-id", data=cid),
            dbc.Breadcrumb(
                items=[
                    {"label": "Campaigns", "href": "/"},
                    {"label": campaign["name"] or cid, "active": True},
                ]
            ),
            tabs,
        ]
    )


# --- Logic tab: load UC tables once on mount ----------------------------


@callback(
    Output("uc-tables-store", "data"),
    Input("campaign-loaded-id", "data"),
    State("uc-tables-store", "data"),
)
def _load_uc_tables(_id, current):
    if current:
        return no_update
    try:
        return uc.list_tables_in_catalog(SETTINGS.catalog)
    except Exception:
        return []


# --- Logic tab: render step list reactively -----------------------------


@callback(
    Output("pipeline-step-list", "children"),
    Input("pipeline-store", "data"),
)
def _render_step_list(pipeline):
    return step_list(pipeline)


# --- Logic tab: open / cancel / submit modal ----------------------------


@callback(
    Output("step-modal-state", "data"),
    Input({"role": "open-modal", "op": ALL}, "n_clicks"),
    Input({"role": "step-edit", "name": ALL}, "n_clicks"),
    Input("step-modal-cancel", "n_clicks"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _modal_state_router(_opens, _edits, _cancel, pipeline):
    triggered = ctx.triggered_id
    if not triggered:
        return no_update

    if triggered == "step-modal-cancel":
        return None

    # Pattern-matching trigger: dict with role + extra
    if isinstance(triggered, dict):
        role = triggered.get("role")
        if role == "open-modal":
            # n_clicks may be None on initial fire; ignore that
            value = ctx.triggered[0].get("value")
            if not value:
                return no_update
            return {"op": triggered["op"], "editing": None}
        if role == "step-edit":
            value = ctx.triggered[0].get("value")
            if not value:
                return no_update
            name = triggered["name"]
            steps = (pipeline or {}).get("steps") or []
            step = next((s for s in steps if s["name"] == name), None)
            if not step:
                return no_update
            return {"op": step["op"], "editing": name}
    return no_update


@callback(
    Output("step-modal", "is_open"),
    Output("step-modal-title", "children"),
    Output("step-modal-body", "children"),
    Input("step-modal-state", "data"),
    State("pipeline-store", "data"),
    State("uc-tables-store", "data"),
)
def _render_modal(state, pipeline, uc_tables):
    if not state:
        return False, "", html.Div()
    op = state["op"]
    editing = state.get("editing")
    title = f"Edit {OP_LABELS.get(op, op).removeprefix('Add ')}" if editing else OP_LABELS.get(op, op)

    step_dict: dict | None = None
    steps = (pipeline or {}).get("steps") or []
    if editing:
        step_dict = next((s for s in steps if s["name"] == editing), None)

    # Available "from" / "left" / "right" names: any step defined BEFORE the
    # currently-edited step (or all of them, if adding new).
    if editing and step_dict:
        idx = next((i for i, s in enumerate(steps) if s["name"] == editing), len(steps))
        names = [s["name"] for s in steps[:idx]]
    else:
        names = [s["name"] for s in steps]

    # Pre-compute columns for any pre-set from/left/right so dropdowns are populated on open.
    columns_for: dict[str, list[str]] = {}
    if step_dict:
        if op in ("filter", "field", "select", "aggregate") and step_dict.get("from"):
            columns_for["from"] = columns.get_step_columns(pipeline, step_dict["from"])
        if op == "join":
            if step_dict.get("left"):
                columns_for["left"] = columns.get_step_columns(pipeline, step_dict["left"])
            if step_dict.get("right"):
                columns_for["right"] = columns.get_step_columns(pipeline, step_dict["right"])

    body = render_form_body(op, names, uc_tables or [], step_dict, columns_for)
    return True, title, body


# --- Logic tab: dataset source toggle (UC vs File) ----------------------


@callback(
    Output("dataset-uc-block", "style"),
    Output("dataset-file-block", "style"),
    Input({"role": "step-form", "key": "source"}, "value"),
    prevent_initial_call=True,
)
def _toggle_dataset_source(source):
    if source == "file":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


# --- Logic tab: live column dropdown updates ---------------------------


@callback(
    Output({"role": "step-form", "key": ALL}, "options"),
    Input({"role": "step-form", "key": "from"}, "value"),
    Input({"role": "step-form", "key": "left"}, "value"),
    Input({"role": "step-form", "key": "right"}, "value"),
    State({"role": "step-form", "key": ALL}, "id"),
    State({"role": "step-form", "key": ALL}, "options"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _update_column_options(from_val, left_val, right_val, ids, current_options, pipeline_data):
    keys_present = {idobj["key"] for idobj in ids}
    needs_from = bool(keys_present & {"column", "group_by"})
    needs_left = "left_key" in keys_present
    needs_right = "right_key" in keys_present

    cols_from = (
        columns.get_step_columns(pipeline_data, from_val)
        if (needs_from and from_val)
        else []
    )
    cols_left = (
        columns.get_step_columns(pipeline_data, left_val)
        if (needs_left and left_val)
        else []
    )
    cols_right = (
        columns.get_step_columns(pipeline_data, right_val)
        if (needs_right and right_val)
        else []
    )

    out: list = []
    for idobj, cur in zip(ids, current_options):
        key = idobj["key"]
        if key in ("column", "group_by"):
            out.append([{"label": c, "value": c} for c in cols_from])
        elif key == "left_key":
            out.append([{"label": c, "value": c} for c in cols_left])
        elif key == "right_key":
            out.append([{"label": c, "value": c} for c in cols_right])
        else:
            out.append(no_update)
    return out


# --- Logic tab: dataset preview (top 10 rows of selected UC table) ------


@callback(
    Output("dataset-preview-area", "children"),
    Input({"role": "step-form", "key": "table_fqn"}, "value"),
    prevent_initial_call=True,
)
def _preview_dataset(table_fqn):
    if not table_fqn:
        return html.Div()
    try:
        df = uc.query_df(f"SELECT * FROM {table_fqn} LIMIT 10")
    except Exception as exc:
        return dbc.Alert(
            f"Could not preview {table_fqn}: {exc}", color="warning", className="small mb-0"
        )
    if df.empty:
        return html.Div(f"({table_fqn} is empty)", className="text-muted small")
    return html.Div(
        [
            html.Div("Preview · top 10 rows", className="small text-muted mb-1"),
            html.Div(
                dbc.Table.from_dataframe(
                    df.head(10), striped=True, hover=True, responsive=True, size="sm"
                ),
                style={"max-height": "260px", "overflow": "auto"},
            ),
        ]
    )


# --- Logic tab: run preview SQL and render rows -------------------------


@callback(
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Input("pipeline-preview-rows", "n_clicks"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _preview_pipeline_rows(_n, pipeline_data):
    steps = (pipeline_data or {}).get("steps") or []
    if not steps:
        return dbc.Alert(
            "Pipeline is empty — add at least one step.", color="warning", duration=3000
        )
    try:
        pipeline = Pipeline.model_validate(pipeline_data)
    except Exception as exc:
        return dbc.Alert(f"Invalid pipeline: {exc}", color="danger")
    try:
        sql = compile_pipeline_preview(pipeline, limit=50)
    except CompileError as exc:
        return dbc.Alert(f"Compile error: {exc}", color="danger")
    try:
        df = uc.query_df(sql)
    except Exception as exc:
        return dbc.Alert(f"Preview failed: {exc}", color="danger")
    last_step = steps[-1]["name"]
    if df.empty:
        return dbc.Alert(
            f"Pipeline compiled successfully but produced 0 rows from `{last_step}`.",
            color="info",
        )
    return dbc.Card(
        [
            dbc.CardHeader(
                f"Preview · final step `{last_step}` · top {len(df)} rows of "
                f"{', '.join(df.columns[:6])}{' ...' if len(df.columns) > 6 else ''}"
            ),
            dbc.CardBody(
                dbc.Table.from_dataframe(
                    df, striped=True, hover=True, responsive=True, size="sm"
                ),
                style={"max-height": "500px", "overflow": "auto"},
            ),
        ]
    )


# --- Logic tab: submit step --------------------------------------------


def _parse_columns_text(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"\s+AS\s+", line, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            out.append({"column": parts[0].strip(), "alias": parts[1].strip()})
        else:
            out.append({"column": line})
    return out


def _parse_keys_text(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        left, right = line.split("=", 1)
        out.append({"left": left.strip(), "right": right.strip()})
    return out


def _build_step(op: str, fields: dict) -> dict:
    name = (fields.get("name") or "").strip()
    if op == "dataset":
        source = fields.get("source") or "uc"
        step = {"op": "dataset", "name": name, "source": source}
        if source == "uc":
            step["table_fqn"] = (fields.get("table_fqn") or "").strip()
        else:
            step["file_path"] = (fields.get("file_path") or "").strip()
            step["file_format"] = fields.get("file_format") or "csv"
        return step
    if op == "filter":
        return {
            "op": "filter",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "column": (fields.get("column") or "").strip(),
            "operator": fields.get("operator") or "=",
            "value": fields.get("value") or "",
        }
    if op == "field":
        return {
            "op": "field",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "new_field_name": (fields.get("new_field_name") or "").strip(),
            "expression": (fields.get("expression") or "").strip(),
        }
    if op == "select":
        return {
            "op": "select",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "columns": _parse_columns_text(fields.get("columns_text", "")),
        }
    if op == "join":
        primary = []
        lkey = (fields.get("left_key") or "").strip()
        rkey = (fields.get("right_key") or "").strip()
        if lkey and rkey:
            primary.append({"left": lkey, "right": rkey})
        primary.extend(_parse_keys_text(fields.get("extra_keys_text", "")))
        return {
            "op": "join",
            "name": name,
            "left": (fields.get("left") or "").strip(),
            "right": (fields.get("right") or "").strip(),
            "join_type": fields.get("join_type") or "INNER",
            "keys": primary,
        }
    if op == "union":
        return {
            "op": "union",
            "name": name,
            "left": (fields.get("left") or "").strip(),
            "right": (fields.get("right") or "").strip(),
        }
    if op == "aggregate":
        agg_lines = [
            line.strip()
            for line in (fields.get("aggregations_text") or "").splitlines()
            if line.strip()
        ]
        gb = fields.get("group_by") or []
        if isinstance(gb, str):
            gb = [gb]
        return {
            "op": "aggregate",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "group_by": [c for c in gb if c],
            "aggregations": agg_lines,
        }
    if op == "custom":
        return {
            "op": "custom",
            "name": name,
            "sql": (fields.get("sql") or "").strip(),
        }
    raise ValueError(f"unknown op: {op}")


@callback(
    Output("pipeline-store", "data"),
    Output("step-modal-state", "data", allow_duplicate=True),
    Output("pipeline-action-output", "children"),
    Input("step-modal-submit", "n_clicks"),
    State("step-modal-state", "data"),
    State({"role": "step-form", "key": ALL}, "value"),
    State({"role": "step-form", "key": ALL}, "id"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _submit_step(_n, state, values, ids, pipeline):
    if not state:
        return no_update, no_update, no_update
    fields = {idobj["key"]: v for v, idobj in zip(values, ids)}
    try:
        step = _build_step(state["op"], fields)
    except Exception as exc:
        return (
            no_update,
            no_update,
            dbc.Alert(f"Could not build step: {exc}", color="danger"),
        )

    if not step["name"]:
        return no_update, no_update, dbc.Alert("Step name is required.", color="warning")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", step["name"]):
        return (
            no_update,
            no_update,
            dbc.Alert(
                "Step name must start with a letter/underscore and contain only "
                "letters, digits, and underscores.",
                color="warning",
            ),
        )

    steps = list((pipeline or {}).get("steps") or [])
    editing = state.get("editing")
    if editing:
        new_steps = [step if s["name"] == editing else s for s in steps]
    else:
        if any(s["name"] == step["name"] for s in steps):
            return (
                no_update,
                no_update,
                dbc.Alert(
                    f"A step named '{step['name']}' already exists.", color="warning"
                ),
            )
        new_steps = steps + [step]

    return (
        {"steps": new_steps},
        None,
        dbc.Alert(
            f"{'Updated' if editing else 'Added'} step {step['name']}.",
            color="success",
            duration=3000,
        ),
    )


# --- Logic tab: delete step --------------------------------------------


@callback(
    Output("pipeline-store", "data", allow_duplicate=True),
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Input({"role": "step-delete", "name": ALL}, "n_clicks"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _delete_step(_clicks, pipeline):
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        return no_update, no_update
    value = ctx.triggered[0].get("value")
    if not value:
        return no_update, no_update
    name = triggered.get("name")
    steps = list((pipeline or {}).get("steps") or [])
    new_steps = [s for s in steps if s["name"] != name]
    if len(new_steps) == len(steps):
        return no_update, no_update
    return (
        {"steps": new_steps},
        dbc.Alert(f"Removed step {name}.", color="success", duration=3000),
    )


# --- Logic tab: action bar (Save / Preview / Run) ----------------------


@callback(
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("pipeline-save", "n_clicks"),
    Input("pipeline-preview", "n_clicks"),
    Input("pipeline-run", "n_clicks"),
    State("pipeline-store", "data"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _pipeline_action(_s, _p, _r, pipeline_data, campaign_id, session, refresh):
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    steps = (pipeline_data or {}).get("steps") or []
    if not steps:
        return dbc.Alert("Pipeline is empty — add at least one step.", color="warning"), no_update
    try:
        pipeline = Pipeline.model_validate(pipeline_data)
    except Exception as exc:
        return dbc.Alert(f"Invalid pipeline: {exc}", color="danger"), no_update

    if triggered == "pipeline-save":
        version = metadata.save_pipeline_definition(campaign_id, pipeline_data, user)
        metadata.append_audit(campaign_id, user, "pipeline_save", {"version": version})
        return (
            dbc.Alert(f"Saved pipeline definition v{version}.", color="success", duration=4000),
            (refresh or 0) + 1,
        )

    if triggered == "pipeline-preview":
        try:
            sql = compile_pipeline_preview(pipeline, limit=200)
        except CompileError as exc:
            return dbc.Alert(f"Compile error: {exc}", color="danger"), no_update
        return (
            dbc.Card(
                [
                    dbc.CardHeader("Preview SQL"),
                    dbc.CardBody(html.Pre(sql, style={"white-space": "pre-wrap", "font-size": 13})),
                ]
            ),
            no_update,
        )

    if triggered == "pipeline-run":
        latest = metadata.get_latest_pipeline_definition(campaign_id)
        if not latest:
            metadata.save_pipeline_definition(campaign_id, pipeline_data, user)
        try:
            result = runner.run_campaign(campaign_id, user)
        except Exception as exc:
            return (
                dbc.Alert(f"Run failed: {exc}", color="danger"),
                (refresh or 0) + 1,
            )
        return (
            dbc.Alert(
                f"Pipeline ran in {result['elapsed_s']}s — "
                f"{result['lead_count']:,} rows in {result['results_table']}.",
                color="success",
            ),
            (refresh or 0) + 1,
        )

    return no_update, no_update


# --- Approvals callbacks ---------------------------------------------------


@callback(
    Output("approval-result", "children"),
    Output("campaign-refresh", "data"),
    Input("approval-submit", "n_clicks"),
    Input("approval-approve", "n_clicks"),
    Input("approval-reject", "n_clicks"),
    State("approval-comment", "value"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _approval_action(_s, _a, _r, comment, campaign_id, session, refresh):
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    role = (session or {}).get("role", ROLE_MARKETER)

    if triggered == "approval-submit" and role == ROLE_MARKETER:
        new_status, msg = "pending_approval", "Submitted for compliance review."
    elif triggered == "approval-approve" and role == ROLE_COMPLIANCE:
        new_status, msg = "approved", "Approved."
    elif triggered == "approval-reject" and role == ROLE_COMPLIANCE:
        new_status, msg = "rejected", "Rejected."
    else:
        return dbc.Alert("Action not permitted for your role.", color="warning"), no_update

    metadata.update_campaign_status(campaign_id, new_status)
    metadata.append_approval(campaign_id, new_status, user, comment or "")
    metadata.append_audit(campaign_id, user, f"approval_{new_status}", {"comment": comment or ""})
    return dbc.Alert(msg, color="success", duration=3000), (refresh or 0) + 1


# --- Info tab callbacks ----------------------------------------------------


@callback(
    Output("ci-save-alert", "children"),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("ci-save", "n_clicks"),
    State("ci-name", "value"),
    State("ci-priority", "value"),
    State("ci-organization", "value"),
    State("ci-owner", "value"),
    State("campaign-loaded-id", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _save_info(_n, name, priority, organization, owner, campaign_id, refresh):
    metadata.update_campaign_info(campaign_id, name, priority, organization, owner)
    return (
        dbc.Alert("Saved.", color="success", duration=2500, className="mt-2"),
        (refresh or 0) + 1,
    )


@callback(
    Output("info-run-output", "children"),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("info-run-now", "n_clicks"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _run_now(_n, campaign_id, session, refresh):
    if not campaign_id:
        return no_update, no_update
    user = (session or {}).get("user_email", "demo@databricks.com")
    try:
        result = runner.run_campaign(campaign_id, user)
    except ValueError as e:
        return dbc.Alert(str(e), color="warning", duration=4000), no_update
    except Exception as e:
        return (
            dbc.Alert(f"Run failed: {e}", color="danger"),
            (refresh or 0) + 1,
        )
    return (
        dbc.Alert(
            f"Pipeline ran in {result['elapsed_s']}s — "
            f"{result['lead_count']:,} rows in {result['results_table']}.",
            color="success",
            duration=6000,
        ),
        (refresh or 0) + 1,
    )


@callback(
    Output("info-run-output", "children", allow_duplicate=True),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("info-cron-save", "n_clicks"),
    State("info-cron", "value"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _save_schedule(_n, cron, campaign_id, session, refresh):
    if not campaign_id:
        return no_update, no_update
    user = (session or {}).get("user_email", "demo@databricks.com")
    cron = (cron or "").strip() or None
    metadata.update_campaign_schedule(campaign_id, cron)
    metadata.append_audit(campaign_id, user, "schedule_updated", {"cron": cron})
    msg = f"Schedule set: {cron}" if cron else "Schedule cleared."
    return (
        dbc.Alert(msg, color="success", duration=3500),
        (refresh or 0) + 1,
    )
