"""Single source of truth for compiling + executing a campaign DAG.

Used by both the DAG editor's Run button and the Info tab's Run Now button.
For scheduled runs, the same function is callable from a notebook/Job task.
"""
from __future__ import annotations

import time

from app.compiler import Dag, compile_dag
from app.config import SETTINGS
from app.services import metadata, uc


def run_campaign(campaign_id: str, actor: str) -> dict:
    """Run the latest pipeline definition. Returns run summary."""
    campaign = metadata.get_campaign(campaign_id)
    if not campaign:
        raise ValueError(f"campaign {campaign_id} not found")
    pdef = metadata.get_latest_pipeline_definition(campaign_id)
    if not pdef:
        raise ValueError("Save a pipeline definition before running.")

    dag = Dag.model_validate(pdef["dag"])
    results_table = SETTINGS.table(
        f"campaign_{campaign_id.replace('-', '_')}_results"
    )
    sql_text = compile_dag(dag, results_table)

    metadata.append_audit(
        campaign_id, actor, "pipeline_run_start", {"version": pdef["version"]}
    )
    started = time.time()
    try:
        uc.execute(sql_text)
        df = uc.query_df(f"SELECT COUNT(*) AS n FROM {results_table}")
        leads = int(df.iloc[0]["n"]) if not df.empty else 0
        sub_df = uc.query_df(
            f"SELECT COUNT(DISTINCT account_id) AS n FROM {results_table}"
        )
        sub_count = int(sub_df.iloc[0]["n"]) if not sub_df.empty else 0
    except Exception as exc:
        elapsed = round(time.time() - started, 2)
        metadata.append_audit(
            campaign_id,
            actor,
            "pipeline_run_failed",
            {"error": str(exc), "elapsed_s": elapsed},
        )
        metadata.update_campaign_run_result(
            campaign_id, "", 0, 0, last_run_status="FAILED"
        )
        raise

    elapsed = round(time.time() - started, 2)
    cur_status = (campaign.get("status") or "").lower()
    if campaign.get("schedule_cron"):
        new_status = "scheduled"
    elif cur_status in ("draft", "rejected"):
        new_status = cur_status  # don't override a draft just because someone ran it
    else:
        new_status = "approved"

    metadata.update_campaign_run_result(
        campaign_id,
        results_table,
        leads,
        sub_count,
        last_run_status="SUCCESS",
        new_status=new_status,
    )
    metadata.append_audit(
        campaign_id,
        actor,
        "pipeline_run_success",
        {
            "elapsed_s": elapsed,
            "lead_count": leads,
            "sub_account_count": sub_count,
            "results_table": results_table,
        },
    )
    return {
        "results_table": results_table,
        "lead_count": leads,
        "sub_account_count": sub_count,
        "elapsed_s": elapsed,
    }
