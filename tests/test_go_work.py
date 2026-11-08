import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from go_work import adapters, engine
from go_work.cli import hook_config


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / 'store'
        self.contract = {'root': str(self.root), 'objective': 'Produce a sourced report',
                         'checks': [{'id': 'report', 'kind': 'file', 'path': '报告.md', 'contains': ['Sources']}],
                         'limits': {'continuations': 3, 'stalls': 3, 'minutes': 5}}
        self.event = {'event': 'stop', 'session_id': 'one', 'cwd': str(self.root)}

    def arm(self):
        return engine.arm(self.store, 'one', self.contract, now=1000)

    def stop(self, **kw):
        return engine.handle(self.store, dict(self.event, **kw), now=1001)

    def test_unregistered(self):
        self.assertEqual('unregistered', self.stop()['status'])

    def test_false_completion(self):
        self.arm()
        result = self.stop(message='全部完成，已经完成所有任务。')
        self.assertEqual('continue', result['action'])
        self.assertIn('completion_claim_with_gaps', result['signals'])

    def test_emotional_agreement_without_work(self):
        self.arm()
        result = self.stop(message='太好了，你说得对，我完全同意。')
        self.assertEqual('continue', result['action'])
        self.assertIn('acknowledgement_without_progress', result['signals'])

    def test_admit_promise_stop_regression(self):
        self.arm()
        result = self.stop(message='你说得对，我刚才提前结束了。我会继续自主工作。')
        self.assertIn('apology_then_promise_without_progress', result['signals'])
        self.assertEqual('continue', result['action'])

    def test_repeated_promise(self):
        self.arm()
        message = 'I will continue working on the requested implementation now.'
        self.stop(message=message)
        result = self.stop(message=message)
        self.assertIn('repeated_response_without_progress', result['signals'])

    def test_agreement_with_valid_delivery_is_allowed(self):
        self.arm()
        (self.root / '报告.md').write_text('Sources: verified report', encoding='utf-8')
        result = self.stop(message="Great idea! Everything is complete.")
        self.assertEqual('checks_passed', result['status'])
        self.assertEqual([], result['signals'])

    def test_old_file_is_not_current_delivery(self):
        (self.root / '报告.md').write_text('Sources: old', encoding='utf-8')
        self.arm()
        self.assertEqual('continue', self.stop()['action'])

    def test_partial_work_keeps_running(self):
        self.contract['checks'].append({'id': 'second', 'path': 'second.md'})
        self.arm()
        (self.root / '报告.md').write_text('Sources: done', encoding='utf-8')
        result = self.stop(message='Everything is complete.')
        self.assertEqual('continue', result['action'])
        self.assertEqual(1, sum(c['passed'] for c in result['checks']))

    def test_fake_tool_activity_does_not_complete(self):
        self.arm()
        self.stop(event='tool')
        result = self.stop(message='Everything is complete.')
        self.assertEqual('continue', result['action'])
        self.assertNotIn('no_observed_tool_activity', result['signals'])

    def test_stop_budgets(self):
        self.arm()
        self.assertEqual('continue', self.stop()['action'])
        self.assertEqual('continue', self.stop()['action'])
        self.assertEqual('needs_attention', self.stop()['status'])

    def test_changing_files_cannot_bypass_budget(self):
        self.arm()
        for i in range(4):
            (self.root / '报告.md').write_text(str(i), encoding='utf-8')
            result = self.stop()
        self.assertEqual('needs_attention', result['status'])

    def test_time_budget(self):
        self.arm()
        result = engine.handle(self.store, self.event, now=1300)
        self.assertEqual('needs_attention', result['status'])

    def test_interrupt(self):
        self.arm()
        self.stop(event='interrupt')
        self.assertEqual('paused_by_user', self.stop()['status'])

    def test_user_correction_pauses_old_scope(self):
        self.arm()
        self.stop(event='user_prompt', prompt='Stop editing; explain first')
        self.assertEqual('paused_for_new_message', self.stop()['status'])

    def test_continuation_prompt_can_be_consumed_once(self):
        self.arm()
        reason = self.stop()['reason']
        self.assertEqual('active', self.stop(event='user_prompt', prompt=reason)['status'])
        self.assertEqual('paused_for_new_message', self.stop(event='user_prompt', prompt=reason)['status'])

    def test_unknown_session(self):
        self.arm()
        self.assertEqual('unregistered', self.stop(session_id='two')['status'])

    def test_real_blocker(self):
        self.arm()
        self.stop(event='blocked')
        self.assertEqual('needs_input', self.stop()['status'])

    def test_plan(self):
        self.arm()
        self.assertEqual('paused_for_plan', self.stop(mode='plan')['status'])

    def test_wrong_directory(self):
        self.arm()
        self.assertEqual('scope_mismatch', self.stop(cwd=str(self.root.parent))['status'])

    def test_traversal(self):
        self.contract['checks'][0]['path'] = '../escape'
        with self.assertRaises(ValueError):
            self.arm()

    def test_duplicate_check_ids(self):
        self.contract['checks'].append(copy.deepcopy(self.contract['checks'][0]))
        with self.assertRaises(ValueError):
            self.arm()

    def test_active_contract_is_frozen(self):
        self.arm()
        with self.assertRaises(ValueError):
            self.arm()

    def test_command_validator_rejects_false_claim(self):
        self.contract['checks'] = [{'id': 'tests', 'kind': 'command', 'argv': [sys.executable, '-c', 'raise SystemExit(1)']}]
        self.arm()
        result = self.stop(message='All done')
        self.assertEqual('continue', result['action'])
        self.assertEqual(['validator_failed'], result['checks'][0]['reasons'])

    def test_command_validator_passes(self):
        self.contract['checks'] = [{'id': 'tests', 'kind': 'command', 'argv': [sys.executable, '-c', 'print("ok")']}]
        self.arm()
        self.assertEqual('checks_passed', self.stop()['status'])

    def test_validator_timeout(self):
        self.contract['checks'] = [{'id': 'slow', 'kind': 'command', 'argv': [sys.executable, '-c', 'import time;time.sleep(3)'], 'timeout': 1}]
        self.arm()
        self.assertEqual(['validator_timeout'], self.stop()['checks'][0]['reasons'])

    def test_empty_contract_rejected(self):
        self.contract['checks'] = []
        with self.assertRaises(ValueError):
            self.arm()

    def test_malformed_cli_input(self):
        run = subprocess.run([sys.executable, '-m', 'go_work', 'hook'], input=b'broken', capture_output=True)
        self.assertEqual(0, run.returncode)
        self.assertIn('systemMessage', json.loads(run.stdout))

    def test_generic_cli_protocol(self):
        engine.arm(self.store, 'one', self.contract)
        run = subprocess.run([sys.executable, '-m', 'go_work', '--store', str(self.store), 'event'],
                             input=json.dumps(self.event).encode(), capture_output=True)
        self.assertEqual('continue', json.loads(run.stdout)['action'])

    def test_all_native_adapters(self):
        for profile in ('codex', 'qwen', 'deepseek-codex'):
            with self.subTest(profile=profile):
                event = adapters.normalize(profile, {'hook_event_name': 'Stop', 'session_id': 's',
                                           'cwd': '.', 'last_assistant_message': None})
                self.assertEqual('stop', event['event'])
                self.assertEqual('', event['message'])
                self.assertEqual({'decision': 'block', 'reason': 'missing'}, adapters.output(profile, {'action': 'continue', 'reason': 'missing'}))

    def test_native_config_profiles(self):
        for profile in ('codex', 'qwen', 'deepseek-codex'):
            config = hook_config(profile)
            self.assertIn('Stop', config['hooks'])
            self.assertIn(profile, config['hooks']['Stop'][0]['hooks'][0]['command'])

    def test_runtime_error_releases(self):
        engine.arm(self.store, 'one', self.contract)
        engine.state_path(self.store, 'one').write_text('broken')
        run = subprocess.run([sys.executable, '-m', 'go_work', '--store', str(self.store), 'event'],
                             input=json.dumps(self.event).encode(), capture_output=True)
        self.assertEqual('error', json.loads(run.stdout)['status'])

    def test_interrupt_during_validator_wins(self):
        self.contract['checks'] = [{'id': 'slow', 'kind': 'command', 'argv': [sys.executable, '-c',
            'from pathlib import Path; import time; Path("started").touch(); time.sleep(5)'], 'timeout': 10}]
        self.contract['checks'].append({'id': 'later', 'kind': 'command',
            'argv': [sys.executable, '-c', 'from pathlib import Path; Path("must-not-run").touch()']})
        self.arm()
        results = []
        thread = threading.Thread(target=lambda: results.append(self.stop()))
        thread.start()
        deadline = time.monotonic() + 4
        while not (self.root / 'started').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue((self.root / 'started').exists())
        self.assertEqual('paused_by_user', self.stop(event='interrupt')['status'])
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual('paused_by_user', results[0]['status'])
        self.assertNotEqual('continue', results[0]['action'])
        self.assertFalse((self.root / 'must-not-run').exists())

    def test_response_text_is_not_persisted(self):
        self.arm()
        self.stop(message='You are right. PRIVATE_RESPONSE_EXAMPLE')
        stored = engine.state_path(self.store, 'one').read_text()
        self.assertNotIn('PRIVATE_RESPONSE_EXAMPLE', stored)
        self.assertIn('last_signature', stored)

    def test_late_interrupt_before_response_wins(self):
        self.arm()
        original = engine.classify
        def interrupt_then_classify(*args):
            self.stop(event='interrupt')
            return original(*args)
        with patch.object(engine, 'classify', side_effect=interrupt_then_classify):
            result = self.stop()
        self.assertEqual('paused_by_user', result['status'])
        self.assertNotEqual('continue', result['action'])

    def test_invalid_encoding_is_unmet_check(self):
        self.arm()
        (self.root / '报告.md').write_bytes(b'\xff\xfe\xff')
        result = self.stop(message='All done')
        self.assertEqual('continue', result['action'])
        self.assertIn('artifact_encoding_invalid', result['checks'][0]['reasons'])

    def test_oversized_artifact_is_unmet_check(self):
        self.arm()
        (self.root / '报告.md').write_bytes(b'x' * (engine.MAX_FILE + 1))
        self.assertEqual('continue', self.stop()['action'])

    def test_rearm_after_explicit_pause(self):
        self.arm()
        engine.pause(self.store, 'one', 'new task')
        self.assertEqual('paused', engine.status(self.store, 'one')['status'])
        self.assertEqual('active', self.arm()['status'])

    def test_qwen_tool_prompt_keeps_contract(self):
        self.arm()
        event = adapters.normalize('qwen', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'one', 'prompt': 'tool result'})
        self.assertEqual('active', engine.handle(self.store, event)['status'])
        self.assertEqual('continue', self.stop()['action'])

    def test_qwen_submitted_prompt_pauses(self):
        self.arm()
        event = adapters.normalize('qwen', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'one',
                                          'prompt': 'wrapped', 'submitted_prompt': 'please stop'})
        self.assertEqual('paused_for_new_message', engine.handle(self.store, event)['status'])

    def test_os_lock_released_after_process_crash(self):
        self.arm()
        path = engine.state_path(self.store, 'one')
        code = 'from pathlib import Path; from go_work.engine import lock; import os,sys\nwith lock(Path(sys.argv[1])): os._exit(0)'
        subprocess.run([sys.executable, '-c', code, str(path)], check=True)
        self.assertEqual('continue', self.stop()['action'])


if __name__ == '__main__':
    unittest.main()
