"""Whole-project discovery/collection uses isolated state, no sampling restrictions or external requests."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import librivox_dashboard as web
import librivox_fetch as app
import librivox_launch as launch
import librivox_projects as projects
from test_librivox_fetch import serving
from test_api_rescan import book


def seed(number=1, kind="Collaborative"):
    return {"url": f"https://librivox.org/project-{number}/", "title": f"Project {number}",
            "type": kind, "language": "French"}


def metadata(item):
    rows = [{"title": f"Section {n}", "readers": readers, "seconds": 15,
             "url128": f"https://example.invalid/chapter{n}_128kb.mp3",
             "url64": f"https://example.invalid/chapter{n}_64kb.mp3"} for n, readers in enumerate((["1"], ["1", "2"], ["2"]), 1)]
    return {**seed(), **item, "authors": ["Test Author"], "reader_names": {"1": "First", "2": "Second"},
            "sections": rows, "source": {}, "metadata_status": "ready"}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="librivox-projects-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = projects.Library(self.root)
        self.stop = threading.Event()

    def populate(self, number=1):
        with patch.object(projects, "details", side_effect=metadata):
            self.library.inspect(seed(number), reader="1", include=True)
        return projects.identity(seed(number)["url"])

    def transfer(self, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(url.encode())

    def dashboard(self):
        manifest = self.root / "session.json"
        manifest.write_text(json.dumps({"auto_collect": False, "defaults": {"download_texts": False}}))
        return web.Dashboard(launch.load_batch(manifest), manifest=manifest)

    def test_extended_metadata_preserves_all_sections_and_shared_cast(self):
        data = book()
        data.update(authors=[{"first_name": "Test", "last_name": "Author"}], language="French",
                    genres=[{"name": "Dramatic Readings"}])
        data["sections"][1]["playtime"] = "15"
        data["sections"][1]["readers"][0]["display_name"] = "First &amp; Reader"
        with patch.object(app, "get", return_value=json.dumps({"books": [data]})) as get:
            result = projects.details(seed())
        self.assertEqual(result["type"], "Dramatic")
        self.assertEqual(result["authors"], ["Test Author"])
        self.assertEqual(result["sections"][0]["seconds"], 15)
        self.assertEqual(result["sections"][1]["readers"], ["1", "2"])
        self.assertEqual(result["reader_names"]["1"], "First & Reader")
        self.assertIn("authors", get.call_args.args[0])

    def test_direct_url_resolves_id_and_html_fallback_preserves_source(self):
        page = '<title>Fixture | LibriVox</title><a href="https://librivox.org/rss/101">RSS</a>'
        def get(url):
            if "/api/" in url:
                return json.dumps({"books": [book()]})
            return page
        with patch.object(app, "get", side_effect=get) as requests:
            result = projects.details({"url": seed()["url"]})
        self.assertEqual(result["title"], book()["title"])
        self.assertEqual(requests.call_count, 2)
        with patch.object(app, "get", return_value=page), patch.object(app.api, "project", side_effect=OSError("offline")), \
                patch.object(app, "read_project_html", return_value=[{**metadata(seed())["sections"][0], "source": {}}]):
            result = projects.details({"url": seed()["url"]})
        self.assertEqual(result["title"], "Fixture")
        self.assertEqual(result["source"]["metadata_source"], "html")

    def test_full_listing_has_no_sampling_limit_and_dramatic_is_opt_in(self):
        items = [seed(n) for n in range(1, 23)] + [seed(23, "Dramatic")]
        with patch.object(app, "listing_pages", return_value=iter([(1, items)])), \
                patch.object(projects, "details", side_effect=metadata) as details, patch.object(app, "download") as download:
            self.library.scan("1", self.stop)
            self.assertEqual(details.call_count, 22)
            download.assert_not_called()
        self.assertEqual(len(self.library.data["projects"]), 23)
        self.assertEqual(self.library.data["scans"]["1"]["status"], "complete")
        key = projects.identity(items[-1]["url"])
        self.assertEqual(self.library.data["projects"][key]["metadata_status"], "excluded")
        with patch.object(app, "listing_pages", return_value=iter([(1, items)])), \
                patch.object(projects, "details", side_effect=metadata) as details:
            self.library.scan("1", self.stop, include=True)
            self.assertEqual(details.call_count, 1)
        self.assertEqual(len(self.library.data["projects"][key]["sections"]), 3)

    def test_pause_resume_reuses_cached_projects_and_deduplicates_readers(self):
        def inspect(item):
            self.stop.set()
            return metadata(item)
        with patch.object(app, "listing_pages", return_value=iter([(1, [seed(), seed(2)])])), \
                patch.object(projects, "details", side_effect=inspect):
            self.library.scan("1", self.stop)
        self.assertEqual(self.library.data["scans"]["1"]["status"], "paused")
        self.stop.clear()
        with patch.object(app, "listing_pages", return_value=iter([(1, [seed(), seed(2)])])), \
                patch.object(projects, "details", side_effect=metadata) as inspect:
            self.library.scan("2", self.stop)
            self.assertEqual(inspect.call_count, 1)
        self.assertEqual(self.library.data["projects"][projects.identity(seed()["url"])]["discovered_readers"], ["1", "2"])

    def test_failures_and_listing_errors_do_not_claim_completion(self):
        with patch.object(app, "listing_pages", return_value=iter([(1, [seed()])])), \
                patch.object(projects, "details", side_effect=OSError("metadata failed")):
            self.library.scan("1", self.stop)
        self.assertEqual(self.library.data["scans"]["1"]["status"], "scan incomplete")
        with patch.object(app, "listing_pages", side_effect=OSError("listing failed")):
            self.library.scan("1", self.stop)
        self.assertEqual(self.library.data["scans"]["1"]["status"], "scan failed")
        with patch.object(projects, "details", side_effect=metadata):
            self.library.inspect(seed(), "1")
        self.assertFalse(next(iter(self.library.data["projects"].values())).get("error"))

    def test_reader_scope_includes_shared_sections_then_full_project_resumes(self):
        key = self.populate()
        with patch.object(app, "download", side_effect=self.transfer) as transfer:
            self.library.download(key, "1", self.stop, download_texts=False)
            self.assertEqual(transfer.call_count, 2)
            self.library.download(key, None, self.stop, download_texts=False)
            self.assertEqual(transfer.call_count, 3)
            self.library.download(key, None, self.stop, download_texts=False)
            self.assertEqual(transfer.call_count, 3)
        self.assertEqual(self.library.snapshot()["projects"][key]["downloaded"], 3)
        self.assertEqual(projects.Library(self.root).snapshot()["projects"][key]["downloaded"], 3)

    def test_fallback_failed_retry_and_missing_file_recovery(self):
        key = self.populate()
        def fallback(url, dest):
            if "128kb" in url:
                raise OSError("128 unavailable")
            self.transfer(url, dest)
        with patch.object(app, "download", side_effect=fallback):
            self.library.download(key, None, self.stop, download_texts=False)
        self.assertTrue(all(s["download"]["quality"] == "64" for s in self.library.data["projects"][key]["sections"]))
        first = self.library.file(key, 1)
        first.unlink()
        self.assertEqual(self.library.snapshot()["projects"][key]["sections"][0]["status"], "missing")
        with patch.object(app, "download", side_effect=OSError("both failed")):
            self.library.download(key, None, self.stop, download_texts=False)
        self.assertEqual(self.library.data["projects"][key]["download_request"]["status"], "incomplete")
        with patch.object(app, "download", side_effect=self.transfer) as transfer:
            self.library.download(key, None, self.stop, download_texts=False)
            self.assertEqual(transfer.call_count, 1)
        self.assertEqual(self.library.snapshot()["projects"][key]["downloaded"], 3)

    def test_pause_preserves_completed_files_and_resumes_without_retransfer(self):
        key = self.populate()
        def transfer(url, dest):
            self.transfer(url, dest)
            self.stop.set()
        with patch.object(app, "download", side_effect=transfer):
            self.library.download(key, None, self.stop, download_texts=False)
        self.assertEqual(self.library.data["projects"][key]["download_request"]["status"], "paused")
        self.stop.clear()
        with patch.object(app, "download", side_effect=self.transfer) as transfer:
            self.library.download(key, None, self.stop, download_texts=False)
            self.assertEqual(transfer.call_count, 2)

    def test_text_is_shared_and_missing_text_does_not_block_project(self):
        key = self.populate()
        with patch.object(app.texts, "fetch_book", return_value={"status": "missing"}) as text, \
                patch.object(app, "download", side_effect=self.transfer):
            self.library.download(key, None, self.stop)
        self.assertEqual(text.call_args.args[1], self.library.root)
        self.assertEqual(self.library.data["projects"][key]["download_request"]["status"], "complete")

    def test_refresh_does_not_lose_completed_downloads(self):
        key = self.populate()
        with patch.object(app, "download", side_effect=self.transfer):
            self.library.download(key, None, self.stop, download_texts=False)
        files = [s["download"] for s in self.library.data["projects"][key]["sections"]]
        with patch.object(projects, "details", side_effect=metadata):
            self.library.inspect(seed(), include=True, refresh=True)
        self.assertEqual([s["download"] for s in self.library.data["projects"][key]["sections"]], files)
        def revised(item):
            result = metadata(item)
            result["sections"][0]["url128"] = "https://example.invalid/revised_128kb.mp3"
            return result
        with patch.object(projects, "details", side_effect=revised):
            self.library.inspect(seed(), include=True, refresh=True)
        project = self.library.data["projects"][key]
        self.assertIn("chapter1_128kb", project["sections"][0]["url128"])
        self.assertIn("revised_128kb", project["last_scan"]["sections"][0]["url128"])
        with patch.object(app, "download") as transfer:
            self.library.download(key, None, self.stop, download_texts=False)
            transfer.assert_not_called()

    def test_interrupted_requests_are_visible_after_reopen_without_writing(self):
        key = self.populate()
        project = self.library.data["projects"][key]
        project["download_request"] = {"status": "downloading", "reader": None, "sections": [1, 2, 3]}
        project["sections"][0]["download"] = {"status": "downloading", "file": f"{key}/0001_128kb.mp3"}
        self.library.data["scans"]["1"] = {"status": "scanning"}
        self.library.save()
        before = self.library.path.read_bytes()
        snapshot = projects.Library(self.root).snapshot()
        self.assertEqual(snapshot["projects"][key]["download_request"]["status"], "interrupted")
        self.assertEqual(snapshot["projects"][key]["sections"][0]["status"], "interrupted")
        self.assertEqual(snapshot["scans"]["1"]["status"], "interrupted")
        self.assertEqual(self.library.path.read_bytes(), before)

    def test_project_text_uses_shared_cache_and_cannot_serve_arbitrary_paths(self):
        key = self.populate()
        project = self.library.data["projects"][key]
        project["source"] = {"gutenberg_id": "1941"}
        project["text"] = {"status": "done", "file": "../private.txt"}
        self.assertIsNone(self.library.text_file(key))
        path = self.root / "texts" / "gutenberg" / "1941" / "source.txt"
        path.parent.mkdir(parents=True)
        path.write_text("fixture book")
        self.assertEqual(self.library.text_file(key), path)
        dashboard = web.Dashboard(project_root=self.root)
        self.library.save()
        dashboard.projects = projects.Library(self.root)
        with serving(web.make_handler(dashboard)) as (base, _):
            with urllib.request.urlopen(base + f"/project-text?project={key}", timeout=5) as response:
                self.assertEqual(response.read(), b"fixture book")

    def test_invalid_urls_media_containment_and_section_bounds(self):
        for url in ("https://example.invalid/book/", "file:///book", "https://librivox.org/reader/1/", "https://librivox.org/a/../b/", None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                projects.project_url(url)
        key = self.populate()
        with self.assertRaises(ValueError):
            self.library.file(key, 0)
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"private")
        self.library.data["projects"][key]["sections"][0]["download"] = {"status": "done", "file": "../outside.mp3"}
        self.assertIsNone(self.library.file(key, 1))

    def test_dashboard_busy_guard_sampling_isolation_and_review_only(self):
        dashboard = self.dashboard()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def listing(*args):
            entered.set()
            release.wait(5)
            return iter([(1, [seed()])])
        with patch.object(app, "listing_pages", side_effect=listing), patch.object(projects, "details", side_effect=metadata):
            dashboard.project_action("project_scan", {"value": "https://librivox.org/reader/1/"})
            self.assertTrue(entered.wait(2))
            with self.assertRaises(ValueError):
                dashboard.start()
            with self.assertRaises(ValueError):
                dashboard.project_action("project_open", {"url": seed()["url"]})
            dashboard.pause()
            release.set()
            dashboard.worker.join(5)
        self.assertFalse(dashboard.jobs)
        self.assertFalse(dashboard.paths)
        review = web.Dashboard.for_review(self.root / "downloads")
        before = review.projects.path.read_bytes()
        with self.assertRaises(ValueError):
            review.project_action("project_scan", {"value": "1"})
        self.assertEqual(review.projects.path.read_bytes(), before)

    def test_http_project_routes_download_and_range_playback(self):
        dashboard = self.dashboard()
        def post(base, action, body):
            req = urllib.request.Request(base + "/api/" + action, json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as response:
                self.assertEqual(response.status, 200)
        with serving(web.make_handler(dashboard)) as (base, _), patch.object(projects, "details", side_effect=metadata):
            post(base, "project_open", {"url": seed()["url"]})
            dashboard.worker.join(5)
            key = projects.identity(seed()["url"])
            with patch.object(app, "download", side_effect=self.transfer):
                post(base, "project_download", {"project": key, "reader": "1"})
                dashboard.worker.join(5)
            with urllib.request.urlopen(base + "/api/projects", timeout=5) as response:
                data = json.load(response)
            self.assertEqual(data["projects"][key]["downloaded"], 2)
            media = data["projects"][key]["sections"][0]["audio_url"]
            with urllib.request.urlopen(urllib.request.Request(base + media, headers={"Range": "bytes=0-3"}), timeout=5) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 4)
            with urllib.request.urlopen(base + "/projects", timeout=5) as response:
                self.assertIn(b"Include dramatic readings", response.read())
