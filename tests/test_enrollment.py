import json
from pathlib import Path
import tempfile
import unittest
from go_work.enrollment import context

class EnrollmentTests(unittest.TestCase):
    def test_opt_in_scope_and_event_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {'event':'user_prompt','session_id':'synthetic','prompt':'write a report','cwd':tmp}
            self.assertIsNone(context(root, 'codex', event))
            (root/'enrollment.json').write_text(json.dumps({'roots':[tmp]}))
            self.assertIn('arm --session synthetic', context(root, 'codex', event))
            self.assertIn('Questions, discussion', context(root, 'codex', event))
            for profile in ['qwen','generic','deepseek-codex']:
                self.assertIsNone(context(root, profile, event))
            for kind in ['stop','tool','interrupt']:
                self.assertIsNone(context(root, 'codex', dict(event,event=kind)))
            self.assertIsNone(context(root, 'codex', dict(event,cwd=str(root/'elsewhere'))))
            self.assertIsNone(context(root, 'codex', dict(event,prompt=None)))

    def test_new_chat_registered_without_model_and_idempotent(self):
        from go_work import engine
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'enrollment.json').write_text(json.dumps({'roots':[tmp]}))
            event = {'event':'user_prompt','session_id':'new-chat','prompt':'private text','cwd':tmp}
            context(root, 'codex', event)
            first = engine.status(root, 'new-chat')
            self.assertEqual('registered', first['status'])
            self.assertEqual('awaiting_contract', first['task_status'])
            context(root, 'codex', event)
            self.assertEqual(first['registered_at'], engine.status(root, 'new-chat')['registered_at'])
            self.assertNotIn('private text', json.dumps(engine.status(root, 'new-chat')))
            self.assertEqual('allow', engine.handle(root, dict(event,event='stop'))['action'])
            engine.arm(root, 'new-chat', {'root':tmp,'objective':'write output','checks':[{'path':'out.txt'}]})
            context(root, 'codex', event)
            self.assertEqual('active', engine.status(root, 'new-chat')['status'])
            self.assertEqual(1, len(list((root/'registrations').glob('*.json'))))
            context(root, 'codex', dict(event,session_id='another-chat'))
            self.assertEqual(2, len(list((root/'registrations').glob('*.json'))))
