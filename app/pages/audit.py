"""Audit log page — append-only history of all campaign actions."""
from __future__ import annotations

import json

import dash
import dash_bootstrap_components as dbc
from dash import html

from app.services import metadata

dash.register_page(__name__, path="/audit", name="Audit Log")


def layout() -> html.Div:
    df = metadata.query_audit_log(limit=200)
    if df.empty:
        return dbc.Alert("No audit events yet.", color="light")
    rows = []
    for _, r in df.iterrows():
        payload = r["payload"] if isinstance(r["payload"], dict) else {}
        rows.append(
            html.Tr(
                [
                    html.Td(str(r["ts"])[:19], className="text-muted small"),
                    html.Td(r["campaign_id"] or "—"),
                    html.Td(r["actor"]),
                    html.Td(html.Code(r["action"])),
                    html.Td(html.Code(json.dumps(payload), style={"font-size": 11})),
                ]
            )
        )
    return html.Div(
        [
            html.H3("Audit Log", className="mb-3"),
            dbc.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th("When"),
                                html.Th("Campaign"),
                                html.Th("Actor"),
                                html.Th("Action"),
                                html.Th("Payload"),
                            ]
                        )
                    ),
                    html.Tbody(rows),
                ],
                striped=True,
                hover=True,
                responsive=True,
            ),
        ]
    )
