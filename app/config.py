"""Centralized configuration. All env vars and table names live here."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    catalog: str
    schema: str
    volume: str
    warehouse_id: str
    lakebase_instance: str
    pipeline_job_id: str | None
    app_port: int

    @property
    def schema_fqn(self) -> str:
        return f"{self.catalog}.{self.schema}"

    @property
    def volume_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/{self.volume}"

    def table(self, name: str) -> str:
        """Fully-qualified UC table name with ProspectorPro_ prefix."""
        return f"{self.catalog}.{self.schema}.ProspectorPro_{name}"


def load_settings() -> Settings:
    return Settings(
        catalog=os.getenv("PROSPECTORPRO_CATALOG", "att_log_anomaly_catalog"),
        schema=os.getenv("PROSPECTORPRO_SCHEMA", "prospector_pro"),
        volume=os.getenv("PROSPECTORPRO_VOLUME", "ProspectorPro_uploads"),
        warehouse_id=os.getenv("DATABRICKS_WAREHOUSE_ID", "0b11e3b9a1c7aff0"),
        lakebase_instance=os.getenv("PROSPECTORPRO_LAKEBASE_INSTANCE", "prospectorpro"),
        pipeline_job_id=os.getenv("PROSPECTORPRO_PIPELINE_JOB_ID"),
        app_port=int(os.getenv("DATABRICKS_APP_PORT", "8000")),
    )


SETTINGS = load_settings()


# Logical table names (used with SETTINGS.table())
T_CAMPAIGNS = "campaigns"
T_PIPELINE_DEFS = "pipeline_definitions"
T_APPROVALS = "approvals"
T_AUDIT = "audit_log"
T_UPLOADS = "uploads"

# Synthetic source tables
T_SUBSCRIBERS = "subscribers"
T_ACCOUNTS = "accounts"
T_USAGE = "usage"
T_DEVICES = "devices"
T_TICKETS = "support_tickets"

ALL_SOURCE_TABLES = [T_SUBSCRIBERS, T_ACCOUNTS, T_USAGE, T_DEVICES, T_TICKETS]
