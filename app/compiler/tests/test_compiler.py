import pytest

from app.compiler import Dag, compile_dag, compile_preview
from app.compiler.compiler import CompileError


def make_dag(**kw) -> Dag:
    return Dag.model_validate(kw)


SUBSCRIBERS = "att_log_anomaly_catalog.prospector_pro.ProspectorPro_subscribers"
ACCOUNTS = "att_log_anomaly_catalog.prospector_pro.ProspectorPro_accounts"
TARGET = "att_log_anomaly_catalog.prospector_pro.ProspectorPro_campaign_001_results"


def test_simple_source_filter_sink():
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {"id": "f1", "type": "filter", "config": {"predicate": "arpu > 50"}},
            {"id": "out", "type": "sink", "config": {}},
        ],
        edges=[
            {"source": "src", "target": "f1"},
            {"source": "f1", "target": "out"},
        ],
    )
    sql = compile_dag(dag, TARGET)
    assert "CREATE OR REPLACE TABLE" in sql
    assert SUBSCRIBERS in sql
    assert "WHERE arpu > 50" in sql
    assert "n_f1" in sql


def test_derive_columns():
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {
                "id": "d",
                "type": "derive",
                "config": {
                    "columns": [
                        {"name": "ltv", "expression": "arpu * tenure_months"},
                        {"name": "decade", "expression": "FLOOR(age / 10) * 10"},
                    ]
                },
            },
            {"id": "out", "type": "sink", "config": {}},
        ],
        edges=[{"source": "src", "target": "d"}, {"source": "d", "target": "out"}],
    )
    sql = compile_dag(dag, TARGET)
    assert "(arpu * tenure_months) AS ltv" in sql
    assert "(FLOOR(age / 10) * 10) AS decade" in sql


def test_join_two_sources():
    dag = make_dag(
        nodes=[
            {"id": "subs", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {"id": "accts", "type": "source_uc", "config": {"table_fqn": ACCOUNTS}},
            {
                "id": "j",
                "type": "join",
                "config": {"join_type": "inner", "on": "left.account_id = right.account_id"},
            },
            {"id": "out", "type": "sink", "config": {}},
        ],
        edges=[
            {"source": "subs", "target": "j", "side": "left"},
            {"source": "accts", "target": "j", "side": "right"},
            {"source": "j", "target": "out"},
        ],
    )
    sql = compile_dag(dag, TARGET)
    assert "INNER JOIN" in sql
    assert "lhs.account_id = rhs.account_id" in sql
    assert "AS lhs" in sql and "AS rhs" in sql


def test_source_file_csv():
    path = "/Volumes/att_log_anomaly_catalog/prospector_pro/ProspectorPro_uploads/leads.csv"
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_file", "config": {"volume_path": path, "file_format": "csv"}},
            {"id": "out", "type": "sink", "config": {}},
        ],
        edges=[{"source": "src", "target": "out"}],
    )
    sql = compile_dag(dag, TARGET)
    assert "read_files(" in sql
    assert "format => 'csv'" in sql
    assert "header => 'true'" in sql


def test_preview_no_sink_required():
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {"id": "f1", "type": "filter", "config": {"predicate": "region = 'TX'"}},
        ],
        edges=[{"source": "src", "target": "f1"}],
    )
    sql = compile_preview(dag, limit=50)
    assert "LIMIT 50" in sql
    assert "WHERE region = 'TX'" in sql
    assert "CREATE OR REPLACE" not in sql


def test_rejects_cycle():
    dag = make_dag(
        nodes=[
            {"id": "a", "type": "filter", "config": {"predicate": "1=1"}},
            {"id": "b", "type": "filter", "config": {"predicate": "1=1"}},
        ],
        edges=[{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    )
    with pytest.raises(CompileError, match="cycle"):
        compile_preview(dag)


def test_rejects_sql_injection_token():
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {"id": "f", "type": "filter", "config": {"predicate": "1=1; DROP TABLE foo"}},
            {"id": "out", "type": "sink", "config": {}},
        ],
        edges=[{"source": "src", "target": "f"}, {"source": "f", "target": "out"}],
    )
    with pytest.raises(CompileError, match="forbidden"):
        compile_dag(dag, TARGET)


def test_rejects_two_sinks():
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {"id": "out1", "type": "sink", "config": {}},
            {"id": "out2", "type": "sink", "config": {}},
        ],
        edges=[{"source": "src", "target": "out1"}, {"source": "src", "target": "out2"}],
    )
    with pytest.raises(CompileError, match="exactly one sink"):
        compile_dag(dag, TARGET)


def test_rejects_invalid_results_table():
    dag = make_dag(
        nodes=[
            {"id": "src", "type": "source_uc", "config": {"table_fqn": SUBSCRIBERS}},
            {"id": "out", "type": "sink", "config": {}},
        ],
        edges=[{"source": "src", "target": "out"}],
    )
    with pytest.raises(CompileError, match="invalid results_table"):
        compile_dag(dag, "not.fully.qualified.too.many")
