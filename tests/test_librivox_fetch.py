"""Offline regression checks; temporary output only, no LibriVox or Archive requests."""
import contextlib
import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import librivox_fetch as app


@contextlib.contextmanager
def serving(handler):
    with app.LocalServer(("127.0.0.1", 0), handler) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", server
        finally:
            server.shutdown()
            worker.join(timeout=5)


def candidate(number=1):
    return {
        "url": f"https://librivox.org/project-{number}/", "title": f"Project {number}",
        "type": "Collaborative", "sections_total": 2, "solo_sections": 1,
        "section": {"title": "Chapter", "seconds": 600,
                    "url128": "https://example.invalid/chapter_128kb.mp3",
                    "url64": "https://example.invalid/chapter_64kb.mp3"},
        "quality": "128", "in_range": True, "decision": None, "download": None,
    }


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="librivox-test-")
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.args = SimpleNamespace(name="Test reader", url="https://librivox.org/reader/1/",
                                    projects=20, count=10, range=[5, 15])
        self.st = app.State(self.args, "1", self.out)
        self.c = candidate()
        self.st.candidates = [self.c]

    def reload(self):
        return app.State(self.args, "1", self.out)

    def post(self, base, action, **body):
        req = urllib.request.Request(base + "/api/" + action, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def complete(self):
        file = Path("project-1") / "chapter_128kb.mp3"
        (self.out / file).parent.mkdir()
        (self.out / file).write_bytes(b"audio")
        self.c["download"] = {"status": "done", "quality": "128", "file": str(file), "at": "before"}
        return self.out / file

    def test_individual_request_survives_restart_without_bulk_target(self):
        with serving(app.make_handler(self.st)) as (base, _):
            self.post(base, "download", url=self.c["url"])
            self.post(base, "download", url=self.c["url"])
        resumed = self.reload()
        self.assertEqual(resumed.want_downloads, 0)
        self.assertEqual(resumed.queue, [self.c["url"]])
        self.assertEqual(app.next_download(resumed)["url"], self.c["url"])

    def test_legacy_queued_and_inflight_requests_recover(self):
        for status in ("queued", "downloading"):
            with self.subTest(status=status):
                self.c["download"] = {"status": status}
                self.st.save()
                saved = json.loads(self.st.path.read_text(encoding="utf-8"))
                saved.pop("queue")
                self.st.path.write_text(json.dumps(saved), encoding="utf-8")
                resumed = self.reload()
                self.assertEqual(resumed.queue, [self.c["url"]])
                self.assertEqual(resumed.candidates[0]["download"]["status"], "queued")

    def test_inflight_intent_is_saved_before_network_io(self):
        self.st.want_downloads = 1

        def transfer(url, dest):
            resumed = self.reload()
            self.assertEqual(resumed.queue, [])
            self.assertEqual(resumed.want_downloads, 1)
            self.assertEqual(app.next_download(resumed)["url"], self.c["url"])
            dest.parent.mkdir()
            dest.write_bytes(b"audio")

        with patch.object(app, "download", side_effect=transfer):
            self.assertTrue(app.download_next(self.st))
        self.assertEqual(self.st.downloaded(), 1)
        self.assertFalse(app.download_next(self.st))

    def test_missing_file_is_visible_and_bulk_can_restore_it(self):
        file = self.complete()
        self.c["decision"] = "keep"
        self.st.want_downloads = 1
        self.st.save()
        file.unlink()
        resumed = self.reload()
        d = resumed.candidates[0]["download"]
        self.assertEqual(d["status"], "missing")
        self.assertEqual(d["at"], "before")
        self.assertEqual(resumed.candidates[0]["decision"], "keep")
        self.assertEqual(resumed.downloaded(), 0)
        self.assertIsNotNone(app.next_download(resumed))

    def test_removing_file_during_session_clears_completion_banner(self):
        file = self.complete()
        self.st.want_downloads = 1
        self.st.save()
        self.assertEqual(json.loads(self.st.snapshot())["downloaded"], 1)
        file.unlink()
        view = json.loads(self.st.snapshot())
        self.assertEqual(view["downloaded"], 0)
        self.assertEqual(view["candidates"][0]["download"]["status"], "missing")
        self.assertEqual(self.reload().candidates[0]["download"]["status"], "missing")

    def test_individual_128_failure_downloads_64_without_second_click(self):
        payload = b"local fixture audio"
        requests = []

        class AudioHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(self.path)
                if self.path.endswith("128kb.mp3"):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with serving(AudioHandler) as (base, _):
            self.c["section"].update(url128=base + "/chapter_128kb.mp3", url64=base + "/chapter_64kb.mp3")
            self.st.enqueue(self.c)
            self.assertTrue(app.download_next(self.st))
            resumed = self.reload()  # restart between the failed 128 and its fallback
            self.assertTrue(app.download_next(resumed))
            self.assertFalse(app.download_next(resumed))
        self.assertEqual(requests, ["/chapter_128kb.mp3", "/chapter_64kb.mp3"])
        d = resumed.candidates[0]["download"]
        self.assertEqual((self.out / d["file"]).read_bytes(), payload)
        self.assertEqual(d["quality"], "64")
        self.assertEqual(resumed.queue, [])
        self.assertFalse(list(self.out.rglob("*.part")))

    def test_bulk_fallback_waits_for_exhaustion_and_preserves_prime_priority(self):
        self.st.want_downloads = 1
        with patch.object(app, "download", side_effect=OSError("temporary failure")):
            app.download_next(self.st)
        self.assertIsNone(app.next_download(self.st))
        second = candidate(2)
        self.st.candidates.append(second)
        self.assertIs(app.next_download(self.st), second)
        second["decision"] = "reject"
        self.st.scan_done = True
        self.assertIs(app.next_download(self.st), self.c)

    def test_failed_64_attempt_stops_instead_of_retrying_forever(self):
        self.c["quality"] = "64"
        self.st.enqueue(self.c)
        with patch.object(app, "download", side_effect=OSError("offline")):
            app.download_next(self.st)
        self.assertEqual(self.c["download"]["status"], "failed")
        self.assertEqual(self.st.queue, [])
        self.assertFalse(app.download_next(self.st))

    def test_interrupted_bulk_transfer_keeps_bulk_fallback_rules_after_restart(self):
        self.st.want_downloads = 1
        self.c["download"] = {"status": "downloading", "individual": False}
        self.st.candidates.append(candidate(2))
        self.st.save()
        resumed = self.reload()
        with patch.object(app, "download", side_effect=OSError("128 transfer failed")):
            app.download_next(resumed)
        self.assertEqual(resumed.queue, [])
        self.assertEqual(resumed.candidates[0]["quality"], "64")
        self.assertEqual(app.next_download(resumed)["url"], resumed.candidates[1]["url"])

    def test_reject_cancels_queued_request_without_deleting_existing_audio(self):
        file = self.complete()
        self.c["download"] = None
        with serving(app.make_handler(self.st)) as (base, _):
            self.post(base, "download", url=self.c["url"])
            self.post(base, "decide", url=self.c["url"], decision="reject")
        self.assertIsNone(app.next_download(self.st))
        self.assertEqual(self.reload().queue, [])
        self.assertTrue(file.is_file())

    def test_playback_fallback_can_be_reversed_without_losing_decision_or_64_file(self):
        self.c["decision"] = "keep"
        with serving(app.make_handler(self.st)) as (base, _):
            self.post(base, "missing_128", url=self.c["url"])
            self.assertEqual(self.c["quality"], "64")
            file = self.complete()
            self.c["download"]["quality"] = "64"
            before = copy.deepcopy(self.c["download"])
            self.post(base, "retry_128", url=self.c["url"])
            self.assertEqual(self.c["quality"], "128")
            self.assertNotIn("missing_128", self.c)
            self.assertEqual(self.c["decision"], "keep")
            self.assertEqual(self.c["download"], before)
            self.assertTrue(file.is_file())
            self.post(base, "download", url=self.c["url"])
            self.assertEqual(self.reload().queue, [self.c["url"]])

    def test_quality_change_during_transfer_does_not_mislabel_saved_audio(self):
        self.st.enqueue(self.c)

        def transfer(url, dest):
            self.st.mark_128_missing(self.c, "player error during transfer")
            dest.parent.mkdir()
            dest.write_bytes(b"128 audio")

        with patch.object(app, "download", side_effect=transfer):
            app.download_next(self.st)
        self.assertEqual(self.c["download"]["quality"], "128")
        self.assertEqual(self.c["quality"], "128")
        self.assertNotIn("missing_128", self.c)

    def test_occupied_port_is_rejected(self):
        with app.LocalServer(("127.0.0.1", 0), app.make_handler(self.st)) as first:
            with self.assertRaises(OSError):
                app.LocalServer(first.server_address, app.make_handler(self.st))

    def test_reject_during_failed_transfer_cancels_fallback(self):
        self.st.enqueue(self.c)

        def transfer(url, dest):
            self.c["decision"] = "reject"
            self.st.queue.remove(self.c["url"])
            raise OSError("transfer failed after rejection")

        with patch.object(app, "download", side_effect=transfer):
            app.download_next(self.st)
        self.assertEqual(self.c["download"]["status"], "failed")
        self.assertEqual(self.st.queue, [])
        self.assertFalse(app.download_next(self.st))

    def test_keep_is_annotation_and_rejected_downloads_do_not_count(self):
        self.st.want_downloads = 1
        self.assertIs(app.next_download(self.st), self.c)  # no Keep needed
        self.complete()
        self.c["decision"] = "reject"
        self.assertEqual(self.st.downloaded(), 0)
        self.assertTrue((self.out / self.c["download"]["file"]).is_file())


if __name__ == "__main__":
    unittest.main()
