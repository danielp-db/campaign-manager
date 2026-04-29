"""Databricks Jobs API — runs the campaign pipeline runner."""
from __future__ import annotations

from databricks.sdk import WorkspaceClient

from app.config import SETTINGS


def trigger_pipeline_run(campaign_id: str) -> int:
    """Kick off ProspectorPro_pipeline_runner with the given campaign_id."""
    if not SETTINGS.pipeline_job_id:
        raise RuntimeError("PROSPECTORPRO_PIPELINE_JOB_ID not configured")
    w = WorkspaceClient()
    run = w.jobs.run_now(
        job_id=int(SETTINGS.pipeline_job_id),
        job_parameters={"campaign_id": campaign_id},
    )
    return run.run_id


def set_schedule(job_id: int, cron: str | None, timezone: str = "America/New_York") -> None:
    w = WorkspaceClient()
    job = w.jobs.get(job_id=job_id)
    settings = job.settings
    if cron:
        from databricks.sdk.service.jobs import CronSchedule, PauseStatus
        settings.schedule = CronSchedule(
            quartz_cron_expression=cron,
            timezone_id=timezone,
            pause_status=PauseStatus.UNPAUSED,
        )
    else:
        settings.schedule = None
    w.jobs.update(job_id=job_id, new_settings=settings)


def get_recent_runs(job_id: int, limit: int = 20) -> list[dict]:
    w = WorkspaceClient()
    runs = w.jobs.list_runs(job_id=job_id, limit=limit)
    out = []
    for r in runs:
        out.append(
            {
                "run_id": r.run_id,
                "state": r.state.life_cycle_state.value if r.state else None,
                "result": r.state.result_state.value if r.state and r.state.result_state else None,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "campaign_id": (r.job_parameters or {}).get("campaign_id"),
            }
        )
    return out
