"""
Persists completed investigation runs to investigation_reports -- a
real history log, not a cache the system reads to skip fresh work
(see the migration's docstring for why). NOT called automatically
inside run_investigation() itself -- a deliberate, separate, explicit
call, so callers (e.g. ad-hoc dev/test runs) can choose whether a
given run actually gets saved to history.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def save_investigation_report(db: Session, customer_id: int, rule_id: int, result: dict) -> int:
    """Takes the dict returned by run_investigation() directly.
    Returns the new row's id."""
    chain_analysis = result.get("chain_analysis")
    final_report_structured = result.get("final_report_structured")

    row = db.execute(
        text(
            """
            INSERT INTO investigation_reports
                (customer_id, rule_id, chain_analysis, final_report, rendered_report, trace, tool_calls_made)
            VALUES
                (:customer_id, :rule_id, :chain_analysis, :final_report, :rendered_report, :trace, :tool_calls_made)
            RETURNING id
            """
        ),
        {
            "customer_id": customer_id,
            "rule_id": rule_id,
            "chain_analysis": chain_analysis.model_dump_json() if chain_analysis else None,
            "final_report": final_report_structured.model_dump_json() if final_report_structured else None,
            "rendered_report": result.get("final_report"),
            "trace": result.get("trace"),
            "tool_calls_made": result.get("tool_calls_made"),
        },
    )
    return row.scalar_one()