"""Vendored runtime, host framework and entry point contracts; no external requests."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import librivox_web  # source-checkout bootstrap
from librivox_download import microweb, web


class FrameworkTests(unittest.TestCase):
    def test_explicit_framework_controls_routes_responses_and_errors(self):
        spec = importlib.util.spec_from_file_location('test_host_framework', microweb.__file__)
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            component = web.create_component({'settings_dir': root}, framework=host)
            self.assertIsInstance(component, host.Component)
            self.assertIsInstance(component.app, host.App)
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(component.app.handle('GET', '/api/dashboard')[0], 503)
            component.start()
            try:
                shell = host.Shell(); shell.add(component, '/downloads')
                status, _, page = shell.handle('GET', '/downloads/')
                self.assertEqual(status, 200)
                self.assertIn(b'<base href="/downloads/">', page)
                self.assertEqual(shell.handle('POST', '/downloads/api/session_new', b'{"file":"test.json"}')[0], 200)
                self.assertTrue((root / 'sessions/test.json').is_file())
            finally:
                component.stop()

    def test_vendored_updater_runs_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-B', str(Path(microweb.__file__).resolve()), '--version'],
                                    cwd=tmp, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), microweb.__version__)

    def test_entry_point_runs_the_console(self):
        with patch('librivox_download.launch.main', return_value=0) as launch:
            self.assertEqual(librivox_web.main(), 0)
        launch.assert_called_once_with()
