# Databricks notebook source
"""CLI seeder — same metadata as the app's auto-seed plus immediate materialization
of the Approved + Scheduled campaigns so the Analytics tab has data to render.

Note: requires `psycopg` locally. If you can't install it, the deployed app
auto-seeds metadata on first start (see `app.services.demo_seed.seed_if_empty`).
Materialization is a single SQL statement per campaign — you can also kick that
off from the app via the Run Now button on the Info tab.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.compiler import Dag, compile_dag  # noqa: E402
from app.config import SETTINGS  # noqa: E402
from app.services import demo_seed, metadata, uc  # noqa: E402


def _materialize(campaign_id: str, dag: dict) -> None:
    table = SETTINGS.table(f"campaign_{campaign_id}_results")
    sql = compile_dag(Dag.model_validate(dag), table)
    uc.execute(sql)
    leads_df = uc.query_df(f"SELECT COUNT(*) AS n FROM {table}")
    leads = int(leads_df.iloc[0]["n"]) if not leads_df.empty else 0
    sub_df = uc.query_df(f"SELECT COUNT(DISTINCT account_id) AS n FROM {table}")
    subs = int(sub_df.iloc[0]["n"]) if not sub_df.empty else 0
    is_scheduled = campaign_id == demo_seed.CAMPAIGN_SCHEDULED["id"]
    metadata.update_campaign_run_result(
        campaign_id,
        table,
        leads,
        subs,
        last_run_status="SUCCESS",
        new_status="scheduled" if is_scheduled else None,
    )
    print(f"  {campaign_id}: {leads:,} leads in {table}")


def main() -> None:
    metadata.ensure_tables()
    n = demo_seed.seed_if_empty()
    if n:
        print(f"Seeded {n} campaigns into Lakebase metadata.")
    else:
        print("Lakebase metadata already populated (skipping insert).")

    print("Materializing approved + scheduled campaigns...")
    _materialize(demo_seed.CAMPAIGN_APPROVED["id"], demo_seed.DAG_APPROVED)
    _materialize(demo_seed.CAMPAIGN_SCHEDULED["id"], demo_seed.DAG_SCHEDULED)

    print("Done.")


if __name__ == "__main__":
    main()
