import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine
from app.rule_analyzer.investigation_graph import run_investigation
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.qradar_client_factory import build_qradar_client_for_customer
from app.rule_analyzer.report_storage import save_investigation_report


CUSTOMER_NAME = "cotecna"
# RULE_ID = 496  # replace with a real internal rule_id from your fresh data
RULE_ID = 359 #%Office 365%Malware Mail Detected%


with engine.connect() as db:
    customer_id = db.execute(
        text("SELECT id FROM customers WHERE name = :name"), {"name": CUSTOMER_NAME}
    ).scalar_one()

    qradar_client = build_qradar_client_for_customer(db, customer_id)
    provider = LLMProvider()

    result = run_investigation(db, provider, qradar_client, customer_id, RULE_ID)

    trace_path = Path(__file__).resolve().parent.parent / "app" / "rule_analyzer" / "trace.md"
    with open(trace_path, "w", encoding="utf-8") as f:
        f.write("# Investigation trace\n\n")
        f.write("```\n")
        f.write(result["trace"])
        f.write("\n```\n")

    print(f"Trace saved to {trace_path}")

    print("=" * 70)
    print("CHAIN ANALYSIS:")
    print("=" * 70)
    print(result["chain_analysis"])

    print()
    print(f"TOOL CALLS MADE: {result['tool_calls_made']}")

    print()
    print("=" * 70)
    print("FINAL REPORT:")
    print("=" * 70)
    print(result["final_report"])
    report_id = save_investigation_report(db, customer_id, RULE_ID, result)
    db.commit()
    print(f"Saved as investigation_reports.id = {report_id}")