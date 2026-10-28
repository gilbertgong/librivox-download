"""Local session selection and serialized controller replacement; no server restarts."""
import json
import threading
from pathlib import Path

from .dashboard import Dashboard
from . import launch


def stop_dashboard(view):
    view.closing = True
    view.pause()
    if view.interactive:
        view.interactive.stop.set()
        view.interactive.wake.set()
    for worker in list(view.threads) + ([view.worker] if view.worker else []):
        while worker.is_alive():
            worker.join(0.5)
    view.serving = False


class Sessions:
    def __init__(self, current, directory, enabled=True):
        self.current = current
        self.directory = Path(directory).resolve()
        self.home = self.directory / "sessions"
        self.enabled = enabled
        self.lock = threading.RLock()
        self.switching = False
        self.pending = None
        self.error = ""
        self.generation = 0
        self.worker = None
        self.closing = False

    def files(self):
        paths = set()
        for directory in (self.directory, self.home):
            if directory.is_dir():
                paths.update(p.resolve() for p in directory.iterdir()
                             if p.suffix.lower() == ".json" and p.is_file()
                             and p.resolve().parent == directory)
        if self.current.manifest:
            paths.add(self.current.manifest)
        return sorted(paths, key=lambda p: str(p).lower())

    def snapshot(self):
        with self.lock:
            active = self.current.manifest
            entries = []
            if self.enabled:
                for path in self.files():
                    try:
                        launch.load_batch(path)
                        error = ""
                    except (OSError, ValueError, TypeError, KeyError) as exc:
                        error = str(exc)
                    entries.append({"path": str(path), "name": str(path.relative_to(self.directory))
                                    if path.is_relative_to(self.directory) else str(path),
                                    "valid": not error, "error": error})
            return {"enabled": self.enabled, "active": str(active) if active else None,
                    "name": active.name if active else None, "directory": str(self.home),
                    "files": entries, "switching": self.switching, "pending": self.pending,
                    "error": self.error, "generation": self.generation}

    def open(self, filename, create=False):
        with self.lock:
            if not self.enabled or self.closing:
                raise ValueError("session switching is unavailable in this view")
            if self.switching:
                raise ValueError("a session is already opening; wait for it to finish")
            if not isinstance(filename, str) or not filename.strip():
                raise ValueError("choose a session file or enter a filename")
            if create:
                name = filename.strip()
                if "/" in name or "\\" in name or ":" in name or name.startswith("."):
                    raise ValueError("enter a filename, not a path")
                if not name.lower().endswith(".json"):
                    name += ".json"
                self.home.mkdir(parents=True, exist_ok=True)
                path = self.home / name
                # Keep the established downloads directory when moving new configs into sessions/.
                data = {"output_root": "../downloads", "auto_collect": False, "readers": []}
                try:
                    with path.open("x", encoding="utf-8", newline="\n") as output:
                        output.write(json.dumps(data, indent=2) + "\n")
                except FileExistsError:
                    raise ValueError(f"Session {name} already exists; open it or choose another filename") from None
            else:
                path = Path(filename).resolve()
                if path not in self.files():
                    raise ValueError("choose a JSON file listed in the session picker")
            # Invalid configs or corrupt saved libraries must not interrupt the current session.
            candidate = Dashboard(jobs=launch.load_batch(path), manifest=path)
            old = self.current
            self.switching = True
            self.pending = path.name
            self.error = ""
            old.closing = True
            old.pause()

            def switch():
                try:
                    stop_dashboard(old)
                    # Reload after draining: an editor may have changed the selected file meanwhile.
                    candidate = Dashboard(jobs=launch.load_batch(path), manifest=path)
                    with self.lock:
                        if not self.closing:
                            candidate.serving = True
                            self.current = candidate
                            self.generation += 1
                            print(f"Session settings: {path}", flush=True)
                except Exception as exc:
                    with self.lock:
                        old.closing = False
                        old.serving = True
                        self.error = str(exc)
                finally:
                    with self.lock:
                        self.switching = False
                        self.pending = None
            self.worker = threading.Thread(target=switch, daemon=True)
            self.worker.start()

    def stop(self):
        with self.lock:
            self.closing = True
            self.current.pause()
        if self.worker:
            self.worker.join()
        stop_dashboard(self.current)
