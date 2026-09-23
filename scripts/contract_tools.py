"""Offline comparison/migration and local processing preview (never activates)."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts.loader import load_contract


def read(path):
    data = Path(path).read_bytes()
    if len(data) > 262144: raise ValueError('FILE_TOO_LARGE')
    return json.loads(data)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['compare','migrate','preview'])
    parser.add_argument('first'); parser.add_argument('second')
    parser.add_argument('--view', default='external-collaboration')
    parser.add_argument('--presidio-url', default='http://127.0.0.1:58182')
    args = parser.parse_args()
    a,b=read(args.first),read(args.second)
    if args.operation=='compare':
        from app.contracts.changes import compare
        result=compare(a,b)
    elif args.operation=='migrate':
        from app.contracts.migrate import migrate
        result=migrate(a,b)
    else:
        from app.services.view_processing import process_view
        from app.adapters.presidio import PresidioClient
        client=PresidioClient(args.presidio_url)
        try: result=(await process_view(load_contract(a),args.view,b,client,b.get('meeting_id'))).data
        finally: await client.close()
    print(json.dumps(result, indent=2))
    return 1 if result.get('status')=='blocked' else 0


if __name__=='__main__':
    try: sys.exit(asyncio.run(main()))
    except Exception:
        print(json.dumps({'code':'CONTRACT_TOOL_FAILED'})); sys.exit(1)
