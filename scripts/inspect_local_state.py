"""Read-only persistence evidence for the dedicated synthetic compose stack."""
import asyncio
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


async def main():
    if os.environ.get('LOCAL_SYNTHETIC_STACK')!='1':raise RuntimeError('SYNTHETIC_STACK_REQUIRED')
    from app.database import AsyncSessionLocal,engine
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        result={'database':await db.scalar(text('select current_database()')),
                'receipts':await db.scalar(text('select count(*) from delivery_receipts')),
                'outbox':await db.scalar(text('select count(*) from outbox_events')),
                'pending':await db.scalar(text('select count(*) from outbox_events where processed=false')),
                'active_contracts':await db.scalar(text("select count(*) from contract_versions where state='active'"))}
    print(json.dumps(result));await engine.dispose()


if __name__=='__main__':asyncio.run(main())
