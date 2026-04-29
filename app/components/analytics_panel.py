"""Analytics tab — 3 prebuilt Plotly charts on the campaign's results table."""
from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import dcc, html

from app.services import uc


def _safe_query(sql: str) -> pd.DataFrame:
    try:
        return uc.query_df(sql)
    except Exception:
        return pd.DataFrame()


def analytics_panel(campaign: dict) -> html.Div:
    if not campaign:
        return html.Div()
    results_table = campaign.get("results_table")
    if not results_table:
        return dbc.Alert(
            "No results yet. Run the pipeline at least once to see analytics.",
            color="light",
            className="text-center",
        )

    cols = uc.list_columns(results_table)
    col_names = {c["column_name"] for c in cols}

    charts: list = []

    if "region" in col_names:
        df = _safe_query(
            f"SELECT region, COUNT(*) AS leads FROM {results_table} GROUP BY region ORDER BY leads DESC"
        )
        if not df.empty:
            fig = px.bar(df, x="region", y="leads", title="Leads by Region")
            charts.append(dbc.Col(dcc.Graph(figure=fig), md=6))

    if "segment" in col_names:
        df = _safe_query(
            f"SELECT segment, COUNT(*) AS leads FROM {results_table} GROUP BY segment"
        )
        if not df.empty:
            fig = px.pie(df, names="segment", values="leads", title="Leads by Segment", hole=0.4)
            charts.append(dbc.Col(dcc.Graph(figure=fig), md=6))

    if "arpu" in col_names:
        df = _safe_query(f"SELECT arpu FROM {results_table} LIMIT 50000")
        if not df.empty:
            fig = px.histogram(df, x="arpu", nbins=40, title="ARPU Distribution")
            charts.append(dbc.Col(dcc.Graph(figure=fig), md=12))

    if not charts:
        df = _safe_query(f"SELECT * FROM {results_table} LIMIT 1000")
        if df.empty:
            return dbc.Alert("Results table is empty.", color="warning")
        return html.Div(
            [
                html.H5("Result Sample"),
                dbc.Table.from_dataframe(df.head(20), striped=True, hover=True, responsive=True),
            ]
        )

    summary = _safe_query(f"SELECT COUNT(*) AS leads FROM {results_table}")
    leads = int(summary.iloc[0]["leads"]) if not summary.empty else 0

    return html.Div(
        [
            dbc.Alert(
                [html.Span("Results table: "), html.Code(results_table), f" — {leads:,} leads"],
                color="info",
                className="py-2",
            ),
            dbc.Row(charts, className="g-3"),
        ]
    )
