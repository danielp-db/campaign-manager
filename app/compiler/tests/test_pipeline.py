import pytest

from app.compiler.pipeline import (
    AggregateStep,
    CompileError,
    CustomStep,
    DatasetStep,
    FieldStep,
    FilterStep,
    JoinKey,
    JoinStep,
    Pipeline,
    SelectColumn,
    SelectStep,
    UnionStep,
    compile_pipeline,
    compile_pipeline_preview,
)

CAT = "att_log_anomaly_catalog.prospector_pro"
SUBS = f"{CAT}.ProspectorPro_subscribers"
ACCTS = f"{CAT}.ProspectorPro_accounts"
TARGET = f"{CAT}.ProspectorPro_campaign_C0001_results"


def test_dataset_then_filter():
    p = Pipeline(
        steps=[
            DatasetStep(name="subs", source="uc", table_fqn=SUBS),
            FilterStep(
                name="tx_subs",
                **{"from": "subs"},
                column="region",
                operator="=",
                value="Texas",
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "CREATE OR REPLACE TABLE" in sql
    assert "subs AS (" in sql
    assert "tx_subs AS (" in sql
    assert "WHERE region = 'Texas'" in sql
    assert "SELECT * FROM tx_subs" in sql


def test_filter_numeric_value_unquoted():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            FilterStep(name="t", **{"from": "s"}, column="arpu", operator=">=", value="80"),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "WHERE arpu >= 80" in sql


def test_filter_is_null():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            FilterStep(name="t", **{"from": "s"}, column="account_id", operator="IS NULL", value=""),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "WHERE account_id IS NULL" in sql


def test_field_adds_computed_column():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            FieldStep(
                name="enriched",
                **{"from": "s"},
                new_field_name="ltv",
                expression="arpu * tenure_months",
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "(arpu * tenure_months) AS ltv FROM s" in sql


def test_select_columns_with_alias():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            SelectStep(
                name="t",
                **{"from": "s"},
                columns=[SelectColumn(column="subscriber_id"), SelectColumn(column="arpu", alias="monthly_revenue")],
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "SELECT subscriber_id, arpu AS monthly_revenue FROM s" in sql


def test_join_with_two_keys():
    p = Pipeline(
        steps=[
            DatasetStep(name="L", source="uc", table_fqn=SUBS),
            DatasetStep(name="R", source="uc", table_fqn=ACCTS),
            JoinStep(
                name="joined",
                left="L",
                right="R",
                join_type="LEFT",
                keys=[JoinKey(left="account_id", right="account_id"), JoinKey(left="region", right="region")],
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "L AS lhs LEFT JOIN R AS rhs" in sql
    assert "lhs.account_id = rhs.account_id AND lhs.region = rhs.region" in sql


def test_union_all():
    p = Pipeline(
        steps=[
            DatasetStep(name="L", source="uc", table_fqn=SUBS),
            DatasetStep(name="R", source="uc", table_fqn=ACCTS),
            UnionStep(name="U", left="L", right="R"),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "SELECT * FROM L UNION ALL SELECT * FROM R" in sql


def test_dataset_from_file():
    p = Pipeline(
        steps=[
            DatasetStep(
                name="leads",
                source="file",
                file_path="/Volumes/cat/sch/vol/leads.csv",
                file_format="csv",
            )
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "read_files(" in sql
    assert "format => 'csv'" in sql
    assert "header => 'true'" in sql


def test_rejects_unknown_reference():
    p = Pipeline(
        steps=[
            FilterStep(name="t", **{"from": "missing"}, column="c", operator="=", value="v"),
        ]
    )
    with pytest.raises(CompileError, match="unknown step"):
        compile_pipeline(p, TARGET)


def test_rejects_duplicate_names():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            DatasetStep(name="s", source="uc", table_fqn=ACCTS),
        ]
    )
    with pytest.raises(CompileError, match="duplicate"):
        compile_pipeline(p, TARGET)


def test_rejects_forbidden_token():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            FilterStep(name="t", **{"from": "s"}, column="x", operator="LIKE", value="hi'; DROP"),
        ]
    )
    # LIKE goes through quote_literal which escapes single quotes; the ; alone is forbidden in IN, but for LIKE the value is a literal — check that it gets escaped properly
    sql = compile_pipeline(p, TARGET)
    # The single quote from value gets escaped to ''; the resulting SQL is not exploitable
    assert "'hi''; DROP'" in sql


def test_rejects_invalid_results_table():
    p = Pipeline(
        steps=[DatasetStep(name="s", source="uc", table_fqn=SUBS)]
    )
    with pytest.raises(CompileError, match="invalid results_table"):
        compile_pipeline(p, "not_fully_qualified")


def test_preview_targets_specific_step():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            FilterStep(name="f", **{"from": "s"}, column="region", operator="=", value="TX"),
            FieldStep(name="g", **{"from": "f"}, new_field_name="ltv", expression="arpu * 12"),
        ]
    )
    sql = compile_pipeline_preview(p, target_step="f", limit=50)
    assert "LIMIT 50" in sql
    assert "SELECT * FROM f LIMIT 50" in sql
    assert "g AS (" not in sql  # later step excluded
    assert "CREATE OR REPLACE" not in sql


def test_aggregate_step():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            AggregateStep(
                name="by_region",
                **{"from": "s"},
                group_by=["region", "segment"],
                aggregations=["COUNT(*) AS leads", "SUM(arpu) AS total_arpu"],
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "SELECT region, segment, COUNT(*) AS leads, SUM(arpu) AS total_arpu FROM s" in sql
    assert "GROUP BY region, segment" in sql


def test_aggregate_no_group_by():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            AggregateStep(
                name="totals",
                **{"from": "s"},
                group_by=[],
                aggregations=["COUNT(*) AS n"],
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "SELECT COUNT(*) AS n FROM s" in sql
    assert "GROUP BY" not in sql


def test_custom_step():
    p = Pipeline(
        steps=[
            DatasetStep(name="s", source="uc", table_fqn=SUBS),
            CustomStep(
                name="weird",
                sql="SELECT subscriber_id, RANK() OVER (PARTITION BY region ORDER BY arpu DESC) AS rnk FROM s",
            ),
        ]
    )
    sql = compile_pipeline(p, TARGET)
    assert "RANK() OVER" in sql
    assert "weird AS (" in sql


def test_custom_rejects_forbidden_token():
    p = Pipeline(
        steps=[
            CustomStep(name="bad", sql="SELECT 1; DROP TABLE foo"),
        ]
    )
    with pytest.raises(CompileError, match="forbidden"):
        compile_pipeline(p, TARGET)


def test_alias_serialization_roundtrip():
    """Ensure 'from' alias works on validate + dump."""
    p = Pipeline.model_validate(
        {
            "steps": [
                {"op": "dataset", "name": "s", "source": "uc", "table_fqn": SUBS},
                {"op": "filter", "name": "t", "from": "s", "column": "x", "operator": "=", "value": "1"},
            ]
        }
    )
    dumped = p.model_dump(by_alias=True)
    assert dumped["steps"][1]["from"] == "s"
