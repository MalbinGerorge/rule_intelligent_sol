"""
Runs Sigma-representation generation for ALL of a customer's
canonical rules that don't already have a Sigma representation --
skips already-done rules (avoids wasted LLM cost on a re-run).
Prints live per-rule progress with timestamps and elapsed time, so a
hang on any single rule is immediately visible -- WHICH rule, and
HOW LONG -- rather than opaque. NOTE: this only helps DIAGNOSE a
hang (you'll see it stuck on rule X); it can't recover from a true
infinite loop (e.g. circular BB references) -- only Ctrl+C can.
"""
import sys
import os
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CUSTOMER_NAME = "cotecna"
os.environ["LANGCHAIN_PROJECT"] = f"{CUSTOMER_NAME}-sigma-generation"

from sqlalchemy import text
from app.db.session import engine
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.rule_query import list_canonical_rules
from app.recommendations.sigma_generator import SigmaGenerator

FAILURE_LOG_PATH = Path(__file__).resolve().parent.parent / "app" / "recommendations" / "sigma_batch_failures.md"

with engine.connect() as read_db:
    customer_id = read_db.execute(text("SELECT id FROM customers WHERE name = :n"), {"n": CUSTOMER_NAME}).scalar_one()
    all_rules = list_canonical_rules(read_db, customer_id)
    already_done = {
        r[0] for r in read_db.execute(
            text("SELECT DISTINCT rule_id FROM rule_yaml_representations WHERE customer_id = :c"), {"c": customer_id}
        ).fetchall()
    }
    rules_to_process = [r for r in all_rules if r["id"] not in already_done]

print(f"{len(all_rules)} canonical rules total, {len(already_done)} already done, {len(rules_to_process)} to process now")

provider = LLMProvider()
generator = SigmaGenerator(provider)
failures = []

for i, rule in enumerate(rules_to_process, start=1):
    start_ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{start_ts}] ({i}/{len(rules_to_process)}) Rule {rule['id']}: {rule['name'][:80]} ... ", end="", flush=True)
    t0 = time.time()
    try:
        with engine.begin() as db:
            result = generator.generate_and_save(db, customer_id, rule["id"])
        elapsed = time.time() - t0
        print(f"OK ({result['role']}, {elapsed:.1f}s)")
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"FAILED after {elapsed:.1f}s -- {exc}")
        failures.append({"rule_id": rule["id"], "rule_name": rule["name"], "error": str(exc)})

print(f"\nDone. {len(rules_to_process) - len(failures)} succeeded, {len(failures)} failed.")

if failures:
    lines = ["# Sigma Batch Failures", ""]
    for f in failures:
        lines.append(f"- Rule {f['rule_id']} ({f['rule_name']}): {f['error']}")
    FAILURE_LOG_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Failure details written to {FAILURE_LOG_PATH}")