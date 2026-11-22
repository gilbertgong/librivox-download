"""Namespaced runtime and source/installed entry contracts; no external requests."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import console  # existing source-checkout bootstrap
from librivox_download import cli, fetch, microweb, web


class PackagingTests(unittest.TestCase):
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

    def test_namespaced_updater_cli_from_another_directory(self):
        source = Path(microweb.__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': str(source)}
        with tempfile.TemporaryDirectory() as tmp:
            for argv in ([sys.executable, '-B', '-m', 'librivox_download.microweb', '--version'],
                         [sys.executable, '-B', str(Path(microweb.__file__).resolve()), '--version']):
                result = subprocess.run(argv, cwd=tmp, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), microweb.__version__)

    def test_installed_cli_selects_sessions(self):
        with patch('librivox_download.launch.main', return_value=0) as launch:
            self.assertEqual(cli.main(), 0)
        launch.assert_called_once_with(choose_session=True)

    def test_single_reader_default_output_is_relative_to_launch_directory(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            with patch.object(sys, 'argv', ['fetch', 'Example Reader', 'https://librivox.org/reader/1/']), \
                 patch('librivox_download.dashboard.serve_dashboard') as serve:
                fetch.main()
            view = serve.call_args.args[0]
            self.assertEqual(Path(view.jobs['1']['out']), Path(tmp) / 'downloads/example_reader')
            self.assertFalse((Path(tmp) / 'downloads').exists())
