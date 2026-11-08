"""Offline demonstration; no model, network, or user workspace changes."""
from pathlib import Path
import tempfile
from go_work.engine import arm, handle

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    store = root / 'state'
    contract = {'root': folder, 'objective': 'Write a sourced report',
                'checks': [{'id': 'report', 'kind': 'file', 'path': 'report.md', 'contains': ['Sources']}],
                'limits': {'stalls': 6}}
    arm(store, 'demo', contract)
    event = {'event': 'stop', 'session_id': 'demo', 'cwd': folder}
    for text in ['Everything is complete.', 'Great idea, you are right!',
                 'I stopped too early. I will continue now.']:
        result = handle(store, dict(event, message=text))
        print(text)
        print(' ->', result['action'], '|', ', '.join(result['signals']))
    (root / 'report.md').write_text('Findings: the task now has an artifact.\nSources: synthetic demo.\n')
    result = handle(store, dict(event, message='Everything is complete.'))
    print('After creating the required artifact ->', result['status'])
