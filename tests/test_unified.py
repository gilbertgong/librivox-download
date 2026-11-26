"""Manual and automatic collection share one JSON dashboard and sequential worker."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import librivox_web  # source-checkout bootstrap
from librivox_download import launch as batch
from librivox_download import dashboard as web
from librivox_download import fetch as app
from test_librivox_fetch import candidate, serving


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="librivox-unified-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.json"

    def dashboard(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return web.Dashboard(batch.load_batch(self.path), manifest=self.path)

    def configured(self):
        dashboard = self.dashboard({"auto_collect": False, "defaults": {"download_texts": False},
                                    "readers": [{"reader_id": 1, "name": "Fixture", "count": 5}]})
        state = app.State(batch.reader_args(dashboard.jobs["1"]), "1", dashboard.paths["1"].parent)
        state.candidates = [candidate(), candidate(2)]
        state.want_downloads = 5
        state.save()
        return dashboard, state

    def test_empty_json_opens_entry_and_validates_defaults(self):
        for data in ({}, {"readers": []}):
            dashboard = self.dashboard(data)
            self.assertEqual(dashboard.snapshot()["readers"], [])
            self.assertEqual(dashboard.snapshot()["mode"], "batch")
            self.assertTrue(dashboard.snapshot()["can_add"])
            self.assertFalse(dashboard.snapshot()["can_collect"])
        for data in ({"defaults": {"count": 0}}, {"auto_collect": "false"}, {"readers": None}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.dashboard(data)

    def test_add_reader_persists_settings_notes_and_stays_idle(self):
        dashboard = self.dashboard({"defaults": {"download_texts": False}, "_ignore": {"notes": "Keep me"}})
        with patch.object(app, "get") as get:
            dashboard.add_reader("https://librivox.org/reader/001/", 3)
            get.assert_not_called()
        saved = json.loads(self.path.read_text())
        self.assertFalse(saved["auto_collect"])
        self.assertEqual(saved["_ignore"], {"notes": "Keep me"})
        self.assertEqual(batch.load_batch(self.path)[0]["count"], 3)
        self.assertFalse(dashboard.running)
        self.assertFalse(dashboard.paths["1"].exists())
        before = self.path.read_bytes()
        for value in ("1", "https://example.invalid/reader/2/", "-1", ""):
            with self.assertRaises(ValueError):
                dashboard.add_reader(value, 1)
            self.assertEqual(self.path.read_bytes(), before)

    def test_external_manifest_edit_is_not_overwritten(self):
        dashboard = self.dashboard({})
        self.path.write_text('{"_ignore":"user edit"}')
        with self.assertRaisesRegex(ValueError, "changed outside"):
            dashboard.add_reader("1", 1)
        self.assertEqual(json.loads(self.path.read_text()), {"_ignore": "user edit"})
        self.assertFalse(dashboard.jobs)

    def test_reader_entry_http_route_and_reopen(self):
        dashboard = self.dashboard({})
        with serving(web.make_handler(dashboard)) as (base, _):
            request = urllib.request.Request(base + "/api/add_reader", data=json.dumps(
                {"value": "42", "n": 2}).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
        reopened = web.Dashboard(batch.load_batch(self.path), manifest=self.path)
        self.assertEqual(reopened.snapshot()["readers"][0]["id"], "42")
        self.assertFalse(reopened.manifest_data["auto_collect"])

    def test_browse_resolves_name_without_audio_or_text_download(self):
        dashboard = self.dashboard({"readers": [1]})
        with patch.object(batch, "resolve_name", return_value=("Resolved reader", "page")), \
                patch.object(app, "listing_pages", return_value=iter(())), \
                patch.object(app, "download") as audio, patch.object(app.texts, "fetch_book") as text:
            dashboard.rescan("1")
            dashboard.worker.join(5)
            self.assertFalse(dashboard.running)
            audio.assert_not_called()
            text.assert_not_called()
        saved = dashboard.read("1")
        self.assertEqual(saved["reader"], "Resolved reader")
        self.assertEqual(saved["reader_name_source"], "page")

    def test_individual_download_does_not_fill_saved_bulk_target(self):
        dashboard, state = self.configured()
        transfers = []

        def transfer(url, dest):
            transfers.append(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fixture audio")

        with patch.object(app, "download", side_effect=transfer), patch.object(app, "listing_pages") as scan:
            dashboard.change("1", state.candidates[0]["url"], "download")
            dashboard.worker.join(5)
            scan.assert_not_called()
        self.assertEqual(len(transfers), 1)
        saved = dashboard.read("1")
        self.assertEqual(saved["candidates"][0]["download"]["status"], "done")
        self.assertIsNone(saved["candidates"][1]["download"])
        self.assertEqual(saved["want_downloads"], 5)
        self.assertFalse(dashboard.running)
        dashboard.audio_path("1", saved["candidates"][0]).unlink()
        self.assertEqual(dashboard.snapshot()["readers"][0]["candidates"][0]["review_status"], "missing")
        with patch.object(app, "download", side_effect=transfer):
            dashboard.change("1", state.candidates[0]["url"], "download")
            dashboard.worker.join(5)
        self.assertEqual(len(transfers), 2)
        self.assertEqual(dashboard.snapshot()["readers"][0]["downloaded"], 1)

    def test_manual_retry_and_fallback_preserve_decisions(self):
        dashboard, state = self.configured()
        state.candidates[0]["decision"] = "keep"
        state.save()
        transfers = []

        def transfer(url, dest):
            transfers.append(url)
            if "128" in url:
                raise OSError("fixture unavailable")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fallback")

        with patch.object(app, "download", side_effect=transfer):
            dashboard.change("1", state.candidates[0]["url"], "download")
            dashboard.worker.join(5)
        self.assertEqual(len(transfers), 2)
        dashboard.change("1", state.candidates[0]["url"], "retry_128")
        saved = dashboard.read("1")["candidates"][0]
        self.assertEqual(saved["quality"], "128")
        self.assertEqual(saved["download"]["quality"], "64")
        self.assertEqual(saved["decision"], "keep")
        self.assertTrue(dashboard.audio_path("1", saved).is_file())

    def test_individual_request_does_not_backfill_unrelated_books(self):
        dashboard, state = self.configured()
        data = json.loads(self.path.read_text())
        data["defaults"]["download_texts"] = True
        dashboard.save_manifest(data)
        audio = state.out / "old.mp3"
        audio.write_bytes(b"old audio")
        state.candidates[0]["download"] = {"status": "done", "quality": "128", "file": "old.mp3"}
        state.save()
        books = []

        def prepare(st, c):
            books.append(c["url"])
            st.text_attempted.add(c["url"])

        def transfer(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"new audio")

        with patch.object(app, "prepare_text", side_effect=prepare), patch.object(app, "download", side_effect=transfer):
            dashboard.change("1", state.candidates[1]["url"], "download")
            dashboard.worker.join(5)
        self.assertEqual(books, [state.candidates[1]["url"]])

    def test_busy_controls_and_concurrent_decisions(self):
        dashboard, state = self.configured()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def transfer(url, dest):
            entered.set()
            release.wait(5)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"audio")

        with patch.object(app, "download", side_effect=transfer):
            dashboard.change("1", state.candidates[0]["url"], "download")
            self.assertTrue(entered.wait(3))
            for action in (lambda: dashboard.start(), lambda: dashboard.rescan(),
                           lambda: dashboard.add_reader("2", 1),
                           lambda: dashboard.change("1", state.candidates[1]["url"], "download")):
                with self.assertRaises(ValueError):
                    action()
            dashboard.change("1", state.candidates[0]["url"], "decide", "reject")
            self.assertIn("1", dashboard.states)
            dashboard.pause()
            release.set()
            dashboard.worker.join(5)
        self.assertEqual(dashboard.read("1")["candidates"][0]["decision"], "reject")
        self.assertFalse(dashboard.running)

    def test_reader_count_saved_and_scan_more_retains_scope(self):
        dashboard, state = self.configured()
        with patch.object(batch, "run_batch", return_value={}), contextlib.redirect_stdout(io.StringIO()):
            dashboard.start("1", 7)
            dashboard.worker.join(5)
        self.assertEqual(batch.load_batch(self.path)[0]["count"], 7)
        with patch.object(app, "listing_pages", return_value=iter(())), patch.object(app, "download") as audio:
            dashboard.scan_more("1", 10)
            dashboard.worker.join(5)
            audio.assert_not_called()
        self.assertEqual(dashboard.read("1")["target"], 24)  # 2 x the goal of 7, plus the 10 more

    def test_startup_policy_and_old_command_use_same_controller(self):
        for data, extra, expected in (({}, [], False), ({"readers": [1]}, [], True),
                                       ({"readers": [1]}, ["--browse"], False),
                                       ({"readers": [1], "auto_collect": False}, [], False)):
            self.dashboard(data)
            with patch("sys.argv", ["librivox-download", str(self.path), *extra]), \
                    patch.object(web, "serve_dashboard") as serve:
                self.assertEqual(batch.main(), 0)
                self.assertEqual(serve.call_args.kwargs["collect"], expected)
        with patch("sys.argv", ["fetch", "Fixture", "https://librivox.org/reader/1/",
                                "--out", str(Path(self.temp.name) / "legacy")]), \
                patch.object(web, "serve_dashboard") as serve:
            app.main()
            self.assertIsNone(serve.call_args.args[0].interactive)
            self.assertTrue(serve.call_args.kwargs["browse"])
        self.assertFalse((Path(self.temp.name) / "legacy").exists())

    def test_no_arguments_creates_default_session_in_working_directory(self):
        with contextlib.chdir(self.temp.name), patch("sys.argv", ["librivox-download"]), \
                patch.object(web, "serve_dashboard") as serve, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(batch.main(), 0)
            path = Path(batch.DEFAULT_SESSION)
            self.assertEqual(path.read_bytes(), b"{}\n")
            self.assertIn(f"Created session: {path.resolve()}\n{{}}", output.getvalue())
            self.assertIn(f"Session settings: {path.resolve()}", output.getvalue())
            self.assertEqual(serve.call_args.args[0].manifest, path.resolve())
            self.assertFalse(serve.call_args.kwargs["collect"])
            path.write_text('{"_ignore": "preserve me"}', encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(batch.main(), 0)
            self.assertEqual(path.read_bytes(), before)

    def test_missing_explicit_file_is_created_but_invalid_existing_file_is_preserved(self):
        with patch("sys.argv", ["librivox-download", str(self.path)]), \
                patch.object(web, "serve_dashboard") as serve, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(batch.main(), 0)
            self.assertEqual(json.loads(self.path.read_text()), {})
            self.assertFalse(serve.call_args.kwargs["collect"])
            self.path.write_bytes(b"not json")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                batch.main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(self.path.read_bytes(), b"not json")

    def test_dry_run_headless_and_review_do_not_create_session_files(self):
        for option in ("--dry-run", "--headless"):
            for explicit in ([], [str(self.path)]):
                with self.subTest(option=option, explicit=bool(explicit)), contextlib.chdir(self.temp.name), \
                        patch("sys.argv", ["librivox-download", *explicit, option]), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    batch.main()
                self.assertEqual(error.exception.code, 2)
                self.assertFalse(self.path.exists())
                self.assertFalse((Path(self.temp.name) / batch.DEFAULT_SESSION).exists())
        with contextlib.chdir(self.temp.name), patch("sys.argv", ["librivox-download", "--review", self.temp.name]), \
                patch.object(web, "serve_dashboard"):
            self.assertEqual(batch.main(), 0)
        self.assertFalse((Path(self.temp.name) / batch.DEFAULT_SESSION).exists())
