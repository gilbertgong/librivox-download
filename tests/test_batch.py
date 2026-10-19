"""Batch configuration, lifecycle and local HTTP end-to-end checks. No external requests."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

import librivox_batch as batch
import librivox_fetch as app
from test_librivox_fetch import candidate, serving


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="librivox-batch-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "collection.json"
        self.manifest = {"defaults": {"count": 1, "download_texts": False}, "output_root": "audio",
                         "readers": [{"name": "First reader", "url": "https://librivox.org/reader/1/"},
                                     {"name": "Second reader", "url": "https://librivox.org/reader/2/"}]}

    def jobs(self, manifest=None):
        self.path.write_text(json.dumps(manifest or self.manifest), encoding="utf-8")
        return batch.load_batch(self.path)

    @contextlib.contextmanager
    def catalog(self, fail128=False, fail64=False):
        requests, payload = [], b"local audio payload"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(self.path)
                if self.path.startswith("/reader/"):
                    rid = self.path.strip("/").split("/")[-1]
                    body = f"<title>Works read by Fixture reader {rid} | LibriVox</title>".encode()
                elif self.path.startswith("/listing/"):
                    rid = self.path.rsplit("/", 1)[-1]
                    body = json.dumps({"results": f'<h3><a href="https://librivox.org/book-{rid}/">Book</a>'
                                      '<p class="book-meta">Complete | Collaborative | English</p>',
                                      "pagination": ""}).encode()
                elif self.path.startswith('/api/feed/audiobooks/'):
                    base = f"http://127.0.0.1:{self.server.server_port}"
                    books = [{"id": str(rid), "title": "Book", "url_librivox": f"https://librivox.org/book-{rid}/",
                              "url_text_source": "", "num_sections": "1", "sections": [
                                  {"section_number": "1", "title": "Chapter", "playtime": "600",
                                   "listen_url": f"{base}/audio/{rid}_64kb.mp3", "readers": [{"reader_id": str(rid)}]}]}
                             for rid in (1, 2)]
                    body = json.dumps({"books": books}).encode()
                elif self.path.startswith("/book-"):
                    rid = self.path.strip("/").split("-")[-1]
                    base = f"http://127.0.0.1:{self.server.server_port}"
                    body = ('<table class="chapter-download"><tr><td>'
                            f'<a href="{base}/audio/{rid}_128kb.mp3" class="chapter-name">Chapter</a>'
                            f'<a href="{base}/audio/{rid}_64kb.mp3" class="play-btn">Play</a>'
                            f'<a href="https://librivox.org/reader/{rid}">Reader</a></td>'
                            '<td>00:10:00</td></tr></table>').encode()
                elif self.path.startswith("/audio/"):
                    if (fail128 and self.path.endswith("128kb.mp3")) or (fail64 and self.path.endswith("64kb.mp3")):
                        self.send_error(404)
                        return
                    body = payload
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        original = app.get
        with serving(Handler) as (base, _):
            def local_get(url, **kwargs):
                parsed = urllib.parse.urlsplit(url)
                if "get_results" in parsed.path:
                    target = "/listing/" + urllib.parse.parse_qs(parsed.query)["primary_key"][0]
                else:
                    target = parsed.path + ('?' + parsed.query if parsed.query else '')
                return original(base + target, **kwargs)

            with patch.object(app, "get", side_effect=local_get), patch.object(app, "DELAY", 0):
                yield requests, payload

    def quiet(self):
        return contextlib.redirect_stderr(io.StringIO())

    def test_defaults_overrides_paths_and_stable_ids(self):
        self.manifest["readers"][0].pop("name")
        self.manifest["readers"][1].update(count=3, range_minutes=[3, 12])
        jobs = self.jobs()
        self.assertEqual(jobs[0]["name"], "Reader 1")
        self.assertEqual(jobs[1]["count"], 3)
        self.assertEqual(jobs[0]["range_minutes"], [5, 15])
        self.assertEqual(jobs[1]["range_minutes"], [3, 12])
        self.assertEqual(Path(jobs[0]["out"]), self.root / "audio" / "1")
        self.assertFalse((self.root / "audio").exists())

    def test_ignore_metadata_does_not_change_jobs_or_validate_its_contents(self):
        expected = self.jobs()
        self.manifest['_ignore'] = {'readers': [False, {'url': 'invalid'}]}
        self.manifest['defaults']['_ignore'] = {'count': 0}
        self.manifest['readers'][0]['_ignore'] = ['notes', {'url': 'invalid'}]
        self.manifest['readers'][1]['_ignore'] = None
        self.assertEqual(self.jobs(), expected)
        self.assertFalse((self.root / 'audio').exists())

    def test_invalid_manifests_are_rejected_without_output(self):
        variants = []
        for key, value in (("count", True), ("count", 0), ("count", 1.5), ("range_minutes", [15, 5]),
                           ("timeout_minutes", float("inf")), ("order", "typo"), ("language", 5), ("typo", 1)):
            m = copy.deepcopy(self.manifest)
            m["readers"][1][key] = value
            variants.append(m)
        for url in ("https://example.com/reader/2/", "https://librivox.org/reader/0/", "not a URL"):
            m = copy.deepcopy(self.manifest)
            m["readers"][1]["url"] = url
            variants.append(m)
        duplicate = copy.deepcopy(self.manifest)
        duplicate["readers"][1]["url"] = duplicate["readers"][0]["url"]
        variants.append(duplicate)
        for m in variants:
            with self.subTest(manifest=m), self.assertRaises(ValueError):
                self.jobs(m)
        self.assertFalse((self.root / "audio").exists())

    def test_end_to_end_two_readers_sequential_and_resume_without_network(self):
        self.manifest["readers"][0] = self.manifest["readers"][0]["url"]
        jobs = self.jobs()
        with self.catalog() as (requests, payload), self.quiet():
            summary = batch.run_batch(jobs)
        self.assertEqual([r["status"] for r in summary["results"]], ["completed", "completed"])
        self.assertEqual(summary["results"][0]["name"], "Fixture reader 1")
        self.assertLess(requests.index("/audio/1_128kb.mp3"), requests.index("/listing/2"))
        self.assertTrue(any('/api/feed/audiobooks/' in url for url in requests))
        self.assertFalse(any(url.startswith('/book-') for url in requests))
        for job in jobs:
            state = json.loads((Path(job["out"]) / "state.json").read_text())
            d = state["candidates"][0]["download"]
            self.assertEqual((Path(job["out"]) / d["file"]).read_bytes(), payload)
        with patch.object(app, "listing_pages", side_effect=AssertionError("unexpected network")), \
                patch.object(app, "get", side_effect=AssertionError("unexpected name request")) as fetch, self.quiet():
            resumed = batch.run_batch(jobs)
        fetch.assert_not_called()
        self.assertTrue(all(r["status"] == "completed" for r in resumed["results"]))

    def test_url_shorthand_mixes_with_named_and_count_overrides(self):
        self.manifest["readers"] = ["https://librivox.org/reader/1/",
                                    {"url": "https://librivox.org/reader/2/", "count": 4, "name": "Custom label"}]
        with patch.object(app, "get") as fetch:
            jobs = self.jobs()
        fetch.assert_not_called()
        self.assertEqual([j["name_source"] for j in jobs], ["pending", "explicit"])
        self.assertEqual(jobs[1]["count"], 4)
        self.assertEqual(jobs[1]["name"], "Custom label")

    def test_title_name_decodes_entities_and_preserves_dates_punctuation(self):
        title = '<TITLE> Works read by\n Alice &amp; Bob (1974-2020) | LibriVox </TITLE>'
        with patch.object(app, "get", return_value=title):
            self.assertEqual(batch.reader_name("https://librivox.org/reader/1/"), "Alice & Bob (1974-2020)")

    def test_reader_ids_and_urls_share_normalized_identity_and_overrides(self):
        self.manifest["readers"] = [6281, "000456", {"reader_id": "3", "count": 4},
                                    {"reader_id": 4, "url": "https://librivox.org/reader/004/", "name": "Label"}]
        with patch.object(app, "get") as fetch:
            jobs = self.jobs()
        fetch.assert_not_called()
        self.assertEqual([j["reader_id"] for j in jobs], ["6281", "456", "3", "4"])
        self.assertEqual(jobs[0]["url"], "https://librivox.org/reader/6281/")
        self.assertEqual(jobs[2]["count"], 4)
        self.assertEqual(jobs[3]["name_source"], "explicit")
        self.assertEqual(Path(jobs[1]["out"]).name, "456")

    def test_reader_ids_reject_invalid_values_conflicts_and_cross_format_duplicates(self):
        invalid = [True, 0, -1, 2.5, {"reader_id": False}, {"reader_id": 0}, {"reader_id": -5},
                   {"reader_id": 1.0}, {"reader_id": "1.2"}, {"reader_id": None}, {"reader_id": ""},
                   {"reader_id": "abc"}, {"count": 1},
                   {"reader_id": 1, "url": "https://librivox.org/reader/2/"}]
        for reader in invalid:
            self.manifest["readers"] = [reader]
            with self.subTest(reader=reader), self.assertRaises(ValueError):
                self.jobs()
        for reader in (1, "001", {"reader_id": "1"}):
            self.manifest["readers"] = [reader, "https://librivox.org/reader/1/"]
            with self.subTest(duplicate=reader), self.assertRaisesRegex(ValueError, "duplicate reader ID"):
                self.jobs()

    def test_lookup_failure_keeps_collection_usable_and_retries_name_next_invocation(self):
        self.manifest["readers"] = ["https://librivox.org/reader/1/"]
        job = self.jobs()[0]
        for page in ("<title>Maintenance</title>", "<title>Works read by   | LibriVox</title>"):
            with self.subTest(page=page), patch.object(app, "get", return_value=page), \
                    patch.object(app, "listing_pages", return_value=iter(())), self.quiet():
                result = batch.run_reader(job)
            self.assertEqual(result["status"], "insufficient")
            self.assertEqual(result["name"], "Reader 1")
        saved = json.loads((Path(job["out"]) / "state.json").read_text())
        self.assertEqual(saved["reader_name_source"], "fallback")
        with patch.object(app, "get", return_value="<title>Works read by Recovered Name | LibriVox</title>"), \
                patch.object(app, "listing_pages", return_value=iter(())), self.quiet():
            result = batch.run_reader(job)
        self.assertEqual(result["name"], "Recovered Name")
        self.assertEqual(json.loads((Path(job["out"]) / "state.json").read_text())["reader_name_source"], "page")

    def test_cached_and_explicit_labels_do_not_request_reader_page(self):
        job = {**self.jobs()[0], "name_source": "pending"}
        with patch.object(app, "get") as fetch:
            self.assertEqual(batch.resolve_name(job, {"reader": "Cached name"})[0], "Cached name")
            explicit = {**job, "name_source": "explicit", "name": "Chosen label"}
            self.assertEqual(batch.resolve_name(explicit, {"reader": "Cached name"}), ("Chosen label", "explicit"))
            self.assertEqual(batch.resolve_name(job, {"reader": "Reader 1", "reader_name_source": "page"})[0], "Reader 1")
        fetch.assert_not_called()

    def test_network_failure_falls_back_without_stopping_reader(self):
        self.manifest["readers"] = ["https://librivox.org/reader/1/"]
        job = self.jobs()[0]
        with patch.object(app, "get", side_effect=OSError("offline")), \
                patch.object(app, "listing_pages", return_value=iter(())), self.quiet():
            result = batch.run_reader(job)
        self.assertEqual((result["name"], result["status"]), ("Reader 1", "insufficient"))

    def test_bulk_64_fallback_after_listing_exhaustion(self):
        jobs = self.jobs()
        with self.catalog(fail128=True) as (requests, _), self.quiet():
            result = batch.run_reader(jobs[0])
        self.assertEqual(result["status"], "completed")
        state = json.loads((Path(jobs[0]["out"]) / "state.json").read_text())
        self.assertEqual(state["candidates"][0]["download"]["quality"], "64")
        self.assertEqual(requests.count("/audio/1_64kb.mp3"), 1)

    def test_transfer_failure_is_bounded_and_next_reader_runs(self):
        jobs = self.jobs()
        with self.catalog(fail128=True, fail64=True) as (requests, _), self.quiet():
            results = batch.run_batch(jobs)["results"]
        self.assertEqual([r["status"] for r in results], ["failed", "failed"])
        self.assertEqual(requests.count("/audio/1_64kb.mp3"), 1)
        self.assertEqual(requests.count("/audio/2_64kb.mp3"), 1)

    def test_insufficient_is_distinct_from_remote_failure(self):
        job = self.jobs()[0]
        with patch.object(app, "listing_pages", return_value=iter(())), self.quiet():
            result = batch.run_reader(job)
        self.assertEqual((result["status"], result["downloaded"]), ("insufficient", 0))

    def test_listing_error_does_not_unlock_backups(self):
        job = self.jobs()[0]
        st = app.State(batch.reader_args(job), "1", Path(job["out"]))
        c = candidate()
        c["quality"] = "64"
        st.candidates = [c]
        st.save()
        with patch.object(app, "listing_pages", side_effect=OSError("listing offline")), \
                patch.object(app, "download") as transfer, self.quiet():
            result = batch.run_reader(job)
        self.assertEqual(result["status"], "failed")
        self.assertIn("listing offline", result["detail"])
        transfer.assert_not_called()

    def test_timeout_stops_reader(self):
        job = self.jobs()[0]
        job["timeout_minutes"] = 1
        with patch.object(batch.time, "monotonic", side_effect=[0, 61]), \
                patch.object(app, "listing_pages") as listing, self.quiet():
            result = batch.run_reader(job)
        self.assertEqual(result["status"], "failed")
        self.assertIn("time budget", result["detail"])
        listing.assert_not_called()

    def test_interruption_preserves_intent_skips_remaining_and_can_resume(self):
        jobs = self.jobs()
        with self.catalog(), patch.object(app, "download", side_effect=KeyboardInterrupt), self.quiet():
            results = batch.run_batch(jobs)["results"]
        self.assertEqual([r["status"] for r in results], ["interrupted", "not_run"])
        self.assertFalse(Path(jobs[1]["out"]).exists())
        state = json.loads((Path(jobs[0]["out"]) / "state.json").read_text())
        self.assertEqual(state["candidates"][0]["download"]["status"], "downloading")
        # Saved audio URLs refer to the fixture server that has since stopped; keep transport local and deterministic.
        def transfer(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"resumed")
        with patch.object(app, "download", side_effect=transfer), \
                patch.object(app, "listing_pages", side_effect=AssertionError("unnecessary scan")), self.quiet():
            result = batch.run_reader(jobs[0])
        self.assertEqual(result["status"], "completed")

    def test_incompatible_resume_fails_without_changing_state(self):
        jobs = self.jobs()
        st = app.State(batch.reader_args(jobs[0]), "1", Path(jobs[0]["out"]))
        st.save()
        before = st.path.read_bytes()
        jobs[0]["language"] = "French"
        with self.quiet(), patch.object(app, "listing_pages", return_value=iter(())):
            results = batch.run_batch(jobs)["results"]
        self.assertEqual(results[0]["status"], "failed")
        self.assertIn("selection settings", results[0]["detail"])
        self.assertEqual(results[1]["status"], "insufficient")
        self.assertEqual(st.path.read_bytes(), before)

    def test_cli_dry_run_and_summary_exit_codes(self):
        self.jobs()
        stdout = io.StringIO()
        with patch("sys.argv", ["librivox_batch.py", str(self.path), "--dry-run"]), \
                contextlib.redirect_stdout(stdout):
            self.assertEqual(batch.main(), 0)
        self.assertEqual(len(json.loads(stdout.getvalue())["readers"]), 2)
        self.assertFalse((self.root / "audio").exists())
        for statuses, exit_code in ((["completed", "completed"], 0), (["completed", "insufficient"], 1),
                                    (["failed", "completed"], 1), (["interrupted", "not_run"], 130)):
            with self.subTest(statuses=statuses), patch("sys.argv", ["librivox_batch.py", str(self.path), "--headless"]), \
                    patch.object(batch, "run_batch", return_value={"results": [{"status": s} for s in statuses]}), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(batch.main(), exit_code)
                self.assertIn("results", json.loads(output.getvalue()))

    def test_terminal_progress_reuses_line_and_ends_before_final_status(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        output = Terminal()
        job = {"name": "Reader", "count": 10}
        with contextlib.redirect_stderr(output):
            progress = batch.DownloadProgress()
            progress.update(job, 0)
            progress.update(job, 0)
            progress.update(job, 10)
            progress.update(job, 1)
            progress.finish()
            progress.finish()
            print("Reader: completed", file=output)
        text = output.getvalue()
        self.assertEqual(text.count("\r"), 3)
        self.assertEqual(text.count("0/10 downloaded"), 2)  # 0/10 and 10/10
        self.assertTrue(text.endswith("Reader: 1/10 downloaded \nReader: completed\n"))

    def test_redirected_progress_has_no_controls_or_duplicate_counts(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            progress = batch.DownloadProgress()
            for count in (0, 0, 1, 1, 2):
                progress.update({"name": "Reader", "count": 10}, count)
            progress.finish()
        self.assertNotIn("\r", output.getvalue())
        self.assertEqual(output.getvalue().splitlines(), ["Reader: 0/10 downloaded", "Reader: 1/10 downloaded",
                                                        "Reader: 2/10 downloaded"])


if __name__ == "__main__":
    unittest.main()
