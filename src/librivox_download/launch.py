"""Collect and review LibriVox samples in a local dashboard, or run a headless JSON batch.

    python librivox_web.py
    python librivox_web.py batch.json --dry-run
    python librivox_web.py batch.json
    python librivox_web.py --review downloads
    python librivox_web.py batch.json --headless

With --headless, progress goes to stderr and the final JSON summary goes to stdout. Exit 0 means all targets met;
1 means incomplete/failed readers, 2 means invalid configuration, and 130 means interrupted.
"""
import argparse
import html
import json
import math
import re
import sys
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

from . import fetch as app


DEFAULTS = {"count": 10, "language": "English", "range_minutes": [5, 15],
            "min_seconds": 60, "order": "alpha", "timeout_minutes": 60,
            "download_texts": True, "text_mirror": app.texts.DEFAULT_MIRROR}
DEFAULT_SESSION = "session.local.json"


def positive(value, label, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value <= 0 or (integer and not isinstance(value, int))):
        raise ValueError(f"{label} must be a positive {'integer' if integer else 'number'}")


def normalize_reader_id(value, label):
    if (isinstance(value, bool) or not isinstance(value, (int, str)) or
            not re.fullmatch(r"[0-9]+", str(value).strip()) or int(value) <= 0):
        raise ValueError(f"{label}: reader_id must be a positive integer or digit string")
    return str(int(value))


def load_batch(path, data=None):
    """Validate the whole manifest before any writes or network requests. Paths are manifest-relative."""
    path = Path(path).resolve()
    if data is None:
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"defaults", "output_root", "readers", "_ignore", "auto_collect"}:
        raise ValueError("batch accepts only defaults, output_root, readers, auto_collect and _ignore fields")
    if not isinstance(data.get("auto_collect", True), bool):
        raise ValueError("auto_collect must be true or false")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict) or set(defaults) - (DEFAULTS.keys() | {"_ignore"}):
        raise ValueError(f"defaults accepts only: {', '.join(DEFAULTS)}, _ignore")
    defaults = {k: v for k, v in defaults.items() if k != "_ignore"}
    output = data.get("output_root", "downloads")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("output_root must be a nonempty path string")
    output = (path.parent / output).resolve()
    readers = data.get("readers", [])
    if not isinstance(readers, list):
        raise ValueError("readers must be a list")
    empty = not readers
    # Validate defaults even when the dashboard starts without readers.
    readers = readers or [1]
    jobs, seen = [], set()
    for index, reader in enumerate(readers, 1):
        label = f"reader {index}"
        if isinstance(reader, (str, int)) and not isinstance(reader, bool):
            is_id = isinstance(reader, int) or bool(re.fullmatch(r"[0-9]+", reader.strip()))
            reader = {"reader_id" if is_id else "url": reader}
        if not isinstance(reader, dict) or set(reader) - (DEFAULTS.keys() | {"name", "url", "reader_id", "_ignore"}):
            raise ValueError(f"{label}: unknown fields or invalid reader object")
        rid = normalize_reader_id(reader["reader_id"], label) if "reader_id" in reader else None
        if "url" in reader:
            url = reader["url"]
            if not isinstance(url, str):
                raise ValueError(f"{label}: url must be a string")
            parsed = urllib.parse.urlsplit(url)
            match = re.fullmatch(r"/reader/([0-9]+)/?", parsed.path)
            if (parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in
                    ("librivox.org", "www.librivox.org") or not match or int(match[1]) == 0):
                raise ValueError(f"{label}: expected a LibriVox /reader/ID/ URL")
            url_id = str(int(match[1]))
            if rid is not None and rid != url_id:
                raise ValueError(f"{label}: reader_id and url identify different readers")
            rid = url_id
        if rid is None:
            raise ValueError(f"{label}: url or reader_id is required")
        if rid in seen:
            raise ValueError(f"duplicate reader ID: {rid}")
        seen.add(rid)
        options = DEFAULTS | defaults | {k: v for k, v in reader.items() if k in DEFAULTS}
        positive(options["count"], f"{label} count", integer=True)
        if not isinstance(options["download_texts"], bool):
            raise ValueError(f"{label}: download_texts must be true or false")
        options["text_mirror"] = app.texts.validate_mirror(options["text_mirror"])
        for key in ("min_seconds", "timeout_minutes"):
            positive(options[key], f"{label} {key}")
        bounds = options["range_minutes"]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"{label}: range_minutes must contain MIN and MAX")
        for bound in bounds:
            positive(bound, f"{label} range_minutes")
        if bounds[0] > bounds[1]:
            raise ValueError(f"{label}: range_minutes MIN must not exceed MAX")
        if not isinstance(options["language"], str) or options["order"] not in ("alpha", "catalog_date"):
            raise ValueError(f"{label}: language must be a string and order alpha or catalog_date")
        name = reader.get("name", f"Reader {rid}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}: name must be a nonempty string if provided")
        jobs.append({**options, "reader_id": rid, "name": name,
                     "name_source": "explicit" if "name" in reader else "pending",
                     "url": f"https://librivox.org/reader/{rid}/", "out": str(output / rid)})
    return [] if empty else jobs


def reader_args(job):
    return SimpleNamespace(name=job["name"], url=job["url"], count=job["count"],
                           projects=2 * job["count"], range=job["range_minutes"],
                           download_texts=job["download_texts"], text_mirror=job["text_mirror"],
                           min_seconds=job["min_seconds"], language=job["language"], order=job["order"])


def validate_resume(job, args):
    path = Path(job["out"]) / "state.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if str(saved.get("reader_id")) != job["reader_id"]:
            raise ValueError("output state belongs to another reader; choose a different output_root")
        if saved.get("selection") != app.selection_options(args):
            raise ValueError("saved selection settings differ or are unknown; choose a different output_root")
        return saved
    return {}


def reader_name(url):
    """LibriVox's reader title includes its display name, including any dates or punctuation."""
    page = app.get(url)
    title = re.search(r"<title\b[^>]*>(.*?)</title>", page, re.I | re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "", title[1])) if title else ""
    match = re.fullmatch(r"\s*Works read by\s+(.+?)\s*\|\s*LibriVox\s*", text, re.I | re.S)
    if not match:
        raise ValueError("reader page has no recognizable display name")
    name = " ".join(match[1].split())
    if not name:
        raise ValueError("reader page has an empty display name")
    return name


def resolve_name(job, saved):
    """Prefer an explicit label, then a cached label; a failed lookup never blocks collection."""
    if job.get("name_source", "explicit") == "explicit":
        return job["name"], "explicit"
    fallback = f"Reader {job['reader_id']}"
    cached = saved.get("reader")
    if cached and (cached != fallback or saved.get("reader_name_source") in ("page", "explicit")):
        return cached, saved.get("reader_name_source", "cached")
    try:
        return reader_name(job["url"]), "page"
    except Exception as e:
        print(f"{fallback}: name lookup failed ({e}); using ID label", file=sys.stderr, flush=True)
        return fallback, "fallback"


def projects(st):
    for page, items in app.listing_pages(st.rid, st.args.order):
        st.page = page
        yield from items


def reader_result(job, status, downloaded=None, detail=""):
    return {"reader_id": job["reader_id"], "name": job["name"], "url": job["url"], "out": job["out"],
            "status": status, "target": job["count"], "downloaded": downloaded, "detail": detail}


class DownloadProgress:
    """Redraw one terminal line; redirected logs get only distinct counters, without control characters."""

    def __init__(self):
        self.stream = sys.stderr
        self.terminal = self.stream.isatty()
        self.width = 0
        self.last = None

    def update(self, job, count, premium=None):
        message = (f"{job['name']}: {count}/{job['count']} downloaded" if premium is None else
                   f"{job['name']}: {premium}/{job['count']} premium, {count} downloaded")
        if message == self.last:
            return
        self.last = message
        if self.terminal:
            self.stream.write("\r" + message.ljust(self.width))
            self.width = len(message)
            self.stream.flush()
        else:
            print(message, file=self.stream, flush=True)

    def finish(self):
        if self.terminal and self.width:
            print(file=self.stream, flush=True)
            self.width = 0


def run_reader(job, on_state=None, stop=None, state_factory=None):
    """No background threads: each operation finishes before another reader is started."""
    deadline = time.monotonic() + job["timeout_minutes"] * 60
    args = reader_args(job)
    saved = validate_resume(job, args)  # check before name requests or writes to existing state
    job["name"], source = resolve_name(job, saved)
    args.name = job["name"]
    st = (state_factory or app.State)(args, job["reader_id"], Path(job["out"]))
    with st.lock:
        st.extra["reader_name_source"] = source
        st.want_downloads = job["count"]  # target totals include valid existing non-rejected downloads
        for c in st.candidates:
            if c["download"] and c["download"]["status"] == "failed" and c["decision"] != "reject":
                c["download"] = None  # one new attempt per batch invocation, never an unlimited retry loop
        st.status = "collecting"
        st.save()
    if on_state:
        on_state(job, st)
    listing = projects(st)
    progress = DownloadProgress()
    status, detail = "failed", ""
    try:
        while True:
            if stop and stop.is_set():
                status, detail = "paused", "paused by user; resume explicitly from the dashboard"
                break
            with st.lock:
                st.reconcile_downloads()
                if st.collection_satisfied():
                    status = "completed"
                    if st.premium_downloaded() < job["count"]:
                        detail = "listing exhausted; target filled with degraded fallbacks"
                    break
            if time.monotonic() >= deadline:
                detail = "reader time budget exceeded"
                break
            if app.download_next(st, cancelled=(lambda c: stop.is_set()) if stop else None):
                with st.lock:
                    progress.update(job, st.downloaded(), st.premium_downloaded())
                continue
            if st.scan_done:
                with st.lock:
                    errors = [v["reason"] for v in st.checked.values() if (v["reason"] or "").startswith("error:")]
                    errors += [c["download"]["error"] for c in st.candidates
                               if c["download"] and c["download"]["status"] == "failed" and c["decision"] != "reject"]
                status = "failed" if errors else "insufficient"
                detail = "; ".join(errors[:3]) if errors else "listing exhausted before the target was met"
                break
            try:
                project = next(listing)
            except StopIteration:
                st.scan_done = True  # backups become eligible only after actual exhaustion
            else:
                if not stop or not stop.is_set():
                    st.status = "scanning"
                    app.scan_project(st, project)
    except KeyboardInterrupt:
        status, detail = "interrupted", "stopped by user; rerun the same batch to resume"
    except Exception as e:
        detail = str(e)
    finally:
        progress.finish()
        listing.close()
        with st.lock:
            st.status = status
            st.save()
            downloaded = st.downloaded()
            premium = st.premium_downloaded()
    return {**reader_result(job, status, downloaded, detail), "premium": premium,
            "degraded": downloaded - premium}


def run_batch(jobs, on_state=None, on_result=None, stop=None, state_factory=None):
    results = []
    for index, job in enumerate(jobs):
        if stop and stop.is_set():
            remaining = [reader_result(rest, "not_run", detail="batch paused") for rest in jobs[index:]]
            results.extend(remaining)
            if on_result:
                for result in remaining:
                    on_result(result)
            break
        print(f"Starting {job['name']} ({job['reader_id']})", file=sys.stderr, flush=True)
        try:
            result = run_reader(job, on_state=on_state, stop=stop, state_factory=state_factory)
        except KeyboardInterrupt:
            result = reader_result(job, "interrupted", detail="stopped by user")
        except Exception as e:
            result = reader_result(job, "failed", detail=str(e))
        results.append(result)
        if on_result:
            on_result(result)
        print(f"{job['name']}: {result['status']}", file=sys.stderr, flush=True)
        if result["status"] in ("interrupted", "paused"):
            remaining = [reader_result(rest, "not_run", detail="batch stopped") for rest in jobs[index + 1:]]
            results.extend(remaining)
            if on_result:
                for result in remaining:
                    on_result(result)
            break
    return {"finished_at": app.now(), "results": results}


def main(choose_session=False):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", nargs="?", type=Path,
                        help=("JSON session file; omit to choose or create one in the console" if choose_session else
                              f"JSON session file (default: {DEFAULT_SESSION} in the current directory); create if missing"))
    parser.add_argument("--review", type=Path, help="review an output root, reader directory or state.json; no collection")
    parser.add_argument("--port", type=int, default=8765, help="loopback dashboard port (default 8765)")
    parser.add_argument("--headless", action="store_true", help="collect without a dashboard and exit when finished")
    parser.add_argument("--dry-run", action="store_true", help="validate and print resolved jobs; no writes or network")
    parser.add_argument("--browse", action="store_true", help="open the dashboard without automatic collection")
    args = parser.parse_args()
    if args.batch and args.review:
        parser.error("provide a JSON session file or --review PATH, not both")
    if args.review and (args.headless or args.dry_run or args.browse):
        parser.error("--headless, --dry-run and --browse apply only to a batch JSON file")
    if args.headless and args.browse:
        parser.error("--browse requires the dashboard")
    if choose_session and args.batch is None and (args.headless or args.dry_run):
        parser.error("provide a JSON session file for --headless or --dry-run")
    if args.review:
        from .dashboard import Dashboard, serve_dashboard
        try:
            dashboard = Dashboard.for_review(args.review)
        except (OSError, ValueError) as e:
            parser.error(str(e))
        serve_dashboard(dashboard, args.port)
        return 0
    if choose_session and args.batch is None and not args.headless and not args.dry_run:
        from .dashboard import Dashboard, serve_dashboard
        serve_dashboard(Dashboard(), args.port)
        return 0
    args.batch = args.batch or Path(DEFAULT_SESSION)
    try:
        if not args.headless and not args.dry_run:
            try:
                with args.batch.open("x", encoding="utf-8", newline="\n") as session:
                    session.write("{}\n")
                print(f"Created session: {args.batch.resolve()}\n{{}}", flush=True)
            except FileExistsError:
                pass  # existing files, including invalid/empty ones, must never be overwritten
        jobs = load_batch(args.batch)
    except (OSError, ValueError, TypeError) as e:
        parser.error(str(e))
    if args.dry_run:
        print(json.dumps({"readers": jobs}, indent=2, ensure_ascii=False))
        return 0
    if not args.headless:
        from .dashboard import Dashboard, serve_dashboard
        print(f"Session settings: {args.batch.resolve()}", flush=True)
        data = json.loads(args.batch.read_text(encoding="utf-8"))
        serve_dashboard(Dashboard(jobs=jobs, manifest=args.batch), args.port,
                        collect=bool(jobs) and data.get("auto_collect", True) and not args.browse)
        return 0
    summary = run_batch(jobs)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    statuses = [r["status"] for r in summary["results"]]
    return 130 if "interrupted" in statuses else (0 if all(s == "completed" for s in statuses) else 1)


if __name__ == "__main__":
    sys.exit(main())
