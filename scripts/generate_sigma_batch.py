"""
Runs Sigma-representation generation for a customer's canonical rules,
using the single SigmaGenerator class -- it internally decides
simple vs. correlation routing, so this script never needs to check
that itself. Writes a full trace to trace_recommendations.md.
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CUSTOMER_NAME = "cotecna"

# MUST be set BEFORE importing/using anything that creates an LLM
# client -- LangChain reads this environment variable once, at call
# time, to decide which LangSmith project to log traces into. Setting
# it per-customer here means each customer's batch run automatically
# lands in its own separate project, so cost/token totals in
# LangSmith are already split out per customer, no manual switching.
os.environ["LANGCHAIN_PROJECT"] = f"sigma-generation-{CUSTOMER_NAME}"

from sqlalchemy import text
from app.db.session import engine
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.rule_query import list_canonical_rules
from app.recommendations.sigma_generator import SigmaGenerator

RULE_IDS = [527, 815, 930, 1007]  # manually specified for testing -- set explicit ids to test

TRACE_PATH = Path(__file__).resolve().parent.parent / "app" / "recommendations" / "trace_recommendations.md"

with engine.connect() as read_db:
    customer_id = read_db.execute(text("SELECT id FROM customers WHERE name = :n"), {"n": CUSTOMER_NAME}).scalar_one()
    canonical_rules = list_canonical_rules(read_db, customer_id)
    print(f"{len(canonical_rules)} canonical rules found for {CUSTOMER_NAME} (deduplicated)")

provider = LLMProvider()
generator = SigmaGenerator(provider)
trace_sections = ["# Sigma Generation Trace", ""]

for rule_id in RULE_IDS:
    with engine.begin() as db:
        rule_row = db.execute(text("SELECT name FROM rule_summary WHERE id = :id"), {"id": rule_id}).mappings().first()
        if rule_row is None:
            print(f"\n=== Rule {rule_id}: NOT FOUND, skipping ===")
            continue

        print(f"\n=== Rule {rule_id}: {rule_row['name']} ===")
        result = generator.generate_and_save(db, customer_id, rule_id)

    print(f"Role: {result['role']}")
    print(result["generation"].model_dump_json(indent=2))
    print(f"Saved as rule_yaml_representations.id = {result['ids']}")

    trace_sections.append(
        f"## Rule {rule_id} ({result['role']})\n\n```json\n{result['generation'].model_dump_json(indent=2)}\n```\n\n---\n"
    )

TRACE_PATH.write_text("\n".join(trace_sections), encoding="utf-8")
print(f"\nTrace saved to {TRACE_PATH}")