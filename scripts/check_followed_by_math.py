import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    customer_id = conn.execute(text("SELECT id FROM customers WHERE name='cotecna'")).scalar_one()
    rows = conn.execute(text("""
        SELECT rc.test_class, rc.structured_data
        FROM rule_conditions rc JOIN rules r ON r.id = rc.rule_id
        WHERE r.customer_id = :c
          AND rc.test_class IN ('SequenceFunction_Test','DoubleSequenceFunction_Test',
                                 'CauseAndEffect_Test','TriggerMatchCount')
    """), {"c": customer_id}).mappings().all()

    all_pairs = []
    for r in rows:
        tc, data = r["test_class"], r["structured_data"]
        if tc == "SequenceFunction_Test":
            bb = data.get("sequence", {}).get("bb_ids", [])
            all_pairs += [(bb[i], bb[i+1]) for i in range(len(bb)-1)]
        elif tc == "DoubleSequenceFunction_Test":
            d = data.get("double_sequence", {})
            all_pairs += [(s, t) for s in d.get("stage1_bb_ids", []) for t in d.get("stage2_bb_ids", [])]
        elif tc == "CauseAndEffect_Test":
            d = data.get("cause_and_effect", {})
            all_pairs += [(s, t) for s in d.get("stage1_bb_ids", []) for t in d.get("stage2_bb_ids", [])]
        elif tc == "TriggerMatchCount":
            d = data.get("trigger_match_count", {})
            all_pairs += [(s, t) for s in d.get("trigger_bb_ids", []) for t in d.get("later_bb_ids", [])]

    print(f"Total pairs generated (with duplicates): {len(all_pairs)}")
    print(f"Distinct pairs (what MERGE would collapse to): {len(set(all_pairs))}")