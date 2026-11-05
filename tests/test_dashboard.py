"""Shared dashboard, state-only review, collection controls and local playback checks."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

import console  # source-checkout bootstrap
from librivox_download import launch as batch
from librivox_download import dashboard as web
from librivox_download import fetch as app
from test_librivox_fetch import candidate, serving


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="librivox-dashboard-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = {**batch.DEFAULTS, "download_texts": False, "count": 1, "name": "Test reader", "reader_id": "1",
                    "url": "https://librivox.org/reader/1/", "out": str(self.root / "1")}
        self.st = app.State(batch.reader_args(self.job), "1", Path(self.job["out"]))
        self.c = candidate()
        self.st.candidates = [self.c]
        self.st.want_downloads = 1
        self.audio = self.st.out / "project-1" / "test.mp3"
        self.audio.parent.mkdir(parents=True)
        self.audio.write_bytes(b"0123456789audio")
        self.c["download"] = {"status": "done", "quality": "128", "file": "project-1/test.mp3", "at": "original"}
        self.st.save()

    def test_review_decision_normalizes_legacy_download_path_without_changing_audio(self):
        saved = json.loads(self.st.path.read_text(encoding="utf-8"))
        saved["candidates"][0]["download"]["file"] = "project-1\\test.mp3"
        self.st.path.write_text(json.dumps(saved), encoding="utf-8")
        view = web.Dashboard.for_review(self.root)
        view.change("1", self.c["url"], "decide", "keep")
        updated = json.loads(self.st.path.read_text(encoding="utf-8"))
        download = updated["candidates"][0]["download"]
        self.assertEqual(download, {"status": "done", "quality": "128", "file": "project-1/test.mp3", "at": "original"})
        self.assertEqual(self.audio.read_bytes(), b"0123456789audio")
        self.assertEqual(updated["candidates"][0]["decision"], "keep")

    def request(self, base, path, body=None, headers=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
        return urllib.request.urlopen(request, timeout=5)

    def disconnected_request(self, path, error, fail_write=2, body=None):
        class Writer(io.BytesIO):
            writes = 0
            def write(self, data):
                self.writes += 1
                if self.writes == fail_write:
                    raise error('fixture disconnected')
                return super().write(data)
        handler_type = web.make_handler(web.Dashboard.for_review(self.root))
        handler = handler_type.__new__(handler_type)
        payload = json.dumps(body).encode() if body is not None else b''
        verb = 'POST' if body is not None else 'GET'
        request = f'{verb} {path} HTTP/1.0\r\nHost: localhost\r\nContent-Length: {len(payload)}\r\n\r\n'.encode() + payload
        handler.rfile, handler.wfile = io.BytesIO(request), Writer()
        handler.client_address = ('127.0.0.1', 12345)
        handler.handle()
        return handler

    def test_client_disconnects_during_headers_json_and_media_are_quiet(self):
        media = '/media?' + urllib.parse.urlencode({'reader': '1', 'url': self.c['url']})
        for error in web.CLIENT_DISCONNECTS:
            for path in ('/api/dashboard', media):
                for fail_write in (1, 2):
                    with self.subTest(error=error, path=path, fail_write=fail_write):
                        handler = self.disconnected_request(path, error, fail_write)
                        self.assertTrue(handler.close_connection)

    def test_disconnect_after_decision_does_not_lose_saved_change_or_send_error_response(self):
        handler = self.disconnected_request('/api/decide', ConnectionAbortedError, body={
            'reader': '1', 'url': self.c['url'], 'decision': 'keep'})
        self.assertEqual(handler.wfile.writes, 2)
        saved = json.loads(self.st.path.read_text())
        self.assertEqual(saved['candidates'][0]['decision'], 'keep')

    def test_unrelated_io_errors_are_not_silenced(self):
        with self.assertRaises(PermissionError):
            self.disconnected_request('/api/dashboard', PermissionError)

    def post(self, base, action, **body):
        with self.request(base, "/api/" + action, body) as response:
            return json.load(response)

    def test_review_open_and_snapshot_do_not_change_saved_state_or_run_collection(self):
        raw = json.loads(self.st.path.read_text())
        raw["custom_metadata"] = {"preserve": True}
        raw["candidates"][0]["download"]["status"] = "queued"
        raw.pop("selection")  # legacy states remain reviewable
        self.st.path.write_text(json.dumps(raw))
        before = self.st.path.read_bytes()
        with patch.object(app, "listing_pages") as scan, patch.object(app, "download") as transfer:
            dashboard = web.Dashboard.for_review(self.root)
            snapshot = dashboard.snapshot()
        self.assertEqual(snapshot["mode"], "review")
        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["readers"][0]["candidates"][0]["review_status"], "queued")
        self.assertEqual(self.st.path.read_bytes(), before)
        scan.assert_not_called()
        transfer.assert_not_called()

    def test_both_pages_and_mark_bad_clear_persist_without_deleting_audio(self):
        dashboard = web.Dashboard.for_review(self.root)
        with serving(web.make_handler(dashboard)) as (base, _):
            for page in ("/", "/review?reader=1"):
                with self.request(base, page) as response:
                    html = response.read().decode()
                    self.assertIn('id="overview"', html)
                    self.assertIn('id="review"', html)
            self.post(base, "decide", reader="1", url=self.c["url"], decision="reject")
            view = dashboard.snapshot()["readers"][0]
            self.assertEqual((view["downloaded"], view["usable"], view["rejected"]), (1, 0, 1))
            self.assertEqual(web.Dashboard.for_review(self.root).read("1")["candidates"][0]["decision"], "reject")
            self.post(base, "decide", reader="1", url=self.c["url"], decision=None)
        self.assertEqual(dashboard.read("1")["candidates"][0]["download"]["at"], "original")
        self.assertEqual(dashboard.snapshot()["readers"][0]["usable"], 1)
        self.assertTrue(self.audio.is_file())

    def test_review_refuses_collection_and_cross_origin_posts(self):
        dashboard = web.Dashboard.for_review(self.root)
        with serving(web.make_handler(dashboard)) as (base, _):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post(base, "start")
            self.assertEqual(error.exception.code, 400)
            for action in ("download", "retry_128", "missing_128"):
                with self.subTest(action=action), self.assertRaises(urllib.error.HTTPError) as error:
                    self.post(base, action, reader="1", url=self.c["url"])
                self.assertEqual(error.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as error:
                with self.request(base, "/api/decide", {"reader": "1", "url": self.c["url"], "decision": "reject"},
                                  headers={"Origin": "https://example.invalid"}):
                    pass
            self.assertEqual(error.exception.code, 403)
        self.assertIsNone(dashboard.read("1")["candidates"][0]["decision"])

    def test_local_audio_supports_head_ranges_and_missing_files(self):
        dashboard = web.Dashboard.for_review(self.root)
        url = dashboard.snapshot()["readers"][0]["candidates"][0]["audio_url"]
        with serving(web.make_handler(dashboard)) as (base, _):
            with self.request(base, url, headers={"Range": "bytes=2-5"}) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), b"2345")
                self.assertEqual(response.headers["Content-Range"], "bytes 2-5/15")
            with self.request(base, url, headers={"Range": "bytes=-5"}) as response:
                self.assertEqual(response.read(), b"audio")
            with self.request(base, url, method="HEAD") as response:
                self.assertEqual(response.headers["Content-Length"], "15")
                self.assertEqual(response.read(), b"")
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(base, url, headers={"Range": "bytes=99-"})
            self.assertEqual(error.exception.code, 416)
            self.audio.unlink()
            before = self.st.path.read_bytes()
            view = dashboard.snapshot()["readers"][0]
            self.assertEqual(view["candidates"][0]["review_status"], "missing")
            self.assertEqual(view["downloaded"], 0)
            self.assertEqual(self.st.path.read_bytes(), before)
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(base, url)
            self.assertEqual(error.exception.code, 404)

    def test_audio_cannot_escape_reader_output(self):
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"private")
        self.c["download"]["file"] = "../outside.mp3"
        self.st.save()
        dashboard = web.Dashboard.for_review(self.root / "1")
        self.assertIsNone(dashboard.snapshot()["readers"][0]["candidates"][0]["audio_url"])
        self.assertIsNone(dashboard.audio_path("1", self.c))

    def test_completed_batch_bad_decision_does_not_restart_and_resume_is_explicit(self):
        dashboard = web.Dashboard(jobs=[self.job])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch.object(app, "listing_pages") as scan, patch.object(app, "download") as transfer:
            dashboard.start()
            dashboard.worker.join(5)
            self.assertFalse(dashboard.running)
            dashboard.change("1", self.c["url"], "decide", "reject")
            self.assertFalse(dashboard.running)
            self.assertEqual(dashboard.snapshot()["readers"][0]["usable"], 0)
            scan.assert_not_called()
            transfer.assert_not_called()
        project = {"url": candidate(2)["url"], "title": "Replacement", "type": "Solo", "language": "English"}
        def transfer(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"replacement")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch.object(app, "listing_pages", return_value=iter([(1, [project])])), \
                patch.object(app, "check", return_value=(candidate(2), None)), \
                patch.object(app, "download", side_effect=transfer):
            dashboard.start("1")
            dashboard.worker.join(5)
        self.assertFalse(dashboard.worker.is_alive())
        self.assertEqual(dashboard.snapshot()["readers"][0]["usable"], 1)
        self.assertEqual(dashboard.read("1")["candidates"][0]["decision"], "reject")
        self.assertTrue(self.audio.exists())

    def test_marking_bad_during_live_transfer_is_not_overwritten(self):
        self.c["download"] = None
        self.st.save()
        entered, release = threading.Event(), threading.Event()
        dashboard = web.Dashboard(jobs=[self.job])
        def transfer(url, dest):
            entered.set()
            if not release.wait(5):
                raise AssertionError("test transfer not released")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"audio")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch.object(app, "download", side_effect=transfer), \
                patch.object(app, "listing_pages", return_value=iter(())):
            dashboard.start()
            try:
                self.assertTrue(entered.wait(5))
                dashboard.change("1", self.c["url"], "decide", "reject")
            finally:
                release.set()
                dashboard.worker.join(5)
        saved = dashboard.read("1")["candidates"][0]
        self.assertEqual(saved["decision"], "reject")
        self.assertEqual(saved["download"]["status"], "done")

    def test_pause_prevents_starting_another_reader(self):
        stop = threading.Event()
        stop.set()
        with patch.object(batch, "run_reader") as run, contextlib.redirect_stderr(io.StringIO()):
            summary = batch.run_batch([self.job], stop=stop)
        run.assert_not_called()
        self.assertEqual(summary["results"][0]["status"], "not_run")

    def test_live_pause_finishes_current_transfer_and_keeps_next_reader_idle(self):
        self.c["download"] = None
        self.st.save()
        second = {**self.job, "reader_id": "2", "name": "Second", "out": str(self.root / "2")}
        dashboard = web.Dashboard(jobs=[self.job, second])
        entered, release = threading.Event(), threading.Event()
        def transfer(url, dest):
            entered.set()
            if not release.wait(5):
                raise AssertionError("transfer not released")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"finished before pause")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch.object(app, "download", side_effect=transfer), patch.object(app, "listing_pages") as scan:
            dashboard.start()
            try:
                self.assertTrue(entered.wait(5))
                dashboard.pause()
                self.assertTrue(dashboard.snapshot()["pausing"])
            finally:
                release.set()
                dashboard.worker.join(5)
        self.assertFalse(dashboard.worker.is_alive())
        self.assertEqual(dashboard.results["1"]["status"], "paused")
        self.assertEqual(dashboard.results["2"]["status"], "not_run")
        self.assertEqual(dashboard.read("1")["candidates"][0]["download"]["status"], "done")
        self.assertFalse(Path(second["out"]).exists())
        scan.assert_not_called()

    def test_single_reader_idle_does_not_replace_bad_recordings(self):
        self.st.collecting = False
        self.c["decision"] = "reject"
        with patch.object(app, "download_next") as transfer, \
                patch.object(self.st.wake, "wait", side_effect=lambda *args: self.st.stop.set()):
            app.downloader(self.st)
        transfer.assert_not_called()
        dashboard = web.Dashboard.for_interactive(self.st)
        dashboard.start(count=2)
        self.assertTrue(self.st.collecting)
        self.assertEqual(self.st.want_downloads, 2)

    def test_review_duplicate_reader_rejected_and_empty_root_supported(self):
        (self.root / "empty").mkdir()
        self.assertEqual(web.Dashboard.for_review(self.root / "empty").snapshot()["readers"], [])
        other = self.root / "duplicate"
        other.mkdir()
        (other / "state.json").write_bytes(self.st.path.read_bytes())
        with self.assertRaisesRegex(ValueError, "duplicate reader"):
            web.Dashboard.for_review(self.root)

    def test_dashboard_cli_routes_and_bind_before_collection(self):
        manifest = self.root / "batch.json"
        manifest.write_text(json.dumps({"readers": [{"url": self.job["url"]}], "output_root": "audio"}))
        with patch("sys.argv", ["librivox_launch.py", str(manifest)]), patch.object(web, "serve_dashboard") as serve:
            self.assertEqual(batch.main(), 0)
            self.assertTrue(serve.call_args.kwargs["collect"])
        with patch("sys.argv", ["librivox_launch.py", "--review", str(self.root / "1")]), \
                patch.object(web, "serve_dashboard") as serve:
            self.assertEqual(batch.main(), 0)
            self.assertFalse(serve.call_args.args[0].jobs)
        dashboard = web.Dashboard(jobs=[self.job])
        with app.LocalServer(("127.0.0.1", 0), web.make_handler(dashboard)) as occupied, \
                patch.object(dashboard, "start") as start:
            with self.assertRaises(SystemExit):
                web.serve_dashboard(dashboard, occupied.server_port, collect=True)
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
