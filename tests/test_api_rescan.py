"""API identity/normalization/fallback and explicit metadata-only rescan regression checks."""
import copy
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

import librivox_api as api
import librivox_launch as batch
import librivox_dashboard as web
import librivox_fetch as app
from test_librivox_fetch import candidate, serving


def book(number=1):
    return {"id": str(100 + number), "title": f"Project {number}",
            "url_librivox": f"https://librivox.org/project-{number}/", "url_text_source": "https://www.gutenberg.org/etext/1941",
            "num_sections": "2", "sections": [
                {"section_number": "2", "title": "Second", "playtime": "700", "listen_url": "https://example.invalid/second_64kb.mp3",
                 "readers": [{"reader_id": "1"}, {"reader_id": "2"}]},
                {"section_number": "1", "title": "First &amp; solo", "playtime": "600", "listen_url": "https://example.invalid/first_64kb.mp3",
                 "readers": [{"reader_id": "1"}]}]}


class ApiTests(unittest.TestCase):
    def test_api_checks_exact_url_and_sorts_sections_without_project_html(self):
        other = book(2)
        with patch.object(app, 'get', return_value=json.dumps({'books': [other, book()]})) as get:
            rows = app.read_project('http://www.librivox.org/project-1/', title='Project 1')
        self.assertEqual(get.call_count, 1)
        self.assertIn('/api/feed/audiobooks/', get.call_args.args[0])
        self.assertEqual([r['title'] for r in rows], ['First & solo', 'Second'])
        self.assertEqual(rows[0]['readers'], ['1'])
        self.assertEqual(rows[0]['seconds'], 600)
        self.assertTrue(rows[0]['url128'].endswith('first_128kb.mp3'))
        self.assertEqual(rows[0]['source']['gutenberg_id'], '1941')
        self.assertEqual(rows[0]['source']['metadata_source'], 'api')

    def test_known_id_avoids_title_lookup_but_still_verifies_url(self):
        with patch.object(app, 'get', return_value=json.dumps({'books': [book()]})) as get:
            app.read_project(book()['url_librivox'], project_id='101', title='Old label')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(get.call_args.args[0]).query)
        self.assertEqual(query['id'], ['101'])
        self.assertNotIn('title', query)
        with self.assertRaises(LookupError):
            api.project(lambda url: json.dumps({'books': [book(2)]}), book()['url_librivox'], '101')

    def test_title_results_paginate_until_exact_recording_url(self):
        calls = []
        def get(url):
            calls.append(url)
            offset = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['offset'][0])
            return json.dumps({'books': [book(2), book(3)] if offset == 0 else [book()]})
        with patch.object(api, 'PAGE_SIZE', 2):
            self.assertEqual(api.project(get, book()['url_librivox'], title='Project 1')['id'], '101')
        self.assertEqual(len(calls), 2)
        self.assertIn('offset=2', calls[1])

    def test_unavailable_or_incomplete_api_falls_back_with_visible_provenance(self):
        page = ('<a href="https://librivox.org/rss/101">RSS</a>'
                '<a href="https://www.gutenberg.org/etext/1941">Online text</a>'
                '<table class="chapter-download"><tr><td>'
                '<a href="https://example.invalid/first_128kb.mp3" class="chapter-name">First</a>'
                '<a href="https://librivox.org/reader/1">Reader</a></td><td>00:10:00</td></tr></table>')
        incomplete = book()
        incomplete['sections'].pop()
        for response in ('not JSON', json.dumps({'books': [incomplete]}), json.dumps({'books': [book(2)]})):
            def get(url):
                return response if '/api/' in url else page
            with self.subTest(response=response), patch.object(app, 'get', side_effect=get):
                rows = app.read_project(book()['url_librivox'], title='Project 1')
            self.assertEqual(rows[0]['source']['metadata_source'], 'html')
            self.assertTrue(rows[0]['source']['api_error'])
            self.assertEqual(rows[0]['readers'], ['1'])

    def test_api_shared_readers_are_not_mistaken_for_solo_sections(self):
        data = book()
        data['sections'][1]['readers'] = [{'reader_id': '1'}, {'reader_id': '2'}]
        args = batch.reader_args({**batch.DEFAULTS, 'name': 'Test', 'url': 'https://librivox.org/reader/1/'})
        with patch.object(app, 'get', return_value=json.dumps({'books': [data]})):
            result, reason = app.check({'url': data['url_librivox'], 'title': 'Project 1'}, '1', args)
        self.assertIsNone(result)
        self.assertIn('no solo sections', reason)

    def test_unknown_api_duration_audio_or_reader_fields_require_fallback(self):
        for key, value in (('playtime', '0'), ('playtime', 'nan'), ('listen_url', 'https://example.invalid/audio.mp3'),
                           ('readers', None)):
            data = book()
            data['sections'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                api.sections(data, app.file_urls)


class RescanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='librivox-rescan-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = {**batch.DEFAULTS, 'download_texts': False, 'count': 1, 'name': 'Test', 'reader_id': '1',
                    'url': 'https://librivox.org/reader/1/', 'out': str(self.root / '1')}
        self.st = app.State(batch.reader_args(self.job), '1', Path(self.job['out']))
        self.c = candidate()
        self.audio = self.st.out / 'old.mp3'
        self.st.out.mkdir()
        self.audio.write_bytes(b'original fixture audio')
        self.c.update(decision='keep', decided_at='original decision', download={
            'status': 'done', 'quality': '128', 'file': 'old.mp3', 'at': 'original download'})
        self.st.candidates = [self.c]
        self.st.checked = {self.c['url']: {'title': 'Project 1', 'type': 'Solo', 'reason': None},
                           candidate(2)['url']: {'title': 'Project 2', 'type': 'Solo', 'reason': 'error: old failure'}}
        self.st.extra['custom_metadata'] = {'retain': True}
        self.st.want_downloads = 1
        self.st.save()
        self.projects = [{'url': candidate(n)['url'], 'title': f'Project {n}', 'type': 'Solo', 'language': 'English'}
                         for n in (1, 2, 3)]

    def api_get(self, url, **kwargs):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        number = int(q['id'][0]) - 100 if 'id' in q else int(q['title'][0].split()[-1])
        return json.dumps({'books': [book(number)]})

    def wait(self, view):
        view.worker.join(5)
        self.assertFalse(view.worker.is_alive())
        self.assertFalse(view.running)

    def test_review_rescan_rechecks_skips_preserves_choice_files_and_custom_metadata(self):
        self.c['url'] = 'http://www.librivox.org/project-1/'
        pending = candidate(2)
        pending.update(custom_note='retain this note', quality='64', missing_128={'why': 'old failure'})
        self.st.candidates.append(pending)
        self.st.save()
        view = web.Dashboard.for_review(self.root)
        before = copy.deepcopy(self.c)
        with patch.object(app, 'listing_pages', return_value=iter([(1, self.projects)])), \
                patch.object(app, 'get', side_effect=self.api_get), patch.object(app, 'download') as audio, \
                patch.object(app.texts, 'fetch_book') as text:
            view.rescan('1')
            self.wait(view)
        audio.assert_not_called()
        text.assert_not_called()
        saved = view.read('1')
        self.assertEqual(len(saved['candidates']), 3)
        self.assertIsNone(saved['checked'][candidate(2)['url']]['reason'])
        c = saved['candidates'][0]
        self.assertEqual(c['url'], before['url'])
        for field in ('section', 'download', 'decision', 'decided_at'):
            self.assertEqual(c[field], before[field])
        self.assertEqual(c['last_scan']['source']['metadata_source'], 'api')
        self.assertEqual(saved['custom_metadata'], {'retain': True})
        self.assertEqual(saved['candidates'][1]['custom_note'], 'retain this note')
        self.assertEqual(saved['candidates'][1]['quality'], '128')
        self.assertNotIn('missing_128', saved['candidates'][1])
        self.assertEqual(self.audio.read_bytes(), b'original fixture audio')
        self.assertEqual(saved['last_rescan']['detail'], 'listing exhausted')

    def test_rescan_is_bounded_by_fresh_checks_even_with_existing_premium_candidates(self):
        self.st.target = 1
        with patch.object(app, 'listing_pages', return_value=iter([(1, self.projects)])), \
                patch.object(app, 'get', side_effect=self.api_get) as get:
            result = app.rescan_reader(self.st, threading.Event())
        self.assertEqual(result['detail'], 'candidate target reached')
        self.assertEqual(get.call_count, 1)
        self.assertFalse(self.st.scan_done)
        self.assertEqual(len(self.st.checked), 1)

    def test_listing_error_is_not_reported_as_exhaustion(self):
        with patch.object(app, 'listing_pages', side_effect=OSError('listing offline')):
            result = app.rescan_reader(self.st, threading.Event())
        self.assertEqual(result['status'], 'scan failed')
        self.assertFalse(self.st.scan_done)
        self.assertTrue(self.audio.exists())

    def test_pause_and_failed_checks_are_visible(self):
        stop = threading.Event()
        def get(url, **kw):
            stop.set()
            return self.api_get(url)
        with patch.object(app, 'listing_pages', return_value=iter([(1, self.projects)])), patch.object(app, 'get', side_effect=get):
            result = app.rescan_reader(self.st, stop)
        self.assertEqual(result['status'], 'scan paused')
        self.assertEqual(len(self.st.checked), 1)
        with patch.object(app, 'listing_pages', return_value=iter([(1, self.projects)])), \
                patch.object(app, 'get', side_effect=OSError('metadata offline')):
            result = app.rescan_reader(self.st, threading.Event())
        self.assertEqual(result['status'], 'scan incomplete')
        self.assertIn('3 project checks failed', result['detail'])

    def test_ineligible_pending_candidate_is_retained_but_not_selected(self):
        pending = candidate(2)
        self.st.candidates.append(pending)
        self.st.want_downloads = 2
        p = {**self.projects[1], 'type': 'Dramatic'}
        with patch.object(app, 'listing_pages', return_value=iter([(1, [p])])):
            app.rescan_reader(self.st, threading.Event())
        self.assertFalse(pending['scan_eligible'])
        self.assertEqual(pending['last_scan']['reason'], 'dramatic reading')
        self.st.enqueue(pending)
        self.assertNotIn(pending['url'], self.st.queue)
        self.assertIsNone(app.next_download(self.st))

    def test_live_decision_during_api_check_survives_rescan_merge(self):
        view = web.Dashboard.for_review(self.root)
        entered, release = threading.Event(), threading.Event()
        def get(url, **kw):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('fixture timed out')
            return self.api_get(url)
        with patch.object(app, 'listing_pages', return_value=iter([(1, self.projects[:1])])), patch.object(app, 'get', side_effect=get):
            view.rescan('1')
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(view.snapshot()['rescanning'])
                view.change('1', self.c['url'], 'decide', 'reject')
            finally:
                release.set()
                self.wait(view)
        self.assertEqual(view.read('1')['candidates'][0]['decision'], 'reject')

    def test_post_rescan_route_and_busy_guard(self):
        view = web.Dashboard.for_review(self.root)
        view.running = True
        with self.assertRaises(ValueError):
            view.rescan()
        view.running = False
        with patch.object(app, 'listing_pages', return_value=iter(())), serving(web.make_handler(view)) as (base, _):
            req = urllib.request.Request(base + '/api/rescan', json.dumps({'reader': '1'}).encode(),
                                         {'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)
            self.wait(view)
        self.assertEqual(view.read('1')['status'], 'rescanned')

    def test_legacy_state_without_selection_requires_configuration_without_writes(self):
        saved = json.loads(self.st.path.read_text())
        saved.pop('selection')
        self.st.path.write_text(json.dumps(saved))
        before = self.st.path.read_bytes()
        view = web.Dashboard.for_review(self.root)
        with patch.object(app, 'get') as get, self.assertRaisesRegex(ValueError, 'saved selection'):
            view.rescan()
        get.assert_not_called()
        self.assertEqual(self.st.path.read_bytes(), before)

    def test_single_reader_rescan_stops_old_workers_and_restarts_only_downloader(self):
        view = web.Dashboard.for_interactive(self.st)
        view.serving = True
        self.st.collecting = False
        starts = []
        restarted = threading.Event()
        def idle_downloader(st):
            starts.append(st)
            if len(starts) == 2:
                restarted.set()
            st.stop.wait(5)
        with patch.object(app, 'listing_pages', return_value=iter(())), patch.object(app, 'downloader', side_effect=idle_downloader):
            try:
                view.ensure_interactive_workers()
                old_download = view.download_thread
                old_scan = view.scan_thread
                view.rescan('1')
                self.wait(view)
                self.assertFalse(old_scan.is_alive())
                self.assertFalse(old_download.is_alive())
                self.assertIsNot(view.download_thread, old_download)
                self.assertTrue(restarted.wait(2))
                self.assertEqual(len(starts), 2)
                self.assertFalse(self.st.collecting)
                self.assertIs(view.scan_thread, old_scan)  # no automatic fresh listing after metadata-only pass
            finally:
                view.closing = True
                self.st.stop.set()
                self.st.wake.set()
                for thread in view.threads:
                    thread.join(5)

    def test_rescan_all_readers_and_selected_reader_scope(self):
        second = {**self.job, 'reader_id': '2', 'name': 'Second', 'out': str(self.root / '2')}
        st2 = app.State(batch.reader_args(second), '2', Path(second['out']))
        st2.save()
        original2 = st2.path.read_bytes()
        view = web.Dashboard.for_review(self.root)
        calls = []
        def listing(rid, order):
            calls.append(rid)
            return iter(())
        with patch.object(app, 'listing_pages', side_effect=listing):
            view.rescan('1')
            self.wait(view)
            self.assertEqual(calls, ['1'])
            self.assertEqual(st2.path.read_bytes(), original2)
            view.rescan()
            self.wait(view)
        self.assertEqual(calls, ['1', '1', '2'])


if __name__ == '__main__':
    unittest.main()
