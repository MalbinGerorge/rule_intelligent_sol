import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from app.db.session import engine

csv_path = sys.argv[1]

csv_rules = {}
with open(csv_path, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rule_id = int(row['Rule ID'])
        enabled = row['Rule enabled'].strip().lower() == 'true'
        triggered = bool(row['Rule last triggered'].strip())
        csv_rules[rule_id] = (enabled, triggered, row['Rule name'])

with engine.connect() as conn:
    db_rows = conn.execute(text("""
        SELECT qradar_rule_id, enabled, last_event_at IS NOT NULL AS triggered, name
        FROM rule_summary
        WHERE customer_id = (SELECT id FROM customers WHERE name='cotecna')
          AND object_type = 'RULE'
    """)).fetchall()

db_rules = {r[0]: (r[1], r[2], r[3]) for r in db_rows}

print(f"CSV rules: {len(csv_rules)}, DB rules: {len(db_rules)}")

only_in_csv = set(csv_rules) - set(db_rules)
only_in_db = set(db_rules) - set(csv_rules)
if only_in_csv:
    print(f"\nOnly in CSV: {[(rid, csv_rules[rid][2]) for rid in only_in_csv]}")
if only_in_db:
    print(f"\nOnly in DB: {[(rid, db_rules[rid][2]) for rid in only_in_db]}")

print("\nMismatches (enabled/triggered differ):")
for rid in set(csv_rules) & set(db_rules):
    csv_val = csv_rules[rid][:2]
    db_val = db_rules[rid][:2]
    if csv_val != db_val:
        print(f"  Rule ID {rid} ({csv_rules[rid][2]}): CSV={csv_val}  DB={db_val}")