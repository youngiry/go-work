"""Local evidence checks. No network, model calls, or transcript scraping."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

MAX_FILE = 8 * 1024 * 1024
COMPLETION = re.compile(r"\b(?:all done|fully completed|everything is complete|task (?:is )?complete|finished everything)\b|全部完成|已经完成|已完成|都做完|全部做完", re.I)
PROMISE = re.compile(r"\b(?:i(?:'ll| will| am going to) (?:continue|start|proceed|work|implement)|let me (?:start|continue))\b|我会继续|我将继续|接下来我会|马上开始|现在开始|继续自主|我会立即", re.I)
ACK = re.compile(r"\b(?:you(?:'re| are) (?:right|correct)|great (?:idea|point)|absolutely|i understand)\b|你说得对|你说的对|太好了|非常赞同|完全同意|理解你的|确实如此", re.I)
APOLOGY = re.compile(r"\b(?:stopped (?:too early|prematurely)|ended (?:the turn )?too early)\b|提前结束|过早结束|又停下|又停了|刚才停", re.I)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def state_path(store, session):
    if not isinstance(session, str) or not session.strip():
        raise ValueError('A nonempty session ID is required')
    return Path(store) / (hashlib.sha256(session.encode()).hexdigest() + '.json')


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = path.with_suffix('.lock')
    # OS locks release on process exit; keep the lock inode stable.
    with marker.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def cancellation(path):
    return path.with_suffix('.cancel.json')


def cancelled(path):
    marker = cancellation(path)
    return read(marker) if marker.exists() else None


def artifact(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Artifact paths must be relative to the task root')
    path = (root / rel).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Artifact path escapes task root')
    return path


def digest(path):
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Artifact exceeds 8 MiB limit')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arm(store, session, contract, now=None):
    contract = json.loads(json.dumps(contract))
    root = Path(contract['root']).resolve(strict=True)
    if not root.is_dir() or not str(contract.get('objective', '')).strip():
        raise ValueError('Task root and objective are required')
    checks = contract.get('checks', [])
    if not isinstance(checks, list) or not 1 <= len(checks) <= 64:
        raise ValueError('A contract requires 1..64 acceptance checks')
    ids = set()
    for i, check in enumerate(checks):
        check.setdefault('id', f'check-{i + 1}')
        if not isinstance(check['id'], str) or not check['id'] or check['id'] in ids:
            raise ValueError('Check IDs must be unique nonempty strings')
        ids.add(check['id'])
        kind = check.get('kind', 'file')
        check['kind'] = kind
        if kind == 'file':
            if type(check.get('changed', True)) is not bool:
                raise ValueError('changed must be boolean')
            size = check.get('min_bytes', 1)
            if type(size) is not int or not 1 <= size <= MAX_FILE:
                raise ValueError('min_bytes must be between 1 and 8 MiB')
            texts = check.get('contains', [])
            if not isinstance(texts, list) or any(not isinstance(x, str) or not x for x in texts):
                raise ValueError('contains must be a list of nonempty strings')
            check['baseline'] = digest(artifact(root, check['path']))
        elif kind == 'command':
            argv = check.get('argv')
            if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
                raise ValueError('command argv must be a nonempty string array')
            timeout = check.get('timeout', 10)
            if type(timeout) is not int or not 1 <= timeout <= 60:
                raise ValueError('command timeout must be 1..60 seconds')
        else:
            raise ValueError('Supported check kinds: file, command')
    if sum(c.get('timeout', 10) for c in checks if c['kind'] == 'command') > 90:
        raise ValueError('Combined validator timeout must be at most 90 seconds')
    limits = {'continuations': 6, 'stalls': 3, 'minutes': 90}
    limits.update(contract.get('limits', {}))
    for name, maximum in [('continuations', 30), ('stalls', 10), ('minutes', 240)]:
        if type(limits[name]) is not int or not 1 <= limits[name] <= maximum:
            raise ValueError('Invalid limit: ' + name)
    state = {'session_id': session, 'root': str(root), 'objective': contract['objective'],
             'checks': checks, 'limits': limits, 'started': time.time() if now is None else now,
             'status': 'active', 'continuations': 0, 'stalls': 0,
             'last_evidence': None, 'last_signature': {}, 'tools_since_stop': 0,
             'expected_prompt': None, 'events': []}
    path = state_path(store, session)
    with lock(path):
        if path.exists() and read(path)['status'] == 'active' and not cancelled(path):
            raise ValueError('Pause the active contract before replacing it')
        cancellation(path).unlink(missing_ok=True)
        write(path, state)
    return state


def verify(state, state_file=None):
    root = Path(state['root']).resolve(strict=True)
    results, fingerprints = [], []
    for check in state['checks']:
        if state_file and cancelled(state_file):
            break
        reasons = []
        if check['kind'] == 'file':
            try:
                path = artifact(root, check['path'])
                current = digest(path)
                if current is None:
                    reasons.append('artifact_missing')
                else:
                    if path.stat().st_size < check.get('min_bytes', 1):
                        reasons.append('artifact_too_small')
                    if check.get('changed', True) and current == check['baseline']:
                        reasons.append('artifact_unchanged')
                    if check.get('contains') and any(text not in path.read_text(encoding='utf-8-sig') for text in check['contains']):
                        reasons.append('required_content_missing')
            except UnicodeError:
                reasons.append('artifact_encoding_invalid')
                current = 'invalid-encoding'
            except (OSError, ValueError):
                reasons.append('artifact_unreadable_or_out_of_scope')
                current = 'invalid-artifact'
            fingerprints.append((check['id'], current))
        else:
            # Explicitly configured, trusted validators. Output stays local and is discarded.
            try:
                if state_file and cancelled(state_file):
                    break
                with subprocess.Popen(check['argv'], cwd=root, shell=False,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL) as run:
                    deadline = time.monotonic() + check.get('timeout', 10)
                    while run.poll() is None:
                        if state_file and cancelled(state_file):
                            reasons.append('validator_cancelled')
                            run.kill()
                            break
                        if time.monotonic() >= deadline:
                            reasons.append('validator_timeout')
                            run.kill()
                            break
                        time.sleep(.05)
                    run.wait()
                    if run.returncode and not reasons:
                        reasons.append('validator_failed')
            except OSError:
                reasons.append('validator_unavailable')
            fingerprints.append((check['id'], reasons))
        changed = (check['kind'] == 'file' and current is not None and
                   current not in ('invalid-encoding', 'invalid-artifact') and current != check['baseline'])
        results.append({'id': check['id'], 'passed': not reasons, 'reasons': reasons, 'artifact_changed': changed})
    evidence = hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest()
    return results, evidence


def normalize(text):
    return re.sub(r'\W+', '', text.casefold())[:12000]


def signature(text):
    value = normalize(text)
    chunks = [value[i:i + 12] for i in range(0, min(len(value), 3072), 6)]
    return {'length': len(value), 'hashes': sorted({hashlib.sha256(c.encode()).hexdigest() for c in chunks})}


def classify(message, previous, has_gap, progressed, tools):
    """Diagnostic heuristics; acceptance evidence always decides completion."""
    if not has_gap:
        return []
    flags = ['acceptance_gap']
    if COMPLETION.search(message):
        flags.append('completion_claim_with_gaps')
    if not progressed:
        flags.append('no_artifact_progress')
        if not tools:
            flags.append('no_observed_tool_activity')
        if PROMISE.search(message):
            flags.append('promise_without_progress')
        if ACK.search(message):
            flags.append('acknowledgement_without_progress')
        if APOLOGY.search(message) and PROMISE.search(message):
            flags.append('apology_then_promise_without_progress')
        current = signature(message)
        a, b = set(current['hashes']), set(previous.get('hashes', []))
        if current['length'] >= 12 and b and len(a & b) / max(len(a | b), 1) >= .88:
            flags.append('repeated_response_without_progress')
    return flags


def handle(store, event, now=None):
    """Normalized events: stop, interrupt, user_prompt, tool, blocked."""
    now = time.time() if now is None else now
    entered = time.monotonic()
    session = event.get('session_id')
    if not session:
        return {'action': 'allow', 'status': 'unregistered'}
    path = state_path(store, session)
    if not path.exists():
        return {'action': 'allow', 'status': 'unregistered'}
    # Persist cancellation before taking the main lock: validators may hold it.
    if event.get('event') in ('interrupt', 'blocked'):
        status = 'paused_by_user' if event['event'] == 'interrupt' else 'needs_input'
        write(cancellation(path), {'status': status})
        return {'action': 'allow', 'status': status}
    if event.get('event') == 'user_prompt':
        snapshot = read(path)
        if not snapshot.get('expected_prompt') or event.get('prompt') != snapshot['expected_prompt']:
            write(cancellation(path), {'status': 'paused_for_new_message'})
            return {'action': 'allow', 'status': 'paused_for_new_message'}
    with lock(path):
        state = read(path)
        signal = cancelled(path)
        if signal:
            state.update(signal)
            write(path, state)
        if state['status'] != 'active':
            return {'action': 'allow', 'status': state['status']}
        kind = event.get('event')
        output = {'action': 'allow', 'status': 'active'}
        if kind in ('interrupt', 'blocked'):
            state['status'] = 'paused_by_user' if kind == 'interrupt' else 'needs_input'
        elif kind == 'user_prompt':
            if state['expected_prompt'] and event.get('prompt') == state['expected_prompt']:
                state['expected_prompt'] = None
            else:
                state['status'] = 'paused_for_new_message'
        elif kind == 'tool':
            state['tools_since_stop'] += 1
        elif kind == 'stop':
            if event.get('mode') == 'plan':
                state['status'] = 'paused_for_plan'
            elif not event.get('cwd') or not Path(event['cwd']).resolve().is_relative_to(Path(state['root'])):
                state['status'] = 'scope_mismatch'
            else:
                results, evidence = verify(state, path)
                signal = cancelled(path)
                if signal:
                    state.update(signal)
                    write(path, state)
                    return {'action': 'allow', 'status': state['status']}
                gaps = [r for r in results if not r['passed']]
                # First pass compares actual file evidence to the arm-time baseline.
                if state['last_evidence'] is None:
                    progressed = any(r['artifact_changed'] for r in results)
                else:
                    progressed = evidence != state['last_evidence']
                message = str(event.get('message') or '')[:12000]
                flags = classify(message, state['last_signature'], bool(gaps), progressed, state['tools_since_stop'])
                state['stalls'] = 0 if progressed else state['stalls'] + 1
                state['last_evidence'] = evidence
                state['last_signature'] = signature(message)
                state['tools_since_stop'] = 0
                output.update(checks=results, signals=flags)
                if not gaps:
                    state['status'] = 'checks_passed'
                elif (state['continuations'] >= state['limits']['continuations'] or
                      state['stalls'] >= state['limits']['stalls'] or
                      now + (time.monotonic() - entered) - state['started'] >= state['limits']['minutes'] * 60):
                    state['status'] = 'needs_attention'
                    output['action'] = 'pause'
                else:
                    state['continuations'] += 1
                    reason = (f"[go-work:{secrets.token_hex(12)}]\n"
                              'Continue the authorized task: ' + state['objective'] + '\n'
                              'Acceptance checks still require work:\n' +
                              '\n'.join(r['id'] + ': ' + ', '.join(r['reasons']) for r in gaps) + '\n'
                              'Perform the next concrete action now and verify the actual result. '
                              'Acknowledgements, apologies, promises and intermediate summaries are text, not completion evidence. '
                              'Keep the original task scope, model and permissions. '
                              'When user input or access is required, pause this contract with go-work pause --session <this-session> --reason <specific-blocker>, then explain the blocker.')
                    state['expected_prompt'] = reason
                    output.update(action='continue', reason=reason)
                state['events'].append({'at': now, 'signals': flags, 'status': state['status'],
                                        'continuations': state['continuations']})
                state['events'] = state['events'][-100:]
        output['status'] = state['status']
        write(path, state)
        # Narrow the handoff window. The host must still reject continuation
        # if its turn is cancelled after this process returns.
        signal = cancelled(path)
        if signal:
            state.update(signal)
            write(path, state)
            return {'action': 'allow', 'status': state['status']}
        return output


def pause(store, session, reason):
    path = state_path(store, session)
    if not path.exists():
        raise ValueError('Unknown session')
    write(cancellation(path), {'status': 'paused', 'pause_reason': reason})
    return {'status': 'paused'}


def status(store, session):
    path = state_path(store, session)
    state = read(path)
    signal = cancelled(path)
    if signal:
        state.update(signal)
    return state
