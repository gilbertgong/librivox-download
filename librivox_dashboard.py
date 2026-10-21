"""Collection, sampling review and project library dashboard, backed by local JSON state."""
import copy
import json
import mimetypes
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace

import librivox_fetch as app
import librivox_projects as projects

CLIENT_DISCONNECTS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class Dashboard:
    def __init__(self, jobs=(), paths=None, interactive=None, manifest=None, project_root=None):
        self.manifest = Path(manifest).resolve() if manifest else None
        self.manifest_data = json.loads(self.manifest.read_text(encoding="utf-8")) if manifest else None
        self.jobs = {job["reader_id"]: job for job in jobs}
        if self.manifest:
            project_root = (self.manifest.parent / self.manifest_data.get("output_root", "downloads")).resolve()
        elif self.jobs:
            project_root = Path(next(iter(self.jobs.values()))["out"]).parent
        self.projects = projects.Library(project_root) if project_root is not None else None
        self.paths = {rid: Path(job["out"]) / "state.json" for rid, job in self.jobs.items()}
        self.paths.update(paths or {})
        self.states = {}
        self.results = {}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.worker = None
        self.running = False
        self.project_running = False
        self.rescanning = False
        self.serving = False
        self.closing = False
        self.scan_thread = None
        self.download_thread = None
        self.interactive = interactive
        self.threads = []
        if interactive:
            self.states[interactive.rid] = interactive
            self.paths[interactive.rid] = interactive.path

    @classmethod
    def for_interactive(cls, state):
        return cls(interactive=state)

    @classmethod
    def for_review(cls, root):
        root = Path(root).resolve()
        if not root.exists():
            raise ValueError(f"review path does not exist: {root}")
        files = ([root] if root.is_file() else
                 ([root / "state.json"] if (root / "state.json").is_file() else sorted(root.glob("*/state.json"))))
        paths = {}
        for path in files:
            saved = json.loads(path.read_text(encoding="utf-8"))
            rid = str(saved.get("reader_id", ""))
            if not re.fullmatch(r"[0-9]+", rid) or not isinstance(saved.get("candidates"), list):
                raise ValueError(f"invalid reader state: {path}")
            if rid in paths:
                raise ValueError(f"duplicate reader {rid}; open its reader directory separately")
            paths[rid] = path
        project_root = root.parent.parent if root.is_file() else root.parent if (root / "state.json").is_file() else root
        return cls(paths=paths, project_root=project_root)

    def read(self, rid):
        with self.lock:
            state, path, job = self.states.get(rid), self.paths.get(rid), self.jobs.get(rid)
        if path is None:
            raise ValueError("unknown reader")
        if state:
            with state.lock:
                return copy.deepcopy(state.record())
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"reader_id": rid, "reader": job["name"], "reader_url": job["url"], "candidates": [],
                "checked": {}, "want_downloads": job["count"], "status": "not started"}

    def audio_path(self, rid, c):
        d = c.get("download") or {}
        if not d.get("file"):
            return None
        root = self.paths[rid].parent.resolve()
        path = (root / str(d["file"]).replace("\\", "/")).resolve()
        if not path.is_relative_to(root):
            return None
        return path if path.is_file() else None

    def text_path(self, rid, c):
        path = app.texts.text_present(self.paths[rid].parent, c)
        root = (self.paths[rid].parent.parent / "texts" / "gutenberg").resolve()
        return path if path and path.resolve().is_relative_to(root) else None

    def snapshot(self):
        with self.lock:
            ids, results = list(self.paths), copy.deepcopy(self.results)
            running = self.running
        readers = []
        for rid in ids:
            try:
                saved = self.read(rid)
                candidates = []
                for c in saved["candidates"]:
                    d = c.get("download") or {}
                    present = self.audio_path(rid, c) is not None
                    status = d.get("status", "pending")
                    if status == "done" and not present:
                        status = "missing"
                    media = "/media?" + urllib.parse.urlencode({"reader": rid, "url": c["url"]})
                    text_present = self.text_path(rid, c) is not None
                    text_status = (c.get("text") or {}).get("status", "not checked")
                    if text_status == "done" and not text_present:
                        text_status = "missing"
                    required = c.get("text_required", saved.get("download_texts", False))
                    reasons = ([] if (d.get("quality") or c["quality"]) == "128" else ["64 kbps"])
                    if not c["in_range"]:
                        reasons.append("outside preferred length")
                    if required and not text_present:
                        reasons.append("missing text")
                    candidates.append({**c, "review_status": status, "audio_url": media if present else None,
                                       "text_status": text_status, "text_url": media.replace("/media?", "/text?") if text_present else None,
                                       "degraded_reasons": reasons})
                present = [c for c in candidates if c["audio_url"] and (c.get("download") or {}).get("status") == "done"]
                result = results.get(rid, {})
                last_scan = saved.get("last_rescan") or {}
                readers.append({"id": rid, "name": saved.get("reader", f"Reader {rid}"),
                                "url": saved.get("reader_url", f"https://librivox.org/reader/{rid}/"),
                                "out": str(self.paths[rid].parent),
                                "target": self.jobs[rid]["count"] if rid in self.jobs else saved.get("want_downloads", 0),
                                "status": result.get("status", saved.get("status", "saved state")),
                                "detail": result.get("detail", last_scan.get("detail", "") if saved.get("status") == last_scan.get("status") else ""), "downloaded": len(present),
                                "usable": sum(c.get("decision") != "reject" for c in present),
                                "premium": sum(c.get("decision") != "reject" and not c["degraded_reasons"] for c in present),
                                "rejected": sum(c.get("decision") == "reject" for c in candidates),
                                "kept": sum(c.get("decision") == "keep" for c in candidates),
                                "candidates": candidates, "checked": saved.get("checked", {}), "state": saved})
            except (OSError, ValueError, KeyError, TypeError) as e:
                readers.append({"id": rid, "name": rid, "status": "state error", "detail": str(e),
                                "target": 0, "downloaded": 0, "usable": 0, "premium": 0, "rejected": 0, "kept": 0,
                                "candidates": [], "checked": {}, "state": {}})
        return {"mode": "interactive" if self.interactive else "batch" if self.jobs or self.manifest else "review",
                "running": running or bool(self.interactive and self.interactive.collecting),
                "rescanning": self.rescanning, "can_rescan": bool(self.paths),
                "pausing": running and self.stop.is_set(),
                "can_add": bool(self.manifest),
                "can_projects": bool(self.projects and (self.manifest or self.jobs)),
                "can_collect": bool(self.jobs or self.interactive), "readers": readers}

    def project_action(self, action, body):
        """Use the same operation slot as sampling; never run two collection writers at once."""
        import librivox_launch as launch
        with self.lock:
            if not self.projects or not (self.manifest or self.jobs):
                raise ValueError("open a JSON session to scan or download projects")
            if self.running:
                raise ValueError("pause the current operation and wait for it to stop")
            include = body.get("include_dramatic", self.projects.data.get("include_dramatic", False))
            if not isinstance(include, bool):
                raise ValueError("include_dramatic must be true or false")
            if action == "project_options":
                self.projects.options(include)
                return
            if action == "project_scan":
                job = launch.load_batch(self.manifest or Path("session.json"), {"readers": [body.get("value")]})[0]
                rid = job["reader_id"]
                timeout = self.jobs.get(rid, {}).get("timeout_minutes", 60)
                operation = lambda: self.projects.scan(rid, self.stop, include, timeout)
                label = f"Scanning all projects for reader {rid}"
            elif action == "project_open":
                seed = {"url": projects.project_url(body.get("url"))}
                operation = lambda: self.projects.inspect(seed, include=include, refresh=True)
                label = "Loading project details"
            elif action == "project_download":
                key = body.get("project")
                with self.projects.lock:
                    project = self.projects.data["projects"][key]
                    if project.get("metadata_status") != "ready":
                        raise ValueError("load project details first")
                    rid = launch.normalize_reader_id(body["reader"], "reader") if body.get("reader") is not None else None
                    if rid and not any(rid in section["readers"] for section in project["sections"]):
                        raise ValueError("reader is not credited on any section")
                defaults = launch.DEFAULTS | (self.manifest_data or {}).get("defaults", {})
                if rid in self.jobs:
                    defaults.update({key: self.jobs[rid][key] for key in ("download_texts", "text_mirror")})
                operation = lambda: self.projects.download(key, rid, self.stop, defaults["download_texts"], defaults["text_mirror"])
                label = f"Downloading {project['title']}" + (f" · reader {rid}" if rid else " · entire project")
            else:
                raise ValueError("unknown project action")
            self.projects.options(include)
            self.running = True
            self.project_running = True
            self.stop.clear()
            with self.projects.lock:
                self.projects.data["activity"] = {"status": "running", "detail": label}
                self.projects.save()

            def work():
                status, detail = "idle", label
                try:
                    operation()
                    if self.stop.is_set():
                        status = "paused"
                except Exception as error:
                    status, detail = "failed", str(error)
                finally:
                    with self.projects.lock:
                        self.projects.data["activity"] = {"status": status, "detail": detail}
                        self.projects.save()
                    with self.lock:
                        self.running = False
                        self.project_running = False
            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

    def save_manifest(self, data):
        """Validate before replacing; don't overwrite edits made outside this dashboard."""
        import librivox_launch as batch
        jobs = batch.load_batch(self.manifest, data)
        if json.loads(self.manifest.read_text(encoding="utf-8")) != self.manifest_data:
            raise ValueError("JSON file changed outside the dashboard; restart to load those changes")
        temporary = self.manifest.with_suffix(self.manifest.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(self.manifest)
        self.manifest_data = data
        self.jobs = {job["reader_id"]: job for job in jobs}
        self.paths.update({rid: Path(job["out"]) / "state.json" for rid, job in self.jobs.items()})

    def add_reader(self, value, count):
        import librivox_launch as batch
        with self.lock:
            if not self.manifest or self.running:
                raise ValueError("reader entry requires an idle JSON dashboard")
            batch.positive(count, "count", integer=True)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("enter a LibriVox reader URL or reader ID")
            value = value.strip()
            reader = {"reader_id" if value.isdigit() else "url": value, "count": count}
            data = copy.deepcopy(self.manifest_data)
            if not self.jobs:
                data["auto_collect"] = False
            data.setdefault("readers", []).append(reader)
            self.save_manifest(data)

    def set_count(self, rid, count):
        import librivox_launch as batch
        batch.positive(count, "count", integer=True)
        if rid not in self.jobs:
            raise ValueError("unknown reader")
        if self.manifest:
            data = copy.deepcopy(self.manifest_data)
            index = list(self.jobs).index(rid)
            entry = data["readers"][index]
            if not isinstance(entry, dict):
                entry = {"reader_id": rid}
            data["readers"][index] = {**entry, "count": count}
            self.save_manifest(data)
        else:
            self.jobs[rid]["count"] = count

    def register(self, job, state):
        with self.lock:
            self.states[job["reader_id"]] = state
            self.results.pop(job["reader_id"], None)

    def state_factory(self, args, rid, out):
        with self.lock:
            state = app.State(args, rid, out)
            self.states[rid] = state
            return state

    def finished(self, result):
        with self.lock:
            rid = result["reader_id"]
            self.results[rid] = result
            self.states.pop(rid, None)  # subsequent review reads/edits the saved record directly

    def start(self, rid=None, count=None):
        if self.interactive:
            with self.lock:
                if self.running:
                    raise ValueError("wait for the metadata rescan to finish or pause it")
                st = self.interactive
                with st.lock:
                    if count is not None:
                        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                            raise ValueError("count must be a positive integer")
                        st.want_downloads = count
                    elif not st.want_downloads:
                        st.want_downloads = st.args.count
                    if not st.collecting:
                        st.reset_text_attempts()
                    st.collecting = True
                    st.save()
                st.wake.set()
                self.ensure_interactive_workers()
            return
        with self.lock:
            if self.running:
                raise ValueError("collection is already running")
            if not self.jobs:
                raise ValueError("review only: open with a batch JSON file to collect")
            if rid is not None and rid not in self.jobs:
                raise ValueError("unknown reader")
            if count is not None:
                if rid is None:
                    raise ValueError("select a reader to change its target")
                self.set_count(rid, count)
            jobs = [self.jobs[rid]] if rid else list(self.jobs.values())
            self.stop.clear()
            self.running = True
            for job in jobs:
                self.results[job["reader_id"]] = {"status": "waiting"}

            def work():
                import librivox_launch as batch
                try:
                    summary = batch.run_batch(jobs, on_state=self.register, on_result=self.finished,
                                              stop=self.stop, state_factory=self.state_factory)
                    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
                finally:
                    with self.lock:
                        self.running = False

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

    def ensure_interactive_workers(self, scan=True):
        """Start missing workers only for a live server, never for state-only inspection/tests."""
        with self.lock:
            if not self.interactive or not self.serving or self.closing or self.rescanning:
                return
            for attr, target in (("scan_thread", app.scanner), ("download_thread", app.downloader)):
                if attr == "scan_thread" and (not scan or self.interactive.scan_done):
                    continue
                thread = getattr(self, attr)
                if thread and thread.is_alive():
                    continue
                thread = threading.Thread(target=target, args=(self.interactive,), daemon=True)
                setattr(self, attr, thread)
                self.threads.append(thread)
                thread.start()

    def rescan(self, rid=None):
        """Explicit metadata-only refresh, including when opened with --review."""
        import librivox_launch as batch
        with self.lock:
            if self.running or (self.interactive and (self.interactive.collecting or self.interactive.queue)):
                raise ValueError("pause collection and wait for outstanding downloads before rescanning")
            if rid is not None and rid not in self.paths:
                raise ValueError("unknown reader")
            ids = [rid] if rid else list(self.paths)
            if not ids:
                raise ValueError("no readers to rescan")
            settings = []
            for reader in ids:
                saved = self.read(reader)
                if self.interactive:
                    args = self.interactive.args
                elif reader in self.jobs:
                    args = batch.reader_args(self.jobs[reader])
                    batch.validate_resume(self.jobs[reader], args)
                    args.projects = max(self.jobs[reader].get("projects", args.projects), int(saved.get("target", 0)))
                else:
                    selection = saved.get("selection")
                    if not isinstance(selection, dict) or not {"language", "range_minutes", "min_seconds", "order"} <= selection.keys():
                        raise ValueError("rescan requires saved selection settings; keep legacy state for review and use a new configured collection to scan")
                    args = SimpleNamespace(name=saved.get("reader", f"Reader {reader}"),
                                           url=f"https://librivox.org/reader/{reader}/",
                                           projects=max(20, int(saved.get("target", 20))),
                                           count=max(1, int(saved.get("want_downloads", 1))),
                                           range=selection["range_minutes"], language=selection["language"],
                                           min_seconds=selection["min_seconds"], order=selection["order"],
                                           download_texts=saved.get("download_texts", False),
                                           text_mirror=app.texts.DEFAULT_MIRROR)
                settings.append((reader, args, self.jobs.get(reader, {}).get("timeout_minutes", 60)))
            self.stop.clear()
            self.running = self.rescanning = True
            for reader in ids:
                self.results[reader] = {"status": "waiting to rescan"}

            def work():
                try:
                    if self.interactive:
                        # Stop the old listing iterator before resetting checks. Preserve queued intent.
                        self.interactive.stop.set()
                        self.interactive.wake.set()
                        for thread in self.threads:
                            thread.join()
                        if not self.closing:
                            self.interactive.stop.clear()
                    for reader, args, timeout in settings:
                        if self.stop.is_set():
                            with self.lock:
                                self.results[reader] = {"status": "scan paused", "detail": "rescan not started"}
                            continue
                        try:
                            source = None
                            if reader in self.jobs:
                                args.name, source = batch.resolve_name(self.jobs[reader], self.read(reader))
                                self.jobs[reader]["name"] = args.name
                            with self.lock:
                                state = self.interactive or self.state_factory(args, reader, self.paths[reader].parent)
                                if source:
                                    state.extra["reader_name_source"] = source
                                self.results.pop(reader, None)
                            result = app.rescan_reader(state, self.stop, timeout)
                        except Exception as e:
                            result = {"status": "scan failed", "detail": str(e)}
                        with self.lock:
                            self.results[reader] = result
                            if not self.interactive:
                                self.states.pop(reader, None)
                finally:
                    with self.lock:
                        self.running = self.rescanning = False
                    # Remain idle after a metadata pass; Collect / resume can start a new scanner later.
                    self.ensure_interactive_workers(scan=False)

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

    def pause(self):
        self.stop.set()
        if self.interactive:
            with self.interactive.lock:
                self.interactive.collecting = False

    def change(self, rid, url, action, decision=None):
        # Serialize registration/finish and review writes so no stale snapshot can overwrite a live transfer.
        with self.lock:
            if rid is None and len(self.paths) == 1:
                rid = next(iter(self.paths))
            state = self.states.get(rid)
            if self.rescanning and action != "decide":
                raise ValueError("wait for the metadata rescan to finish")
            if action != "decide" and self.interactive is None:
                if rid not in self.jobs:
                    raise ValueError("open the JSON dashboard to download or select quality")
                if self.running:
                    raise ValueError("pause collection and wait for it to stop before individual actions")
                import librivox_launch as batch
                args = batch.reader_args(self.jobs[rid])
                saved = batch.validate_resume(self.jobs[rid], args)
                args.name = saved.get("reader", args.name)
                state = app.State(args, rid, self.paths[rid].parent)
            lock = state.lock if state else self.lock
            with lock:
                saved = copy.deepcopy(state.record()) if state else self.read(rid)
                c = next((c for c in saved["candidates"] if c["url"] == url), None)
                if c is None:
                    raise ValueError("unknown project")
                if state:
                    c = state.find(url)
                if action == "decide":
                    if decision not in ("keep", "reject", None):
                        raise ValueError("invalid decision")
                    c["decision"], c["decided_at"] = decision, app.now()
                    if state and decision == "reject" and url in state.queue:
                        state.queue.remove(url)
                        if c["download"] and c["download"]["status"] == "queued":
                            c["download"] = None
                elif action == "download":
                    state.enqueue(c)
                elif action == "missing_128":
                    if c["quality"] == "128":
                        state.mark_128_missing(c, "source preview failed (possibly a temporary connection error)")
                elif action == "retry_128":
                    if c["download"] and c["download"]["status"] in ("queued", "downloading"):
                        raise ValueError("wait for the current download to finish")
                    c["quality"] = "128"
                    c.pop("missing_128", None)
                else:
                    raise ValueError("unknown action")
                if state:
                    state.save()
                    state.wake.set()
                    if not self.interactive and action != "decide":
                        self.states.pop(rid, None)
                        self.results.pop(rid, None)
                        if action == "download" and state.queue:
                            self.start_individual(rid, state)
                else:
                    saved["updated_at"] = app.now()
                    path = self.paths[rid]
                    tmp = path.with_suffix(".review.tmp")
                    tmp.write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(path)

    def start_individual(self, rid, state):
        """Drain explicit requests only; a saved bulk target must not start extra transfers."""
        self.stop.clear()
        self.running = True
        self.states[rid] = state

        def work():
            status, detail = "idle", ""
            try:
                while state.queue and not self.stop.is_set():
                    if not app.download_next(state, cancelled=lambda c: self.stop.is_set(), individual_only=True):
                        break
                status = "paused" if self.stop.is_set() else "idle"
            except Exception as e:
                status, detail = "failed", str(e)
            finally:
                with self.lock:
                    with state.lock:
                        state.status = status
                        state.save()
                    self.results[rid] = {"status": status, "detail": detail}
                    self.states.pop(rid, None)
                    self.running = False

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def scan_more(self, rid, n=10):
        import librivox_launch as batch
        with self.lock:
            if self.running or rid not in self.jobs:
                raise ValueError("select a configured reader while collection is idle")
            batch.positive(n, "additional candidates", integer=True)
            args = batch.reader_args(self.jobs[rid])
            saved = batch.validate_resume(self.jobs[rid], args)
            args.name = saved.get("reader", args.name)
            state = app.State(args, rid, self.paths[rid].parent)
            with state.lock:
                state.target = max(self.jobs[rid].get("projects", args.projects), int(saved.get("target", 0))) + n
                state.save()
            self.rescan(rid)


def make_handler(dashboard):
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except CLIENT_DISCONNECTS:
                # Browser navigation, cancelled polling or stopped playback can close the local socket.
                self.close_connection = True

        def log_message(self, *args):
            pass

        def send(self, status, content, kind="application/json"):
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path in ("/", "/review", "/projects"):
                self.send(200, Path(__file__).with_name("dashboard.html").read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/api/dashboard":
                self.send(200, json.dumps(dashboard.snapshot(), ensure_ascii=False))
            elif parsed.path == "/api/projects":
                self.send(200, json.dumps(dashboard.projects.snapshot(active=dashboard.project_running) if dashboard.projects else {"projects": {}, "scans": {}}, ensure_ascii=False))
            elif parsed.path in ("/project-media", "/project-text"):
                try:
                    path = dashboard.projects.text_file(query["project"][0]) if parsed.path == "/project-text" else dashboard.projects.file(query["project"][0], int(query["section"][0]))
                    if path is None:
                        raise ValueError("file not present")
                    if parsed.path == "/project-text":
                        self.send(200, path.read_bytes(), "text/plain; charset=utf-8")
                    else:
                        self.media(path)
                except CLIENT_DISCONNECTS:
                    raise
                except (OSError, ValueError, KeyError, IndexError, AttributeError):
                    self.send(404, "file not found", "text/plain")
            elif parsed.path == "/api/state" and dashboard.interactive:
                self.send(200, dashboard.interactive.snapshot())
            elif parsed.path in ("/media", "/text"):
                try:
                    rid, url = query["reader"][0], query["url"][0]
                    c = next(c for c in dashboard.read(rid)["candidates"] if c["url"] == url)
                    path = dashboard.text_path(rid, c) if parsed.path == "/text" else dashboard.audio_path(rid, c)
                    if path is None:
                        raise ValueError("file not present")
                    if parsed.path == "/text":
                        self.send(200, path.read_bytes(), "text/plain; charset=utf-8")
                    else:
                        self.media(path)
                except CLIENT_DISCONNECTS:
                    raise  # handled at the connection boundary, not as a missing file
                except (OSError, ValueError, KeyError, StopIteration):
                    self.send(404, "file not found", "text/plain")
            else:
                self.send(404, "not found", "text/plain")

        def media(self, path):
            with path.open("rb") as audio:
                size = path.stat().st_size
                start, end = 0, size - 1
                header = self.headers.get("Range")
                if header:
                    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", header)
                    if match and any(match.groups()):
                        lo, hi = match.groups()
                        start = int(lo) if lo else max(0, size - int(hi))
                        end = min(size - 1, int(hi)) if lo and hi else size - 1
                    if not match or not any(match.groups()) or start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                self.send_response(206 if header else 200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(max(0, end - start + 1)))
                if header:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if self.command == "HEAD":
                    return
                audio.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = audio.read(min(left, 65536))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except CLIENT_DISCONNECTS:
                    self.close_connection = True

        def do_POST(self):
            # Mutations are same-origin JSON requests; the server binds only to loopback.
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                self.send(403, "cross-origin request refused", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1048576:
                    raise ValueError("invalid body length")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("expected a JSON object")
                action = self.path.removeprefix("/api/")
                if action in ("start", "download_n"):
                    dashboard.start(body.get("reader"), body.get("n"))
                elif action in ("project_scan", "project_open", "project_download", "project_options"):
                    dashboard.project_action(action, body)
                elif action == "pause":
                    dashboard.pause()
                elif action == "rescan":
                    dashboard.rescan(body.get("reader"))
                elif action == "add_reader":
                    dashboard.add_reader(body.get("value"), body.get("n", 10))
                elif action == "scan_more" and not dashboard.interactive:
                    dashboard.scan_more(body.get("reader"), body.get("n", 10))
                elif action == "scan_more" and dashboard.interactive:
                    if dashboard.rescanning:
                        raise ValueError("wait for the metadata rescan to finish")
                    with dashboard.interactive.lock:
                        dashboard.interactive.target += max(0, int(body.get("n", 10)))
                        dashboard.interactive.save()
                    dashboard.interactive.wake.set()
                    dashboard.ensure_interactive_workers()
                else:
                    dashboard.change(body.get("reader"), body.get("url"), action, body.get("decision"))
                self.send(200, "{}")
            except CLIENT_DISCONNECTS:
                raise  # the operation may have succeeded; do not attempt another response
            except (ValueError, TypeError, KeyError, OSError) as e:
                self.send(400, str(e), "text/plain")

    return Handler


def serve_dashboard(dashboard, port=8765, collect=False, browse=False):
    with app.LocalServer(("127.0.0.1", port), make_handler(dashboard)) as server:
        print(f"Dashboard: http://127.0.0.1:{server.server_port}/ (Ctrl+C to close)", flush=True)
        dashboard.serving = True
        if dashboard.interactive:
            dashboard.ensure_interactive_workers()
        elif collect:
            dashboard.start()
        elif browse:
            dashboard.rescan()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            dashboard.closing = True
            dashboard.pause()
            if dashboard.interactive:
                dashboard.interactive.stop.set()
                dashboard.interactive.wake.set()
            workers = dashboard.threads + ([dashboard.worker] if dashboard.worker else [])
            if any(worker.is_alive() for worker in workers):
                print("Stopping collection after the current operation…", flush=True)
            for worker in workers:
                while worker.is_alive():
                    worker.join(0.5)
