import sys
sys.path.insert(0, '.')
from pathlib import Path
from datetime import datetime, timezone
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
from talonx_ingest.intelligence.delivery.notification_policy import reclassify_pending_rows
from talonx_ingest.intelligence.significance.store import SignificanceStore
from talonx_ingest.intelligence.insider.store import InsiderStore
from talonx_ingest.intelligence.store import EventStore

db_path = Path.home() / ".talonx" / "ingestion_ledger.db"
print("db:", db_path, "exists:", db_path.exists())

ob = DeliveryOutbox(db_path)
sig_store = SignificanceStore(db_path)
insider_store = InsiderStore(db_path)
events_store = EventStore(db_path)

now = datetime.now(timezone.utc)
before_pending = len(ob.pending(route="IMMEDIATE", now=now, limit=1000))
print("PENDING IMMEDIATE rows before:", before_pending)

# capture the two known DD rows' text before, for evidence
dd_ids = ["telegram:card:SEC:0001628280-25-054484:INSIDER_TRANSACTION:telegram-intel-v1",
          "telegram:card:SEC:0001062993-24-009906:INSIDER_TRANSACTION:telegram-intel-v1"]
for did in dd_ids:
    row = ob.get(did)
    if row:
        print(f"BEFORE {did}: {row.text.splitlines()[1] if len(row.text.splitlines())>1 else row.text}")

res = reclassify_pending_rows(ob, significance_store=sig_store, insider_store=insider_store,
                              events_store=events_store, route="IMMEDIATE", limit=1000, now=now)
print("scanned:", res.scanned)
print("downgraded:", res.downgraded, res.downgraded_ids)
print("content_refreshed:", res.content_refreshed, res.content_refreshed_ids)
print("errors:", res.errors)

for did in dd_ids:
    row = ob.get(did)
    if row:
        print(f"AFTER {did}: {row.text.splitlines()[1] if len(row.text.splitlines())>1 else row.text}")
        print(f"  state={row.state} route={row.route}")

after_pending = len(ob.pending(route="IMMEDIATE", now=now, limit=1000))
print("PENDING IMMEDIATE rows after:", after_pending)

ob.close(); sig_store.close(); insider_store.close(); events_store.close()
