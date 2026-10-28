"""Mountable microweb adapter for the downloader's existing collection controller."""
import html
import json
from pathlib import Path

from microweb import App, Component, HTTPError, Response, file_response


def _links(value, prefix):
    """Qualify only public local media links, without changing saved state."""
    if isinstance(value, dict):
        return {key: prefix + item if key in ('audio_url', 'text_url') and isinstance(item, str)
                and item.startswith('/') and not item.startswith('//') else _links(item, prefix)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_links(item, prefix) for item in value]
    return value


def create_app(dashboard, sessions=None):
    """Build routes without starting workers. dashboard may be a deferred getter."""
    web = App()
    def controller():
        current = dashboard() if callable(dashboard) else dashboard
        if current is None:
            raise HTTPError(503, 'downloader component has not started')
        return current
    def response(body, content_type=None):
        return Response(body, content_type=content_type, headers={'Cache-Control': 'no-store'})

    @web.route('/', ['GET'])
    @web.route('/review', ['GET'])
    @web.route('/projects', ['GET'])
    def page(req):
        content = Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
        base = html.escape(req.url(), quote=True)
        return response(content.replace('<meta charset="utf-8">',
                                        f'<meta charset="utf-8"><base href="{base}">', 1),
                        'text/html; charset=utf-8')

    @web.get('/api/dashboard')
    def snapshot(req):
        if sessions is None:
            data = controller().snapshot()
        else:
            with sessions.lock:
                data = controller().snapshot()
                data['session'] = sessions.snapshot()
        return response(_links(data, req.root_path))

    @web.get('/api/projects')
    def projects(req):
        view = controller()
        data = view.projects.snapshot(active=view.project_running) if view.projects else {'projects': {}, 'scans': {}}
        return response(_links(data, req.root_path))

    @web.get('/api/state')
    def state(req):
        view = controller()
        if not view.interactive:
            raise HTTPError(404, 'not found')
        return response(view.interactive.snapshot())

    @web.route('/media', ['GET'])
    @web.route('/text', ['GET'])
    @web.route('/project-media', ['GET'])
    @web.route('/project-text', ['GET'])
    def media(req):
        view = controller()
        try:
            if req.path.startswith('/project-'):
                key = req.query['project']
                path = (view.projects.text_file(key) if req.path == '/project-text'
                        else view.projects.file(key, int(req.query['section'])))
            else:
                rid, url = req.query['reader'], req.query['url']
                candidate = next(c for c in view.read(rid)['candidates'] if c['url'] == url)
                path = view.text_path(rid, candidate) if req.path == '/text' else view.audio_path(rid, candidate)
            if path is None:
                raise ValueError('file not present')
            if req.path.endswith('text'):
                return response(path.read_bytes(), 'text/plain; charset=utf-8')
            return file_response(req, path)
        except (OSError, ValueError, KeyError, IndexError, AttributeError, StopIteration):
            raise HTTPError(404, 'file not found') from None

    def apply_mutation(req):
        view = controller()
        try:
            body = json.loads(req.body() or b'{}')
            if not isinstance(body, dict):
                raise ValueError('expected a JSON object')
            action = req.path.removeprefix('/api/')
            if action in ('start', 'download_n'):
                view.start(body.get('reader'), body.get('n'))
            elif action in ('project_scan', 'project_open', 'project_download', 'project_options'):
                view.project_action(action, body)
            elif action == 'pause':
                view.pause()
            elif action == 'rescan':
                view.rescan(body.get('reader'))
            elif action == 'add_reader':
                view.add_reader(body.get('value'), body.get('n', 10))
            elif action == 'scan_more' and not view.interactive:
                view.scan_more(body.get('reader'), body.get('n', 10))
            elif action == 'scan_more':
                if view.rescanning:
                    raise ValueError('wait for the metadata rescan to finish')
                with view.interactive.lock:
                    view.interactive.target += max(0, int(body.get('n', 10)))
                    view.interactive.save()
                view.interactive.wake.set()
                view.ensure_interactive_workers()
            else:
                view.change(body.get('reader'), body.get('url'), action, body.get('decision'))
            return response({})
        except (ValueError, TypeError, KeyError, OSError) as error:
            raise HTTPError(400, str(error)) from None

    def mutate(req):
        if sessions is None:
            return apply_mutation(req)
        with sessions.lock:
            body = req.json()
            if not isinstance(body, dict):
                raise HTTPError(400, 'expected a JSON object')
            if body.get('session_generation', sessions.generation) != sessions.generation:
                raise HTTPError(409, 'session changed; refresh before trying again')
            if req.path in ('/api/session_open', '/api/session_new'):
                try:
                    sessions.open(body.get('file'), create=req.path.endswith('session_new'))
                    return response({'opening': True})
                except (ValueError, TypeError, KeyError, OSError, AttributeError) as error:
                    raise HTTPError(400, str(error)) from None
            if sessions.switching or sessions.closing:
                raise HTTPError(409, 'opening a session; wait for the current operation to finish')
            return apply_mutation(req)

    for action in ('start', 'download_n', 'project_scan', 'project_open', 'project_download', 'project_options',
                   'session_open', 'session_new', 'pause', 'rescan', 'add_reader', 'scan_more', 'decide', 'download', 'retry_128', 'missing_128'):
        web.post('/api/' + action)(mutate)
    return web


def _component(build, collect=None, browse=False, directory=None, sessions_enabled=True):
    from .sessions import Sessions
    host = [None]
    def controller():
        return host[0].current if host[0] else None
    class SessionProxy:
        def __getattr__(self, name):
            if host[0] is None:
                raise HTTPError(503, 'downloader component has not started')
            return getattr(host[0], name)
    def start():
        view = build()
        host[0] = Sessions(view, directory or Path.cwd(), enabled=sessions_enabled)
        view.serving = True
        if view.interactive:
            view.ensure_interactive_workers()
        elif collect is True or (collect is None and view.jobs and view.manifest_data.get('auto_collect', True)):
            view.start()
        elif browse:
            view.rescan()
    def stop():
        if host[0]:
            host[0].stop()
    return Component('downloads', 'Downloads', create_app(controller, SessionProxy()), start, stop)


def dashboard_component(dashboard, collect=False, browse=False):
    """Wrap an existing controller, as used by the established standalone CLI."""
    return _component(lambda: dashboard, collect, browse,
                      sessions_enabled=not dashboard.review_only and not dashboard.interactive
                      and (bool(dashboard.manifest) or not dashboard.paths))


def create_component(settings):
    """Quiet factory. Resolve relative paths against explicit settings_dir.

    Provide session_file OR review_root. Session creation/loading and controller
    initialization happen only after the host binds. collect=False disables startup
    collection; omitted collect follows the session's existing auto_collect setting.
    """
    from .dashboard import Dashboard
    from . import launch as launch
    if 'session_file' not in settings and 'review_root' not in settings:
        base = Path(settings.get('settings_dir', Path.cwd())).expanduser()
        if not base.is_absolute():
            raise ValueError('settings_dir must be absolute')
        base = base.resolve()
        return _component(Dashboard, collect=False, directory=base)
    key = 'session_file' if 'session_file' in settings else 'review_root'
    if ('session_file' in settings) == ('review_root' in settings):
        raise ValueError('provide session_file or review_root')
    path = Path(settings[key]).expanduser()
    if not path.is_absolute():
        if 'settings_dir' not in settings:
            raise ValueError('relative paths require settings_dir')
        base = Path(settings['settings_dir']).expanduser()
        if not base.is_absolute():
            raise ValueError('settings_dir must be absolute')
        path = base / path
    path = path.resolve()
    def build():
        if key == 'review_root':
            return Dashboard.for_review(path)
        try:
            with path.open('x', encoding='utf-8', newline='\n') as session:
                session.write('{}\n')
        except FileExistsError:
            pass
        jobs = launch.load_batch(path)
        return Dashboard(jobs=jobs, manifest=path)
    return _component(build, settings.get('collect', False if key == 'review_root' else None),
                      directory=settings.get('settings_dir', Path.cwd()), sessions_enabled=key != 'review_root')
