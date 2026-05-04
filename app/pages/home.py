"""Home page — campaign list with status filters."""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html

from app.components.campaign_table import campaign_table
from app.services import metadata

dash.register_page(__name__, path="/", name="Campaigns")

STATUS_TABS = [
    ("all", "All"),
    ("draft", "Draft"),
    ("pending_approval", "Pending Approval"),
    ("approved", "Approved"),
    ("ad_hoc", "Ad Hoc"),
    ("scheduled", "Scheduled"),
    ("running", "Running"),
    ("done", "Done"),
]


def layout() -> html.Div:
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(html.H3("Campaigns", className="mb-0"), md=8),
                    dbc.Col(
                        dbc.Button(
                            "+ New Campaign",
                            href="/campaign/new",
                            color="primary",
                            className="float-end",
                        ),
                        md=4,
                    ),
                ],
                className="mb-3",
            ),
            dbc.Tabs(
                id="home-status-tabs",
                active_tab="all",
                children=[
                    dbc.Tab(label=label, tab_id=tid) for tid, label in STATUS_TABS
                ],
                className="mb-3",
            ),
            dcc.Loading(html.Div(id="home-table"), type="dot"),
        ]
    )


@callback(Output("home-table", "children"), Input("home-status-tabs", "active_tab"))
def _render_table(status: str):
    df = metadata.list_campaigns(status if status != "all" else None)
    return campaign_table(df)
