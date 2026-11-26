"""Session selection, staged controller switching and source-checkout entry points."""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import librivox_web
from librivox_download import dashboard, launch, web
from librivox_download.sessions import Sessions


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def session(self, name, data=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data or {}), encoding="utf-8")
        return path

    def wait(self, predicate):
        limit = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > limit:
                self.fail("session transition did not finish")
            time.sleep(.01)

    def component(self):
        component = web.create_component({"settings_dir": self.root})
        self.assertEqual(list(self.root.iterdir()), [])
        component.start()
        self.addCleanup(component.stop)
        return component

    def snapshot(self, component):
        return json.loads(component.app.handle("GET", "/api/dashboard")[2])

    def post(self, component, action, **body):
        return component.app.handle("POST", "/api/" + action, json.dumps(body).encode())

    def test_new_console_requires_file_for_noninteractive_commands(self):
        for option in ("--headless", "--dry-run"):
            with patch("sys.argv", ["librivox_web.py", option]), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                librivox_web.main()
            self.assertEqual(error.exception.code, 2)

    def test_create_named_session_and_show_active_path_without_collection(self):
        component = self.component()
        self.assertIsNone(self.snapshot(component)["session"]["active"])
        with patch.object(launch, "run_batch") as collect:
            self.assertEqual(self.post(component, "session_new", file="listen")[0], 200)
            self.wait(lambda: not self.snapshot(component)["session"]["switching"])
            collect.assert_not_called()
        path = self.root / "sessions/listen.json"
        self.assertFalse(json.loads(path.read_text(encoding="utf-8"))["auto_collect"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["output_root"], "../downloads")
        info = self.snapshot(component)["session"]
        self.assertEqual(info["active"], str(path))
        self.assertEqual(info["generation"], 1)
        before = path.read_bytes()
        self.assertEqual(self.post(component, "session_new", file="listen.json")[0], 400)
        self.assertEqual(path.read_bytes(), before)

    def test_list_launch_and_sessions_json_with_validation_errors(self):
        host = Sessions(dashboard.Dashboard(), self.root)
        good = self.session("sessions/good.json", {"readers": [1]})
        other = self.session("existing.json")
        bad = self.session("invalid.json", {"other_app": True})
        info = {entry["path"]: entry for entry in host.snapshot()["files"]}
        self.assertTrue(info[str(good)]["valid"])
        self.assertTrue(info[str(other)]["valid"])
        self.assertFalse(info[str(bad)]["valid"])
        self.assertIn("batch accepts", info[str(bad)]["error"])
        with self.assertRaises(ValueError):
            host.open(str(bad))
        self.assertFalse(host.switching)

    def test_creation_rejects_paths_and_open_rejects_unlisted_paths(self):
        host = Sessions(dashboard.Dashboard(), self.root)
        for name in ("../bad.json", "nested/bad.json", "nested\\bad.json", "C:bad.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                host.open(name, create=True)
        self.assertFalse(host.home.exists())
        with self.assertRaises(ValueError):
            host.open(str(self.root.parent / "outside.json"))

    def test_switch_waits_for_old_work_and_preserves_files(self):
        old_file = self.session("old.json", {"readers": [1], "auto_collect": False})
        new_file = self.session("new.json", {"readers": [2], "auto_collect": True, "output_root": "other"})
        old = dashboard.Dashboard(jobs=launch.load_batch(old_file), manifest=old_file)
        old.serving = old.running = True
        saved = self.root / "downloads/1/state.json"
        saved.parent.mkdir(parents=True)
        saved.write_text('{"reader_id":"1","candidates":[]}', encoding="utf-8")
        audio = saved.with_name("recording.mp3"); audio.write_bytes(b"existing recording")
        before = saved.read_bytes()
        host = Sessions(old, self.root)
        stopping, release = threading.Event(), threading.Event()
        def worker():
            old.stop.wait(3)
            stopping.set()
            release.wait(3)
            old.running = False
        old.worker = threading.Thread(target=worker)
        old.worker.start()
        self.addCleanup(host.stop)
        self.addCleanup(release.set)
        app = web.create_app(lambda: host.current, host)
        payload = json.dumps({"file": str(new_file), "session_generation": 0}).encode()
        with patch.object(launch, "run_batch") as collect:
            self.assertEqual(app.handle("POST", "/api/session_open", payload)[0], 200)
            self.assertTrue(stopping.wait(2))
            self.assertTrue(host.switching)
            self.assertIs(host.current, old)
            self.assertEqual(app.handle("POST", "/api/start", b'{}')[0], 409)
            release.set()
            self.wait(lambda: not host.switching)
            collect.assert_not_called()
        self.assertEqual(host.current.manifest, new_file)
        self.assertFalse(old.serving)
        self.assertTrue(host.current.serving)
        self.assertFalse(host.current.running)
        self.assertEqual(saved.read_bytes(), before)
        self.assertEqual(audio.read_bytes(), b"existing recording")
        stale = json.dumps({"session_generation": 0}).encode()
        self.assertEqual(app.handle("POST", "/api/start", stale)[0], 409)

    def test_mounted_session_routes_stay_within_the_downloader(self):
        from librivox_download.microweb import Shell
        component = self.component()
        shell = Shell(); shell.add(component, "/downloads")
        page = shell.handle("GET", "/downloads/")[2].decode()
        self.assertIn('<base href="/downloads/">', page)
        self.assertIn('id="session-picker"', page)
        self.assertEqual(shell.handle("POST", "/downloads/api/session_new", b'{"file":"mounted.json"}')[0], 200)
        self.wait(lambda: not self.snapshot(component)["session"]["switching"])
        self.assertTrue((self.root / "sessions/mounted.json").exists())

    def test_session_changed_while_draining_leaves_old_session_available(self):
        original = self.session("old.json")
        chosen = self.session("new.json")
        old = dashboard.Dashboard(manifest=original)
        host = Sessions(old, self.root)
        release = threading.Event()
        old.worker = threading.Thread(target=lambda: release.wait(3))
        old.worker.start()
        self.addCleanup(host.stop)
        self.addCleanup(release.set)
        host.open(str(chosen))
        chosen.write_text("invalid JSON", encoding="utf-8")
        release.set()
        self.wait(lambda: not host.switching)
        self.assertIs(host.current, old)
        self.assertTrue(old.serving)
        self.assertFalse(old.closing)
        self.assertTrue(host.error)
        self.assertEqual(host.generation, 0)

    def test_review_only_has_no_switching_and_picker_requires_absolute_settings_directory(self):
        saved = self.session("state.json", {"reader_id": "1", "candidates": []})
        component = web.create_component({"review_root": saved})
        component.start()
        try:
            self.assertFalse(self.snapshot(component)["session"]["enabled"])
            self.assertEqual(self.post(component, "session_new", file="unwanted")[0], 400)
            self.assertFalse((self.root / "sessions").exists())
        finally:
            component.stop()
        with self.assertRaisesRegex(ValueError, "absolute"):
            web.create_component({"settings_dir": "relative"})
        empty = self.root / "empty"; empty.mkdir()
        component = web.dashboard_component(dashboard.Dashboard.for_review(empty))
        component.start()
        try:
            self.assertFalse(self.snapshot(component)["session"]["enabled"])
        finally:
            component.stop()

    def test_copied_checkout_launches_without_installation_from_another_directory(self):
        original = Path(librivox_web.__file__).parent
        copied = self.root / "app"
        copied.mkdir()
        shutil.copy2(original / "librivox_web.py", copied / "librivox_web.py")
        shutil.copytree(original / "src", copied / "src", ignore=shutil.ignore_patterns("__pycache__"))
        session = self.session("example.json", {"readers": [1]})
        result = subprocess.run([sys.executable, "-S", "-B", str(copied / "librivox_web.py"), str(session), "--dry-run"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["readers"][0]["reader_id"], "1")
        self.assertFalse((self.root / "downloads").exists())
