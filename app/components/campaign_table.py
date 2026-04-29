"""Reusable campaign list table with status badges."""
from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, html

STATUS_COLORS = {
    "draft": "secondary",
    "pending_approval": "warning",
    "approved": "info",
    "rejected": "danger",
    "scheduled": "primary",
    "running": "success",
    "done": "light",
}


def status_badge(status: str) -> dbc.Badge:
    color = STATUS_COLORS.get((status or "").lower(), "secondary")
    label = (status or "—").replace("_", " ").title()
    return dbc.Badge(label, color=color, pill=True)


def format_int(v) -> str:
    if pd.isna(v) or v is None:
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def campaign_table(df: pd.DataFrame) -> html.Div:
    if df is None or df.empty:
        return dbc.Alert("No campaigns yet.", color="light", className="text-center")

    rows = []
    for _, r in df.iterrows():
        rows.append(
            html.Tr(
                [
                    html.Td(html.A(r["name"], href=f"/campaign/{r['id']}", className="fw-semibold")),
                    html.Td(status_badge(r.get("status"))),
                    html.Td(r.get("priority") or "—"),
                    html.Td(r.get("organization") or "—"),
                    html.Td(r.get("owner") or "—"),
                    html.Td(format_int(r.get("lead_count"))),
                    html.Td(format_int(r.get("sub_account_count"))),
                    html.Td(
                        str(r["last_run_at"])[:19] if pd.notna(r.get("last_run_at")) else "—",
                        className="text-muted small",
                    ),
                ]
            )
        )

    return dbc.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Campaign"),
                        html.Th("Status"),
                        html.Th("Priority"),
                        html.Th("Organization"),
                        html.Th("Owner"),
                        html.Th("Leads"),
                        html.Th("Sub-Accounts"),
                        html.Th("Last Run"),
                    ]
                )
            ),
            html.Tbody(rows),
        ],
        hover=True,
        responsive=True,
        striped=False,
        className="align-middle",
    )
