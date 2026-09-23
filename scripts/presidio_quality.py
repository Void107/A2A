"""Span quality against synthetic labels using the actual service recognizer."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.presidio.service import recognizer
from app.adapters.presidio import PROFILE

cases = [
    ('regression', 'Mail alice@example.com.', ['alice@example.com']),
    ('regression', 'a@example.com, b@example.com', ['a@example.com', 'b@example.com']),
    ('regression', 'No email here.', []),
    ('regression', 'Alice Example 555-1234', []),
    ('exploration', 'Contact team+launch@sub.example.com now', ['team+launch@sub.example.com']),
    ('exploration', '(qa@example.com)', ['qa@example.com']),
    ('exploration', 'alice @ example . com', ['alice @ example . com']),
    ('exploration', '中文人名 张三 电话12345', []),
    ('exploration', 'not-an-email.example.com', []),
]
report = {'profile_revision': PROFILE, 'nlp_model': None, 'entity': 'EMAIL_ADDRESS', 'threshold': 0.5,
          'cases': [], 'scope': 'Synthetic only; obfuscation and other entities are outside supported baseline.'}
for group, text, labels in cases:
    expected = {(text.index(label), text.index(label) + len(label)) for label in labels}
    actual = {(r.start, r.end) for r in recognizer.analyze(text, ['EMAIL_ADDRESS'], nlp_artifacts=None) if r.score >= .5}
    row = {'group': group, 'text': text, 'expected': sorted(expected), 'actual': sorted(actual),
           'tp': len(expected & actual), 'fp': len(actual - expected), 'fn': len(expected - actual)}
    report['cases'].append(row)
    if group == 'regression': assert row['fp'] == row['fn'] == 0
for group in ('regression', 'exploration'):
    rows = [r for r in report['cases'] if r['group'] == group]
    tp, fp, fn = [sum(r[k] for r in rows) for k in ('tp', 'fp', 'fn')]
    report[group] = {'samples': len(rows), 'tp': tp, 'fp': fp, 'fn': fn,
                     'precision': tp/(tp+fp) if tp+fp else None, 'recall': tp/(tp+fn) if tp+fn else None}
(ROOT / 'docs/verification/t07-quality.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({k: report[k] for k in ('regression', 'exploration')}))
