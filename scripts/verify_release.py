"""Release evidence gate. Passing unit tests alone cannot approve an alpha."""
import json
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
state=json.loads((root/'docs/implementation/TASKS.json').read_text())
missing=[r['id']+':'+r['status'] for r in state['acceptance_results'] if r['kind']!='human' and r['status']!='PASS']
missing.extend(t['id']+':'+t['status'] for t in state['tasks'] if t['id'] not in {'T14','T15'} and t['status']!='done')
for name in ['LICENSE','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md']:
    if not (root/name).is_file():missing.append(name+':missing')
print(json.dumps({'release_ready':not missing,'unmet_gates':missing,'human_validation':next(r['status'] for r in state['acceptance_results'] if r['id']=='AC-22')}))
sys.exit(bool(missing))
