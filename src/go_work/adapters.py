"""Adapters deliberately expose only documented lifecycle fields."""
EVENTS = {'Stop': 'stop', 'Interrupt': 'interrupt', 'UserPromptSubmit': 'user_prompt',
          'PostToolUse': 'tool', 'PermissionRequest': 'blocked'}
PROFILES = ('generic', 'codex', 'qwen', 'deepseek-codex')


def normalize(profile, payload):
    if profile == 'generic':
        return payload
    if profile not in PROFILES:
        raise ValueError('Unsupported adapter')
    if profile == 'qwen' and payload.get('hook_event_name') == 'UserPromptSubmit':
        # Qwen also fires this event for tool/hook sends. Only submitted_prompt
        # is an explicit user-input signal. Missing provenance stays unclassified.
        submitted = payload.get('submitted_prompt')
        return {'event': 'user_prompt' if isinstance(submitted, str) else 'unknown',
                'session_id': payload.get('session_id'), 'prompt': submitted}
    return {'event': EVENTS.get(payload.get('hook_event_name'), 'unknown'),
            'session_id': payload.get('session_id'), 'cwd': payload.get('cwd'),
            'message': payload.get('last_assistant_message') or '',
            'prompt': payload.get('prompt'), 'mode': payload.get('permission_mode')}


def output(profile, result):
    if profile == 'generic':
        return result
    if result['action'] == 'continue':
        return {'decision': 'block', 'reason': result['reason']}
    if result['status'] in ('needs_attention', 'scope_mismatch', 'error'):
        return {'systemMessage': 'Go Work: ' + result['status'] + '. Review the local task status.'}
    return {}
