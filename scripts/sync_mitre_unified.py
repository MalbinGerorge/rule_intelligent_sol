import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import engine
from app.services.mitre_unified_sync import sync_rule_mitre_unified

n = sync_rule_mitre_unified(engine)
print(f"Synced {n} rows into rule_mitre_unified")