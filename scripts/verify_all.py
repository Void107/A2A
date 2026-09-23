"""Sequential local CI command. A failed/missing test never yields success."""
import json
import os
import subprocess
import sys
import time
import hashlib
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LOG=ROOT/'docs/verification'/('ci-run-'+uuid.uuid4().hex[:10])


def main():
    LOG.mkdir(parents=True,exist_ok=True)
    sources=[p for folder in ['app','scripts','tests','alembic','policies'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.py','.rego','.json'} and '__pycache__' not in p.parts]
    (LOG/'source-manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')
    print('Evidence directory: '+str(LOG),flush=True)
    commands=[('unit',[os.environ.get('UNIT_PYTHON',sys.executable),'-m','pytest','-q'])]
    commands.extend((name,[sys.executable,'scripts/'+name+'.py']) for name in
        ['verify_real_baseline','verify_unmigrated','verify_security','verify_upstream','verify_tls','verify_receipts','verify_process_failures','verify_opa','verify_processing','verify_delivery'])
    commands.append(('presidio_quality',[os.environ.get('PRESIDIO_PYTHON',str(ROOT/'.venv-presidio/bin/python')),'scripts/presidio_quality.py']))
    results=[]
    for name,command in commands:
        started=time.time(); path=LOG/('ci-'+name+'.log')
        with path.open('w') as output:
            code=subprocess.run(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT).returncode
        results.append({'name':name,'command':command,'exit_code':code,'started_unix':started,'seconds':time.time()-started,'log':str(path.relative_to(ROOT))})
        (LOG/'ci-results.json').write_text(json.dumps(results,indent=2)+'\n')
        print(name, 'PASS' if code==0 else 'FAIL', flush=True)
    return int(any(r['exit_code'] for r in results))


if __name__=='__main__':sys.exit(main())
