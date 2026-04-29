# Databricks notebook source
"""Generate synthetic Telco source data for the ProspectorPro demo.

Runs via the SQL warehouse — no Spark cluster required. Each table is built from
range() + deterministic-ish random expressions so the demo is repeatable.

Usage (local):
    python -m data.synthetic_data_gen
"""
from __future__ import annotations

import sys

# Allow `python -m data.synthetic_data_gen` from the project root
sys.path.insert(0, ".")

from app.config import SETTINGS  # noqa: E402
from app.services import uc  # noqa: E402

N_ACCOUNTS = 5_000  # 4_500 sub-accounts under 500 parent accounts
N_SUBSCRIBERS = 250_000
N_USAGE_MONTHS = 6


STATEMENTS: list[tuple[str, str]] = [
    (
        "accounts",
        f"""
        CREATE OR REPLACE TABLE {SETTINGS.table("accounts")} AS
        WITH parents AS (
            SELECT
                'A' || LPAD(CAST(id AS STRING), 6, '0') AS account_id,
                CAST(NULL AS STRING) AS parent_account_id,
                'Parent ' || CAST(id AS STRING) AS account_name,
                'parent' AS account_type,
                element_at(array('Manufacturing','Retail','Healthcare','Finance','Energy','Logistics','Tech','Public Sector'),
                    CAST(id % 8 AS INT) + 1) AS industry,
                CAST(100 + (id * 37) % 9900 AS INT) AS employee_count
            FROM range(500)
        ),
        subs AS (
            SELECT
                'A' || LPAD(CAST(id + 500 AS STRING), 6, '0') AS account_id,
                'A' || LPAD(CAST(id % 500 AS STRING), 6, '0') AS parent_account_id,
                'Sub-Account ' || CAST(id AS STRING) AS account_name,
                'sub' AS account_type,
                element_at(array('Manufacturing','Retail','Healthcare','Finance','Energy','Logistics','Tech','Public Sector'),
                    CAST(id % 8 AS INT) + 1) AS industry,
                CAST(10 + (id * 11) % 990 AS INT) AS employee_count
            FROM range({N_ACCOUNTS - 500})
        )
        SELECT * FROM parents UNION ALL SELECT * FROM subs
        """,
    ),
    (
        "subscribers",
        f"""
        CREATE OR REPLACE TABLE {SETTINGS.table("subscribers")} AS
        SELECT
            'S' || LPAD(CAST(id AS STRING), 9, '0') AS subscriber_id,
            'A' || LPAD(CAST(id % {N_ACCOUNTS} AS STRING), 6, '0') AS account_id,
            element_at(array('Unlimited Pro','Unlimited Plus','Family Saver','Business Pro','Prepaid'),
                CAST(id % 5 AS INT) + 1) AS plan,
            CAST(1 + (id * 7) % 84 AS INT) AS tenure_months,
            CAST(40 + (id * 13) % 100 AS DECIMAL(8,2)) AS arpu,
            CAST((id * 31) % 100 / 100.0 AS DECIMAL(4,3)) AS churn_score,
            current_timestamp() - make_interval(0, 0, 0, CAST((id * 3) % 90 AS INT), 0, 0, 0) AS last_activity_at,
            CAST(18 + (id * 17) % 60 AS INT) AS age,
            element_at(array('Northeast','Southeast','Midwest','Southwest','West','Texas','California'),
                CAST(id % 7 AS INT) + 1) AS region,
            element_at(array('Consumer','SMB','Enterprise','Government'),
                CAST(id % 4 AS INT) + 1) AS segment
        FROM range({N_SUBSCRIBERS})
        """,
    ),
    (
        "usage",
        f"""
        CREATE OR REPLACE TABLE {SETTINGS.table("usage")} AS
        SELECT
            'S' || LPAD(CAST(id AS STRING), 9, '0') AS subscriber_id,
            date_add(current_date(), -30 * CAST(month_offset AS INT)) AS month,
            CAST(50 + (id * 7 + month_offset * 17) % 600 AS INT) AS calls_minutes,
            CAST(((id * 11 + month_offset * 5) % 50) AS DECIMAL(8,2)) AS data_gb,
            CAST(20 + (id * 3 + month_offset * 11) % 200 AS INT) AS sms_count
        FROM range({N_SUBSCRIBERS}) CROSS JOIN (SELECT explode(sequence(0, {N_USAGE_MONTHS - 1})) AS month_offset)
        """,
    ),
    (
        "devices",
        f"""
        CREATE OR REPLACE TABLE {SETTINGS.table("devices")} AS
        SELECT
            'D' || LPAD(CAST(id AS STRING), 9, '0') AS device_id,
            'S' || LPAD(CAST(id AS STRING), 9, '0') AS subscriber_id,
            element_at(array('iPhone 15','iPhone 14','iPhone 13','Galaxy S24','Galaxy S23','Pixel 8','Pixel 7','OnePlus 12'),
                CAST(id % 8 AS INT) + 1) AS model,
            element_at(array('Apple','Apple','Apple','Samsung','Samsung','Google','Google','OnePlus'),
                CAST(id % 8 AS INT) + 1) AS manufacturer,
            CAST(1 + (id * 5) % 48 AS INT) AS device_age_months,
            CASE WHEN (id * 7) % 100 < 30 THEN true ELSE false END AS eligible_for_upgrade
        FROM range({N_SUBSCRIBERS})
        """,
    ),
    (
        "support_tickets",
        f"""
        CREATE OR REPLACE TABLE {SETTINGS.table("support_tickets")} AS
        SELECT
            'T' || LPAD(CAST(id AS STRING), 9, '0') AS ticket_id,
            'S' || LPAD(CAST(id % {N_SUBSCRIBERS} AS STRING), 9, '0') AS subscriber_id,
            current_timestamp() - make_interval(0, 0, 0, CAST(id % 365 AS INT), 0, 0, 0) AS opened_at,
            current_timestamp() - make_interval(0, 0, 0, CAST(id % 365 - (id % 7) AS INT), 0, 0, 0) AS resolved_at,
            element_at(array('positive','neutral','negative'), CAST(id % 3 AS INT) + 1) AS sentiment,
            element_at(array('Billing','Network','Device','Plan Change','Account Access'),
                CAST(id % 5 AS INT) + 1) AS category
        FROM range({int(N_SUBSCRIBERS * 0.15)})
        """,
    ),
]


def main() -> None:
    print(f"Targeting {SETTINGS.schema_fqn}")
    uc.execute(f"CREATE SCHEMA IF NOT EXISTS {SETTINGS.schema_fqn}")
    uc.ensure_metadata_tables()

    for name, sql_text in STATEMENTS:
        print(f"  building {SETTINGS.table(name)} ...", flush=True)
        uc.execute(sql_text)

    sample = uc.query_df(f"SELECT COUNT(*) AS n FROM {SETTINGS.table('subscribers')}")
    print(f"subscribers: {int(sample.iloc[0]['n']):,}")

    print("Synthetic data generation complete.")


if __name__ == "__main__":
    main()
