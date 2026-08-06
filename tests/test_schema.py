from sqlalchemy import inspect

from app.db.session import engine


def test_all_tables_exist():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "customers",
        "customer_credentials",
        "rules",
        "rules_reference",
        "rule_offense_contributions",
        "mitre_mappings",
        "building_blocks_reference",
        "rule_building_blocks",
        "validation_results",
        "sync_runs",
    }
    assert expected.issubset(tables)