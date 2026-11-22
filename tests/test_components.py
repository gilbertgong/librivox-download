"""Downloader standalone/mounted contract, without production state or network."""
import json
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import librivox_web  # source-checkout bootstrap
from librivox_download import dashboard as dashboard
from librivox_download import web as web
from librivox_download.microweb import Shell
from test_librivox_fetch import candidate


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_shipped_manifest_constructs_the_factory_with_defaults(self):
        manifest = json.loads(Path(librivox_web.__file__).with_name('microweb-component.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['component_api'], 1)
        manifest = manifest['components'][0]
        self.assertEqual(manifest['factory'], 'librivox_web:create_component')
        component = web.create_component({**manifest['defaults'], 'settings_dir': self.root})
        self.assertEqual(component.id, manifest['id'])
        self.assertEqual(list(self.root.iterdir()), [])
        component.start()
        try:
            snapshot = json.loads(component.app.handle('GET', '/api/dashboard')[2])
            self.assertIsNone(snapshot['session']['active'])
            self.assertTrue(snapshot['session']['enabled'])
            self.assertFalse(snapshot['running'])
            self.assertEqual(list(self.root.iterdir()), [])
        finally:
            component.stop()

    def test_factory_and_bind_failure_make_no_files_or_workers(self):
        session = self.root / 'session.json'
        component = web.create_component({'session_file': session, 'collect': True})
        self.assertEqual(list(self.root.iterdir()), [])
        from librivox_download.microweb import _Server
        with _Server(('127.0.0.1', 0), component.app._handler_class()) as occupied:
            with self.assertRaises(SystemExit):
                component.run('127.0.0.1', occupied.server_port)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_settings_relative_startup_and_shutdown(self):
        component = web.create_component({'session_file': 'session.json', 'settings_dir': self.root,
                                          'collect': False})
        with patch.object(dashboard.Dashboard, 'start') as start:
            done = threading.Event()
            def ready():
                self.assertTrue((self.root / 'session.json').is_file())
                self.assertEqual(component.app.handle('GET', '/api/dashboard')[0], 200)
                done.set()
            component.run('127.0.0.1', 0, ready, stop_event=done)
        start.assert_not_called()
        self.assertEqual((self.root / 'session.json').read_text(), '{}\n')

    def test_mounted_pages_links_audio_head_and_decisions(self):
        reader = self.root / '1'
        reader.mkdir()
        (reader / 'sample.mp3').write_bytes(b'0123456789')
        item = candidate()
        item['download'] = {'status': 'done', 'file': 'sample.mp3', 'quality': '128'}
        state = {'reader_id': '1', 'reader': 'Example', 'candidates': [item], 'checked': {}, 'status': 'done'}
        saved = reader / 'state.json'
        saved.write_text(json.dumps(state))
        component = web.create_component({'review_root': self.root})
        shell = Shell()
        shell.add(component, '/downloads')
        with patch('librivox_download.fetch.get', side_effect=AssertionError('unexpected network')):
            component.start()
            try:
                for route in ['/', '/review', '/projects']:
                    status, _, body = shell.handle('GET', '/downloads' + route)
                    self.assertEqual(status, 200)
                    self.assertIn(b'<base href="/downloads/">', body)
                    self.assertNotIn(b"fetch('/api/", body)
                    self.assertNotIn(b'href="/review', body)
                data = json.loads(shell.handle('GET', '/downloads/api/dashboard')[2])
                audio = data['readers'][0]['candidates'][0]['audio_url']
                self.assertTrue(audio.startswith('/downloads/media?'))
                status, headers, body = shell.handle('GET', audio, headers={'Range': 'bytes=2-4'})
                self.assertEqual((status, body), (206, b'234'))
                self.assertEqual(headers['Content-Range'], 'bytes 2-4/10')
                self.assertEqual(shell.handle('HEAD', audio)[2], b'')
                payload = json.dumps({'reader': '1', 'url': item['url'], 'decision': 'reject'}).encode()
                self.assertEqual(shell.handle('POST', '/downloads/api/decide', payload)[0], 200)
                self.assertEqual(json.loads(saved.read_text())['candidates'][0]['decision'], 'reject')
                self.assertTrue((reader / 'sample.mp3').is_file())
                self.assertEqual(shell.handle('GET', '/downloads/../state.json')[0], 404)
            finally:
                component.stop()

    def test_stop_waits_for_owned_collection(self):
        view = dashboard.Dashboard()
        released = threading.Event()
        worker = threading.Thread(target=lambda: (view.stop.wait(3), released.set()))
        view.worker = worker
        component = web.dashboard_component(view)
        component.start()
        worker.start()
        component.stop()
        self.assertTrue(released.is_set())
        self.assertFalse(worker.is_alive())
        self.assertFalse(view.serving)


if __name__ == '__main__':
    unittest.main()
