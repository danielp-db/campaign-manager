"""Campaign Info tab — metadata + stats + Run/Schedule + Approvals."""
from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from app.auth import ROLE_COMPLIANCE, ROLE_MARKETER
from app.components.campaign_table import format_int, status_badge
from app.services.ai_cron import DAYS_OF_WEEK, FREQUENCIES


def stat_card(label: str, value: str) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(label, className="text-muted small text-uppercase"),
                html.Div(value, className="fs-4 fw-semibold"),
            ]
        ),
        className="h-100",
    )


def info_panel(
    campaign: dict,
    approvals: pd.DataFrame,
    role: str,
    recent_runs: pd.DataFrame | None = None,
) -> html.Div:
    if not campaign:
        return dbc.Alert("Campaign not found", color="danger")

    name = dbc.Input(id="ci-name", value=campaign.get("name", ""), placeholder="Campaign name")
    priority = dcc.Dropdown(
        id="ci-priority",
        options=[
            {"label": "Low", "value": "low"},
            {"label": "Medium", "value": "medium"},
            {"label": "High", "value": "high"},
        ],
        value=campaign.get("priority") or "medium",
        clearable=False,
    )
    org = dbc.Input(id="ci-organization", value=campaign.get("organization", ""), placeholder="Organization")
    owner = dbc.Input(id="ci-owner", value=campaign.get("owner", ""), placeholder="Owner")

    last_run = (
        str(campaign["last_run_at"])[:19] if pd.notna(campaign.get("last_run_at")) else "Not yet run"
    )

    metadata_row = dbc.Row(
        [
            dbc.Col([html.Label("Name", className="form-label small"), name], md=6),
            dbc.Col([html.Label("Priority", className="form-label small"), priority], md=2),
            dbc.Col([html.Label("Organization", className="form-label small"), org], md=2),
            dbc.Col([html.Label("Owner", className="form-label small"), owner], md=2),
        ],
        className="mb-3 g-2",
    )

    stats = dbc.Row(
        [
            dbc.Col(stat_card("Leads", format_int(campaign.get("lead_count"))), md=3),
            dbc.Col(stat_card("Sub-Accounts", format_int(campaign.get("sub_account_count"))), md=3),
            dbc.Col(stat_card("Last Run", last_run), md=3),
            dbc.Col(stat_card("Last Run Status", campaign.get("last_run_status") or "—"), md=3),
        ],
        className="g-2 mb-3",
    )

    save_btn = dbc.Button("Save Info", id="ci-save", color="primary", className="me-2")
    save_alert = html.Div(id="ci-save-alert")

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(html.H4(campaign.get("name") or "Untitled campaign"), md=8),
                    dbc.Col(
                        html.Div(status_badge(campaign.get("status")), className="text-end"),
                        md=4,
                    ),
                ],
                className="mb-3",
            ),
            metadata_row,
            stats,
            html.Div([save_btn, save_alert], className="mb-4"),
            dbc.Row(
                [
                    dbc.Col(_run_schedule_card(campaign, recent_runs, role), md=7),
                    dbc.Col(_approvals_card(campaign, approvals, role), md=5),
                ],
                className="g-3",
            ),
        ]
    )


def _schedule_builder() -> html.Div:
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Repeat", className="small"),
                            dcc.Dropdown(
                                id="sb-frequency",
                                options=FREQUENCIES,
                                value="daily",
                                clearable=False,
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Hour (24h)", className="small"),
                            dbc.Input(
                                id="sb-hour", type="number", min=0, max=23, value=6, step=1
                            ),
                        ],
                        md=2,
                        id="sb-hour-col",
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Minute", className="small"),
                            dbc.Input(
                                id="sb-minute", type="number", min=0, max=59, value=0, step=1
                            ),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Day of week", className="small"),
                            dcc.Dropdown(
                                id="sb-dow",
                                options=DAYS_OF_WEEK,
                                value="MON",
                                clearable=False,
                            ),
                        ],
                        md=3,
                        id="sb-dow-col",
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Day of month", className="small"),
                            dbc.Input(
                                id="sb-dom", type="number", min=1, max=31, value=1, step=1
                            ),
                        ],
                        md=2,
                        id="sb-dom-col",
                    ),
                ],
                className="g-2",
            ),
        ]
    )


def _ai_cron_input() -> html.Div:
    return html.Div(
        [
            dbc.InputGroup(
                [
                    dbc.Input(
                        id="sb-ai-text",
                        placeholder="e.g. every Monday at 9 AM, or every 15 minutes",
                    ),
                    dbc.Button("✨ Convert", id="sb-ai-convert", color="info"),
                ]
            ),
            html.Div(
                "Powered by Databricks ai_query with a foundation model.",
                className="form-text",
            ),
            html.Div(id="sb-ai-output", className="mt-2"),
        ]
    )


def _run_schedule_card(
    campaign: dict, recent_runs: pd.DataFrame | None, role: str = ROLE_MARKETER
) -> dbc.Card:
    cron = campaign.get("schedule_cron") or ""
    status = (campaign.get("status") or "").lower()
    run_mode = (campaign.get("run_mode") or "ad_hoc").lower()
    is_scheduled = run_mode == "scheduled"
    is_compliance = role == ROLE_COMPLIANCE
    has_def = bool(
        campaign.get("results_table") or status not in ("draft", "", None)
    )

    if is_compliance:
        run_button = dbc.Button(
            "🔎 Preview Run",
            id="info-run-now",
            color="info",
            outline=True,
            className="w-100",
            disabled=not has_def,
            title="Compliance preview — runs the pipeline read-only and shows rows without writing to UC.",
        )
    else:
        run_button = dbc.Button(
            "▶ Run Now",
            id="info-run-now",
            color="success",
            className="w-100",
            disabled=(status != "approved"),
            title=(
                "Run the pipeline and materialize results to Unity Catalog."
                if status == "approved"
                else "Run is disabled until the campaign is approved by Compliance."
            ),
        )

    if is_scheduled:
        schedule_status = (
            f"Active · {campaign.get('schedule_cron')}"
            if campaign.get("schedule_cron")
            else "Scheduled (cron unset)"
        )
    else:
        schedule_status = "Manual / on-command only"

    runs_table: html.Div | dbc.Table = html.Div(
        "No runs yet.", className="text-muted small"
    )
    if recent_runs is not None and not recent_runs.empty:
        rows = []
        for _, r in recent_runs.iterrows():
            payload = r["payload"] if isinstance(r["payload"], dict) else {}
            outcome = (
                "✅ SUCCESS"
                if r["action"] == "pipeline_run_success"
                else ("❌ FAILED" if r["action"] == "pipeline_run_failed" else "▶ START")
            )
            details: list = []
            if "lead_count" in payload:
                details.append(f"{int(payload['lead_count']):,} leads")
            if "elapsed_s" in payload:
                details.append(f"{payload['elapsed_s']}s")
            if r["action"] == "pipeline_run_failed" and "error" in payload:
                details.append(str(payload["error"])[:60])
            rows.append(
                html.Tr(
                    [
                        html.Td(str(r["ts"])[:19], className="text-muted small"),
                        html.Td(outcome),
                        html.Td(" · ".join(details) or "—", className="small"),
                    ]
                )
            )
        runs_table = dbc.Table(
            [
                html.Thead(
                    html.Tr([html.Th("When"), html.Th("Outcome"), html.Th("Details")])
                ),
                html.Tbody(rows),
            ],
            size="sm",
            className="mb-0",
        )

    return dbc.Card(
        [
            dbc.CardHeader("Run & Schedule"),
            dbc.CardBody(
                [
                    html.Div(
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        html.Div(
                                            "Run mode", className="text-muted small mb-1"
                                        ),
                                        dbc.RadioItems(
                                            id="info-run-mode",
                                            options=[
                                                {"label": "Ad Hoc · run on command", "value": "ad_hoc"},
                                                {"label": "Scheduled · cron-driven", "value": "scheduled"},
                                            ],
                                            value=run_mode,
                                            inline=True,
                                        ),
                                    ],
                                    md=12,
                                ),
                            ],
                            className="mb-3 g-2",
                        ),
                        style={"display": "none"} if is_compliance else {},
                    ),
                    dbc.Row(
                        [
                            dbc.Col(run_button, md=4),
                            dbc.Col(
                                html.Div(
                                    [
                                        html.Div("Schedule status", className="text-muted small"),
                                        html.Div(schedule_status, className="fw-semibold"),
                                    ]
                                ),
                                md=8,
                            ),
                        ],
                        className="mb-3 align-items-center g-2",
                    ),
                    dbc.Collapse(
                        id="info-schedule-collapse",
                        is_open=is_scheduled and not is_compliance,
                        children=[
                    dbc.Tabs(
                        id="sb-tabs",
                        active_tab="builder",
                        children=[
                            dbc.Tab(
                                html.Div(_schedule_builder(), className="pt-3"),
                                label="Builder",
                                tab_id="builder",
                            ),
                            dbc.Tab(
                                html.Div(_ai_cron_input(), className="pt-3"),
                                label="✨ AI",
                                tab_id="ai",
                            ),
                            dbc.Tab(
                                html.Div(
                                    [
                                        dbc.Label(
                                            "Quartz cron expression (7 fields)",
                                            className="small",
                                        ),
                                        dbc.Input(
                                            id="sb-custom-cron",
                                            value=cron,
                                            placeholder="0 0 6 * * ?",
                                            style={"font-family": "monospace"},
                                        ),
                                    ],
                                    className="pt-3",
                                ),
                                label="Custom cron",
                                tab_id="custom",
                            ),
                        ],
                        className="mb-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Div("Cron preview", className="text-muted small"),
                                    html.Code(
                                        id="info-cron-preview",
                                        children=cron or "(none)",
                                        className="d-block p-2 bg-light rounded",
                                    ),
                                ],
                                md=8,
                            ),
                            dbc.Col(
                                [
                                    dbc.Button(
                                        "Save Schedule",
                                        id="info-cron-save",
                                        color="primary",
                                        className="w-100 mb-1",
                                    ),
                                    dbc.Button(
                                        "Clear",
                                        id="info-cron-clear",
                                        color="secondary",
                                        outline=True,
                                        className="w-100",
                                    ),
                                ],
                                md=4,
                            ),
                        ],
                        className="g-2 mt-2",
                    ),
                        ],
                    ),
                    # Hidden store: the canonical cron the user will save.
                    dcc.Store(id="info-cron-store", data=cron),
                    html.Div(id="info-run-output", className="mt-3"),
                    html.H6(
                        "Recent runs",
                        className="mt-3 mb-2 text-uppercase small text-muted",
                    ),
                    runs_table,
                ]
            ),
        ]
    )


def _approvals_card(campaign: dict, approvals: pd.DataFrame, role: str) -> dbc.Card:
    status = (campaign.get("status") or "draft").lower()

    history_rows = []
    if approvals is not None and not approvals.empty:
        for _, a in approvals.iterrows():
            history_rows.append(
                html.Tr(
                    [
                        html.Td(str(a["created_at"])[:19], className="text-muted small"),
                        html.Td(a["status"]),
                        html.Td(a.get("reviewer") or "—"),
                        html.Td(a.get("comment") or "—"),
                    ]
                )
            )
    history = (
        dbc.Table(
            [
                html.Thead(
                    html.Tr(
                        [html.Th("When"), html.Th("Status"), html.Th("Reviewer"), html.Th("Comment")]
                    )
                ),
                html.Tbody(history_rows),
            ],
            size="sm",
            className="mb-0",
        )
        if history_rows
        else html.Div("No approval history.", className="text-muted small")
    )

    actions: list = []
    if role == ROLE_MARKETER:
        if status in ("draft", "rejected"):
            actions.append(
                dbc.Button("Submit for Approval", id="approval-submit", color="warning", className="me-2")
            )
        else:
            actions.append(
                dbc.Alert(
                    f"Awaiting compliance review (current status: {status.replace('_', ' ').title()}).",
                    color="info",
                    className="mb-0",
                )
            )
    elif role == ROLE_COMPLIANCE:
        if status == "pending_approval":
            actions += [
                dbc.Input(id="approval-comment", placeholder="Reviewer comment", className="mb-2"),
                dbc.Button("Approve", id="approval-approve", color="success", className="me-2"),
                dbc.Button("Reject", id="approval-reject", color="danger"),
            ]
        else:
            actions.append(
                dbc.Alert(
                    f"Nothing to review here (current status: {status.replace('_', ' ').title()}).",
                    color="light",
                    className="mb-0",
                )
            )

    return dbc.Card(
        [
            dbc.CardHeader("Compliance Approval"),
            dbc.CardBody(
                [
                    html.Div(actions, className="mb-3"),
                    html.Div(id="approval-result"),
                    html.H6("History", className="mt-3 mb-2 text-uppercase small text-muted"),
                    history,
                ]
            ),
        ]
    )
