"""Campaign Info tab — metadata + stats + Run/Schedule + Approvals."""
from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from app.auth import ROLE_COMPLIANCE, ROLE_MARKETER
from app.components.campaign_table import format_int, status_badge


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
                    dbc.Col(_run_schedule_card(campaign, recent_runs), md=7),
                    dbc.Col(_approvals_card(campaign, approvals, role), md=5),
                ],
                className="g-3",
            ),
        ]
    )


def _run_schedule_card(campaign: dict, recent_runs: pd.DataFrame | None) -> dbc.Card:
    has_def = bool(campaign.get("results_table") or campaign.get("status") not in ("draft", None))
    cron = campaign.get("schedule_cron") or ""

    schedule_status = "—"
    if campaign.get("schedule_cron"):
        schedule_status = f"Active · {campaign.get('schedule_cron')}"
    elif (campaign.get("status") or "").lower() == "scheduled":
        schedule_status = "Scheduled (cron unset)"

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
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Button(
                                    "▶ Run Now",
                                    id="info-run-now",
                                    color="success",
                                    className="w-100",
                                    disabled=not has_def,
                                ),
                                md=4,
                            ),
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
                    dbc.Label("Schedule (Quartz cron — empty to clear)", className="small"),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Input(
                                    id="info-cron",
                                    value=cron,
                                    placeholder="0 0 6 * * ?",
                                    style={"font-family": "monospace"},
                                ),
                                md=8,
                            ),
                            dbc.Col(
                                dbc.Button(
                                    "Save Schedule",
                                    id="info-cron-save",
                                    color="primary",
                                    className="w-100",
                                ),
                                md=4,
                            ),
                        ],
                        className="g-2",
                    ),
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
