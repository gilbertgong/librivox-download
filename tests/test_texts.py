"""Offline source-text retrieval, provenance, fallback and replacement checks."""
import contextlib
import hashlib
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

import librivox_launch as batch
import librivox_dashboard as dashboard
import librivox_fetch as app
import librivox_text as texts
from test_librivox_fetch import serving


class TextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="librivox-text-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = {**batch.DEFAULTS, "name": "Fixture", "reader_id": "1", "count": 1,
                    "url": "https://librivox.org/reader/1/", "out": str(self.root / "1")}
        self.requests = []
        self.fail = set()
        self.redirect = None
        self.payload = b'The Project Gutenberg eBook of Fixture\r\n\r\nOriginal text.\r\n*** END OF THE PROJECT GUTENBERG EBOOK ***\r\n'

    @contextlib.contextmanager
    def mirror(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                if owner.redirect:
                    self.send_response(302)
                    self.send_header('Location', owner.redirect)
                    self.end_headers()
                    return
                if self.path in owner.fail:
                    self.send_error(404)
                    return
                payload = owner.payload if self.path.endswith('.txt') else b'fixture audio'
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain' if self.path.endswith('.txt') else 'audio/mpeg')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        with serving(Handler) as (base, _), patch.object(texts, 'DELAY', 0):
            self.job['text_mirror'] = base
            yield base

    def source(self, gid='1001'):
        return {'project_id': '101', 'url_text_source': f'https://www.gutenberg.org/etext/{gid}',
                'gutenberg_id': gid, 'gutenberg_url': f'https://www.gutenberg.org/ebooks/{gid}'}

    def projects(self, base, numbers=(1, 2)):
        projects, pages = [], {}
        for n in numbers:
            url = f'https://librivox.org/book-{n}/'
            projects.append({'url': url, 'title': f'Book {n}', 'type': 'Solo', 'language': 'English'})
            pages[url] = (f'<a href="https://librivox.org/rss/{100+n}">RSS</a>'
                          f'<a href="https://www.gutenberg.org/etext/{1000+n}">Online text</a>'
                          '<table class="chapter-download"><tr><td>'
                          f'<a href="{base}/audio/{n}_128kb.mp3" class="chapter-name">Chapter</a>'
                          f'<a href="{base}/audio/{n}_64kb.mp3" class="play-btn">Play</a>'
                          '<a href="https://librivox.org/reader/1">Reader</a></td>'
                          '<td>00:10:00</td></tr></table>')
        return projects, pages

    def run_collection(self, base, numbers=(1, 2)):
        projects, pages = self.projects(base, numbers)
        with patch.object(app, 'get', side_effect=lambda url, **kw: pages[url]), \
                patch.object(app, 'listing_pages', return_value=iter([(1, projects)])), \
                contextlib.redirect_stderr(io.StringIO()):
            return batch.run_reader(self.job)

    def saved(self):
        return json.loads((Path(self.job['out']) / 'state.json').read_text(encoding='utf-8'))

    def test_source_metadata_and_legacy_url_normalization(self):
        source = texts.source_info('<a href="https://librivox.org/rss/52">RSS</a>'
                                   '<a href="https://www.gutenberg.org/etext/1941">Online text</a>')
        self.assertEqual(source['project_id'], '52')
        self.assertEqual(source['gutenberg_id'], '1941')
        for path in ('ebooks/1941', 'ebooks/1941.html.images', 'etext/1941', 'files/1941/1941-0.txt',
                     'cache/epub/1941/pg1941.txt'):
            self.assertEqual(texts.gutenberg_id('https://www.gutenberg.org/' + path), '1941')
        self.assertIsNone(texts.gutenberg_id('https://other.invalid/ebooks/1941'))
        self.assertIsNone(texts.gutenberg_id('https://gutenberg.org/ebooks/0'))

    def test_manifest_defaults_validation_and_audio_only_override(self):
        path = self.root / 'batch.json'
        for defaults, expected in (({}, True), ({'download_texts': False}, False)):
            path.write_text(json.dumps({'readers': [1], 'defaults': defaults}))
            job = batch.load_batch(path)[0]
            self.assertEqual(job['download_texts'], expected)
        for defaults in ({'download_texts': 'true'}, {'text_mirror': 'https://www.gutenberg.org'},
                         {'text_mirror': 'file:///tmp/texts'}):
            path.write_text(json.dumps({'readers': [1], 'defaults': defaults}))
            with self.assertRaises(ValueError):
                batch.load_batch(path)

    def test_mirror_download_preserves_bytes_provenance_and_shared_cache(self):
        with self.mirror() as base:
            first = texts.fetch_book(self.source(), self.root / '1', base)
            second = texts.fetch_book(self.source(), self.root / '2', base)
        self.assertEqual(first['status'], 'done')
        self.assertEqual(first, second)
        self.assertEqual(self.requests, ['/cache/epub/1001/pg1001.txt'])
        file = texts.cache_path(self.root / '1', '1001')
        self.assertEqual(file.read_bytes(), self.payload)
        self.assertEqual(first['sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(json.loads(file.with_name('source.json').read_text())['download_url'],
                         base + '/cache/epub/1001/pg1001.txt')
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_failure_unsupported_and_corrupt_cache_preserve_existing_files(self):
        with self.mirror() as base:
            self.assertEqual(texts.fetch_book({}, self.root / '1', base)['status'], 'missing')
            self.assertEqual(texts.fetch_book({'url_text_source': 'https://other.invalid'}, self.root / '1', base)['status'], 'unsupported')
            self.fail.add('/cache/epub/1001/pg1001.txt')
            self.assertEqual(texts.fetch_book(self.source(), self.root / '1', base)['status'], 'failed')
            self.fail.clear()
            texts.fetch_book(self.source(), self.root / '1', base)
            file = texts.cache_path(self.root / '1', '1001')
            file.write_bytes(b'user-edited text')
            result = texts.fetch_book(self.source(), self.root / '2', base)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(file.read_bytes(), b'user-edited text')

    def test_invalid_mirror_payload_and_main_site_redirect_do_not_create_text(self):
        with self.mirror() as base:
            self.payload = b'<html>Project Gutenberg error page</html>'
            result = texts.fetch_book(self.source(), self.root / '1', base)
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(texts.cache_path(self.root / '1', '1001').exists())
            self.redirect = 'https://www.gutenberg.org/cache/epub/1001/pg1001.txt'
            result = texts.fetch_book(self.source(), self.root / '1', base)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('main Gutenberg', result['reason'])
            self.assertEqual(len(self.requests), 2)  # no follow-up to the forbidden redirect

    def test_missing_text_seeks_premium_before_downloading_backup(self):
        with self.mirror() as base:
            self.fail.add('/cache/epub/1001/pg1001.txt')
            result = self.run_collection(base)
        self.assertEqual((result['status'], result['premium'], result['degraded']), ('completed', 1, 0))
        self.assertNotIn('/audio/1_128kb.mp3', self.requests)
        self.assertIn('/audio/2_128kb.mp3', self.requests)
        saved = self.saved()
        self.assertEqual(saved['candidates'][0]['text']['status'], 'failed')
        self.assertEqual(saved['candidates'][1]['source']['gutenberg_id'], '1002')

    def test_exhaustion_accepts_missing_text_and_retries_on_next_collection(self):
        with self.mirror() as base:
            self.fail.add('/cache/epub/1001/pg1001.txt')
            result = self.run_collection(base, (1,))
            self.assertEqual((result['downloaded'], result['premium'], result['degraded']), (1, 0, 1))
            self.assertIn('degraded', result['detail'])
            before = self.saved()['candidates'][0]['download']
            self.fail.clear()
            self.requests.clear()
            result = self.run_collection(base, (1,))
        self.assertEqual(result['premium'], 1)
        self.assertEqual(self.requests, ['/cache/epub/1001/pg1001.txt'])
        self.assertEqual(self.saved()['candidates'][0]['download'], before)

    def test_existing_degraded_replaced_without_removing_audio_or_decision(self):
        with self.mirror() as base:
            self.fail.add('/cache/epub/1001/pg1001.txt')
            self.run_collection(base, (1,))
            saved = self.saved()
            saved['candidates'][0]['decision'] = 'keep'
            path = Path(self.job['out']) / 'state.json'
            path.write_text(json.dumps(saved), encoding='utf-8')
            original = saved['candidates'][0]['download']
            result = self.run_collection(base)
        self.assertEqual((result['downloaded'], result['premium'], result['degraded']), (2, 1, 1))
        self.assertEqual(self.saved()['candidates'][0]['decision'], 'keep')
        self.assertEqual(self.saved()['candidates'][0]['download'], original)
        self.assertTrue((Path(self.job['out']) / original['file']).exists())

    def test_audio_only_never_fetches_text_or_penalizes_its_absence(self):
        self.job['download_texts'] = False
        with self.mirror() as base:
            result = self.run_collection(base, (1,))
        self.assertEqual(result['premium'], 1)
        self.assertEqual(self.requests, ['/audio/1_128kb.mp3'])
        self.assertEqual(self.saved()['candidates'][0]['source']['gutenberg_id'], '1001')

    def test_legacy_completed_audio_gets_text_without_redownloading_or_changing_decisions(self):
        self.job['download_texts'] = False
        with self.mirror() as base:
            self.run_collection(base, (1,))
            saved = self.saved()
            c = saved['candidates'][0]
            c.pop('source')
            c.pop('text_required')
            c['decision'] = 'keep'
            before = c['download'].copy()
            (Path(self.job['out']) / 'state.json').write_text(json.dumps(saved), encoding='utf-8')
            self.job['download_texts'] = True
            self.requests.clear()
            result = self.run_collection(base, (1,))
        self.assertEqual(result['premium'], 1)
        self.assertEqual(self.requests, ['/cache/epub/1001/pg1001.txt'])
        c = self.saved()['candidates'][0]
        self.assertEqual(c['download'], before)
        self.assertEqual(c['decision'], 'keep')
        self.assertEqual(c['source']['project_id'], '101')

    def test_single_reader_explicit_resume_retries_text_after_exhausted_pass(self):
        with self.mirror() as base:
            self.fail.add('/cache/epub/1001/pg1001.txt')
            self.run_collection(base, (1,))
            st = app.State(batch.reader_args(self.job), '1', Path(self.job['out']))
            st.scan_done = True
            st.text_attempted.add(st.candidates[0]['url'])
            self.assertTrue(st.collection_satisfied())
            st.collecting = False
            view = dashboard.Dashboard.for_interactive(st)
            self.fail.clear()
            self.requests.clear()
            view.start(count=1)
            self.assertFalse(st.collection_satisfied())
            self.assertTrue(app.download_next(st))
            self.assertTrue(st.collection_satisfied())
        self.assertEqual(self.requests, ['/cache/epub/1001/pg1001.txt'])
        self.assertEqual(st.candidates[0]['text']['status'], 'done')

    def test_rejection_during_text_fetch_is_preserved_and_prevents_audio_transfer(self):
        view = dashboard.Dashboard(jobs=[self.job])
        original = texts.fetch_book
        def fetch(source, out, mirror):
            result = original(source, out, mirror)
            if source['gutenberg_id'] == '1001':
                view.change('1', 'https://librivox.org/book-1/', 'decide', 'reject')
            return result
        with self.mirror() as base:
            projects, pages = self.projects(base)
            with patch.object(texts, 'fetch_book', side_effect=fetch), \
                    patch.object(app, 'get', side_effect=lambda url, **kw: pages[url]), \
                    patch.object(app, 'listing_pages', return_value=iter([(1, projects)])), \
                    contextlib.redirect_stderr(io.StringIO()):
                result = batch.run_reader(self.job, on_state=view.register)
        self.assertEqual(result['premium'], 1)
        self.assertEqual(self.saved()['candidates'][0]['decision'], 'reject')
        self.assertNotIn('/audio/1_128kb.mp3', self.requests)

    def test_pause_during_text_fetch_finishes_text_without_starting_audio(self):
        stop = threading.Event()
        original = texts.fetch_book
        def fetch(*args):
            result = original(*args)
            stop.set()
            return result
        with self.mirror() as base:
            projects, pages = self.projects(base, (1,))
            with patch.object(texts, 'fetch_book', side_effect=fetch), \
                    patch.object(app, 'get', side_effect=lambda url, **kw: pages[url]), \
                    patch.object(app, 'listing_pages', return_value=iter([(1, projects)])), \
                    contextlib.redirect_stderr(io.StringIO()):
                result = batch.run_reader(self.job, stop=stop)
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(self.requests, ['/cache/epub/1001/pg1001.txt'])
        self.assertEqual(self.saved()['candidates'][0]['text']['status'], 'done')
        self.assertIsNone(self.saved()['candidates'][0]['download'])

    def test_review_serves_only_derived_cached_text_and_detects_missing_text_read_only(self):
        with self.mirror() as base:
            self.run_collection(base, (1,))
        view = dashboard.Dashboard.for_review(self.root)
        before = (self.root / '1' / 'state.json').read_bytes()
        c = view.snapshot()['readers'][0]['candidates'][0]
        self.assertEqual(c['degraded_reasons'], [])
        with serving(dashboard.make_handler(view)) as (base, _):
            with urllib.request.urlopen(base + c['text_url']) as response:
                self.assertEqual(response.read(), self.payload)
                self.assertEqual(response.headers['Content-Type'], 'text/plain; charset=utf-8')
        file = texts.cache_path(self.root / '1', '1001')
        file.unlink()  # synthetic test fixture only
        c = view.snapshot()['readers'][0]['candidates'][0]
        self.assertIsNone(c['text_url'])
        self.assertIn('missing text', c['degraded_reasons'])
        self.assertEqual((self.root / '1' / 'state.json').read_bytes(), before)
        saved = self.saved()
        saved['candidates'][0]['text']['file'] = '../../private.txt'
        saved['candidates'][0]['source']['gutenberg_id'] = '../../private'
        self.assertIsNone(view.text_path('1', saved['candidates'][0]))


if __name__ == '__main__':
    unittest.main()
