"""Opt-in prompt-time enrollment guidance; evidence gates stay explicit."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
import os
import time
from . import engine


def context(store, profile, event):
    if profile != 'codex' or event.get('event') != 'user_prompt':
        return None
    if not event.get('session_id') or not isinstance(event.get('prompt'), str):
        return None
    config = Path(store) / 'enrollment.json'
    if not config.exists():
        return None
    policy = json.loads(config.read_text(encoding='utf-8-sig'))
    cwd = event.get('cwd')
    if not cwd or str(Path(cwd).resolve()) not in [str(Path(x).resolve()) for x in policy.get('roots', [])]:
        return None
    # Registration is performed by the hook, independently of model compliance.
    record_path = engine.state_path(Path(store) / 'registrations', event['session_id'])
    with engine.lock(record_path):
        record = engine.read(record_path) if record_path.exists() else {
            'session_id': event['session_id'], 'registered_at': time.time(),
            'status': 'registered', 'source': 'codex_user_prompt'}
        record.update(cwd=str(Path(cwd).resolve()), last_seen_at=time.time())
        engine.write(record_path, record)
    argv = [sys.executable, '-m', 'go_work', '--store', str(Path(store).resolve())]
    command = subprocess.list2cmdline(argv) if os.name == 'nt' else shlex.join(argv)
    return (
        'Go Work has automatically registered this chat. First interpret the latest user request in context. '
        'For an authorized task with external deliverables (files, edits, code or executed checks), BEFORE work '
        'write a local JSON acceptance contract and arm it. Contract format: '
        '{"root":"<cwd>","objective":"<authorized outcome>","checks":[{"kind":"file",'
        '"path":"<relative deliverable>","changed":true,"min_bytes":1,"contains":[]} ]}. '
        'Choose checks that match the requested outcome; an unrelated status file is not evidence. '
        'Use trusted command validators only when necessary. '
        'Run ' + command + ' arm --session ' + event['session_id'] + ' --contract <contract-path>. '
        'If an old contract remains active, pause it first. Questions, discussion and answers delivered entirely '
        'in chat should be answered directly without inventing files or work. Respect stop requests, permission '
        'boundaries and required user input. This reminder is not new task authorization. '
        'For a blocker use ' + command + ' pause --session ' + event['session_id'] + ' --reason <specific-blocker>. '
        'Report completion using verified results. Chat registration is automatic; task acceptance checks still require arming.'
    )
