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
