"""One CLI for native hooks and harness-controlled JSON events."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from . import adapters, engine, enrollment


def hook_config(profile):
    if profile == 'generic':
        raise ValueError('Generic integrations call go-work event directly')
    argv = [sys.executable, '-m', 'go_work', 'hook', '--adapter', profile]
    command = subprocess.list2cmdline(argv) if os.name == 'nt' else shlex.join(argv)
    names = ['Stop', 'UserPromptSubmit', 'PostToolUse']
    if profile == 'codex':
        names += ['Interrupt']
    if profile == 'deepseek-codex':
        names = ['Stop', 'UserPromptSubmit']
    return {'hooks': {name: [{'hooks': [{'type': 'command', 'command': command,
                                        'timeout': 3 if name == 'Interrupt' else 120}]}] for name in names}}


def main():
    parser = argparse.ArgumentParser(description='Go Work — verify evidence before an AI agent stops')
    parser.add_argument('--store', type=Path, default=Path(os.environ.get('GO_WORK_STORE', str(Path.home() / '.go-work'))))
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('event', 'hook'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--adapter', choices=adapters.PROFILES, default='generic' if name == 'event' else 'codex')
    cmd = sub.add_parser('arm')
    cmd.add_argument('--session', required=True)
    cmd.add_argument('--contract', type=Path, required=True)
    for name in ('pause', 'status'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--session', required=True)
        if name == 'pause':
            cmd.add_argument('--reason', required=True)
    cmd = sub.add_parser('config')
    cmd.add_argument('--adapter', choices=adapters.PROFILES, required=True)
    args = parser.parse_args()
    try:
        if args.command in ('hook', 'event'):
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('Event exceeds 1 MiB')
            payload = json.loads(raw.decode('utf-8-sig'))
            if not isinstance(payload, dict):
                raise ValueError('Event must be a JSON object')
            event = adapters.normalize(args.adapter, payload)
            result = engine.handle(args.store, event)
            result = adapters.output(args.adapter, result)
            context = enrollment.context(args.store, args.adapter, event)
            if context:
                result['hookSpecificOutput'] = {'hookEventName': 'UserPromptSubmit', 'additionalContext': context}
        elif args.command == 'arm':
            state = engine.arm(args.store, args.session, engine.read(args.contract))
            result = {'status': state['status'], 'session_id': args.session, 'checks': len(state['checks'])}
        elif args.command == 'pause':
            result = engine.pause(args.store, args.session, args.reason)
        elif args.command == 'status':
            result = engine.status(args.store, args.session)
        else:
            result = hook_config(args.adapter)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        if args.command in ('hook', 'event'):
            result = {'action': 'allow', 'status': 'error', 'error_type': type(exc).__name__}
            print(json.dumps(adapters.output(args.adapter, result)))
            return 0  # Hook errors release control; they never restart a failed runtime.
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
