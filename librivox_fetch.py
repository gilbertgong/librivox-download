"""Find a LibriVox reader's solo recordings, one per project, and vet them on a local web page.

    python librivox_fetch.py "Beth Thomas" https://librivox.org/reader/6281/
    then open http://127.0.0.1:8765/

A reader's LibriVox page lists every project they took part in: solo books, collaborative books where they read a
few chapters, dramatic readings (cast performances, skipped), and some they only coordinated. The server reads that
listing a page at a time in the background and checks each project as it comes in. A project is a candidate if a
section's reader list is exactly this reader and the section is at least --min-seconds long. Projects without
per-section reader metadata are skipped. Details prefer LibriVox's official API, with HTML as a fallback;
reader discovery/name lookup still uses the website. Audio-host metadata is not used for selection.

One section per project is offered: the first one 5-15 minutes long (--range), or, if none is, the one closest to
that range. Its file is the 128 kbps one, judged by name (`*_128kb.mp3`). A 64 kbps file is suboptimal: it's used
only when a section has no 128 kbps name, or an attempt to play or download it fails. Such failures can be
temporary; the page offers a way to retry 128 kbps.

A candidate is premium (prime internally) if its section is in the length range, has a 128 kbps file and has
downloaded source text when enabled. Other candidates are degraded backups with visible reasons on Review.
Source books download by default through a Gutenberg mirror, shared under <out>/../texts/gutenberg/<id>.
Scanning continues until there are --projects prime candidates that haven't been rejected (or N, if "Download N"
asks for more), so rejecting one makes the scan look further. On the page you can listen, keep, reject, download
one, or collect N: the server seeks N premium downloads, accepting backups only after listing exhaustion.
Explicit resume seeks premium replacements for degraded recordings, preserving earlier files and decisions.

Everything lives in <out> (default downloads/<name>): one folder per downloaded project with its MP3, and
state.json, the single record of what's been checked, decided (keep / reject) and downloaded, with the time of each
change. It's rewritten on every change, so a restart resumes where it left off.
"""
import argparse
import html
import json
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import librivox_text as texts
import librivox_api as api

USER_AGENT = "librivox-download (personal research)"
DELAY = 0.5  # seconds between LibriVox page requests


# ---------------------------------------------------------------- LibriVox pages

def get(url, ajax=False, referer=None):
    headers = {"User-Agent": USER_AGENT}
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if referer:
        headers["Referer"] = referer
    time.sleep(DELAY)
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def reader_id(url):
    m = re.search(r"/reader/(\d+)", url)
    if not m:
        sys.exit(f"Not a LibriVox reader URL: {url}")
    return m.group(1)


def hms(text):
    """'01:02:03' or '02:03' -> seconds."""
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def listing_pages(rid, order):
    """Yield the reader's listing one page at a time: (page number, [{url, title, type, language}])."""
    page = 1
    while True:
        query = urllib.parse.urlencode({
            "primary_key": rid, "search_category": "reader", "sub_category": "", "search_page": page,
            "search_order": order, "project_type": "either",
        })
        data = json.loads(get(f"https://librivox.org/reader/get_results?{query}", ajax=True,
                              referer=f"https://librivox.org/reader/{rid}/"))
        items = re.findall(r'<h3><a href="([^"]+)">(.*?)</a>.*?class="book-meta">(.*?)</p>', data["results"], re.S)
        if not items:
            return
        projects = []
        for url, title, meta in items:
            parts = [p.strip() for p in meta.split("|")]
            projects.append({"url": url, "title": html.unescape(re.sub(r"<[^>]+>", "", title)),
                             "type": parts[1] if len(parts) > 1 else "", "language": parts[-1]})
        yield page, projects
        pages = [int(n) for n in re.findall(r'data-page_number="(\d+)"', data["pagination"])]
        if page >= max(pages, default=1):
            return
        page += 1


def file_urls(link, play):
    """(128 kbps URL, 64 kbps URL) for a section, judged by file name; either may be None.
    The chapter link is usually *_128kb.mp3 and the play link *_64kb.mp3; each name is derived from the other."""
    url128 = link if link.endswith("_128kb.mp3") else None
    url64 = play if play and play.endswith("_64kb.mp3") else None
    if not url128 and url64:
        url128 = url64[:-len("_64kb.mp3")] + "_128kb.mp3"
    if not url64 and url128:
        url64 = url128[:-len("_128kb.mp3")] + "_64kb.mp3"
    return url128, url64


def read_project(url, project_id=None, title=None):
    """Prefer official API data, using HTML only to resolve an unknown ID or as a fallback."""
    page = None
    try:
        if not project_id and not title:
            page = get(url)
            project_id = texts.source_info(page)["project_id"]
        return api.sections(api.project(get, url, project_id, title), file_urls)
    except Exception as e:
        sections = read_project_html(url, page)
        for section in sections:
            section["source"].update(metadata_source="html", api_error=str(e))
        return sections


def read_project_html(url, page=None):
    """Fallback for unavailable/incomplete API records; the original page-based section parser."""
    page = get(url) if page is None else page
    source = texts.source_info(page)
    table = re.search(r'<table class="chapter-download">(.*?)</table>', page, re.S)
    sections = []
    for row in re.findall(r"<tr>(.*?)</tr>", table.group(1) if table else "", re.S):
        link = re.search(r'<a href="([^"]+)" class="chapter-name">(.*?)</a>', row, re.S)
        if not link:
            continue  # header row
        play = re.search(r'<a href="([^"]+)" class="play-btn">', row)
        time_ = re.findall(r"<td>\s*(\d+:\d\d(?::\d\d)?)\s*</td>", row)
        url128, url64 = file_urls(link.group(1), play.group(1) if play else None)
        sections.append({
            "source": source,
            "title": html.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip(),
            "readers": sorted(set(re.findall(r"librivox\.org/reader/(\d+)", row))),
            "seconds": hms(time_[-1]) if time_ else None,
            "url128": url128, "url64": url64,
        })
    return sections


def pick_section(solo, lo, hi):
    """The first section in [lo, hi] seconds; else the one closest to that range."""
    for s in solo:
        if lo <= s["seconds"] <= hi:
            return s, True
    return min(solo, key=lambda s: lo - s["seconds"] if s["seconds"] < lo else s["seconds"] - hi), False


def check(project, rid, args):
    """(candidate dict, None), or (None, why not)."""
    sections = read_project(project["url"], project.get("project_id"), project.get("title"))
    if not sections:
        return None, "no section table"
    if not any(s["readers"] for s in sections):
        return None, "sections don't list individual readers"
    solo = [s for s in sections if s["readers"] == [rid]]
    if not solo:
        shared = sum(rid in s["readers"] for s in sections)
        return None, ("not listed as a reader of any section" if not shared else
                      f"no solo sections ({shared} shared with other readers)")
    solo = [s for s in solo if (s["seconds"] or 0) >= args.min_seconds and (s["url128"] or s["url64"])]
    if not solo:
        return None, f"no solo section of at least {args.min_seconds:g} s with a file"
    section, in_range = pick_section(solo, args.range[0] * 60, args.range[1] * 60)
    return {**project, "sections_total": len(sections), "solo_sections": len(solo),
            "source": section.get("source", {}),
            "section": {k: section[k] for k in ("title", "seconds", "url128", "url64")},
            "in_range": in_range, "quality": "128" if section["url128"] else "64",
            "found_at": now(), "decision": None, "decided_at": None, "download": None}, None


# ---------------------------------------------------------------- downloads

def download(url, dest):
    """Fetch url to dest via a .part file, so an existing dest is always complete."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
        expected = int(r.headers.get("Content-Length") or 0)
        while chunk := r.read(1 << 20):
            f.write(chunk)
    size = part.stat().st_size
    if expected and size != expected:
        part.unlink()
        raise IOError(f"got {size} bytes, expected {expected}")
    part.replace(dest)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def project_slug(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# ---------------------------------------------------------------- shared state

def is_prime(c):
    """Unchecked text is provisional for selection; completed audio must have text to be premium."""
    text = c.get("text") or {}
    text_ok = (not c.get("text_required", False) or text.get("status") == "done" or
               ((c.get("download") or {}).get("status") != "done" and
                (not text or c.get("text_retry_pending"))))
    quality = (c.get("download") or {}).get("quality", c["quality"])
    return quality == "128" and c["in_range"] and text_ok


class State:
    """Everything the page shows, guarded by one lock and saved to state.json on each change."""

    def __init__(self, args, rid, out):
        self.args, self.rid, self.out = args, rid, out
        self.path = out / "state.json"
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.collecting = False
        self.target = args.projects
        self.want_downloads = 0
        self.queue = []  # project URLs to download one by one, from the per-row buttons
        self.status = "starting"
        self.scan_done = False  # the listing is exhausted (or the scan stopped): no more candidates will come
        self.page = 0
        self.checked = {}  # project URL -> {title, type, reason}; reason None for candidates
        self.candidates = []
        self.extra = {}
        self.updated_at = now()
        self.text_attempted = set()  # retry each candidate at most once per collection pass
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.extra = saved
            self.updated_at = saved.get("updated_at", now())
            self.checked, self.candidates = saved["checked"], saved["candidates"]
            self.target = max(self.target, saved.get("target", 0))
            self.want_downloads = saved.get("want_downloads", 0)  # the last "Download N"
            self.queue = list(dict.fromkeys(saved.get("queue", [])))
            for c in self.candidates:  # also recover requests from older state files without a queue
                if c["download"] and c["download"]["status"] in ("queued", "downloading"):
                    if c["download"].get("individual", True):
                        if c["url"] not in self.queue:
                            self.queue.append(c["url"])
                        c["download"] = {"status": "queued", "at": now()}
                    else:
                        c["download"] = None  # the saved bulk target selects it again, prime first
            if self.reconcile_downloads():
                self.save()
        for c in self.candidates:
            c["text_required"] = getattr(args, "download_texts", True)
            if (c.get("text") or {}).get("status") == "done" and not texts.text_present(self.out, c):
                c["text"] = {**c["text"], "status": "missing", "reason": "Cached source text is missing"}
        self.reset_text_attempts()
        self.collecting = self.want_downloads > 0 and not self.collection_satisfied()

    def record(self):
        """Full state record, with unknown saved metadata preserved. Called with the lock held."""
        return {**self.extra, "reader": self.args.name, "reader_id": self.rid, "updated_at": self.updated_at, "target": self.target,
                "want_downloads": self.want_downloads, "queue": self.queue,
                "status": self.status, "page": self.page,
                "selection": selection_options(self.args),
                "download_texts": getattr(self.args, "download_texts", True),
                "checked": self.checked, "candidates": self.candidates}

    def save(self):
        self.out.mkdir(parents=True, exist_ok=True)
        self.updated_at = now()
        data = self.record()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def find(self, url):
        if not isinstance(url, str):
            return None
        return next((c for c in self.candidates if api.project_key(c["url"]) == api.project_key(url)), None)

    def goal(self):
        """Prime candidates the scan aims for: the target, or more if "Download N" asks for more."""
        return max(self.target, self.want_downloads)

    def good_prime(self):
        return sum(is_prime(c) and c.get("scan_eligible", True) and c["decision"] != "reject" for c in self.candidates)

    def downloaded(self):
        return sum(bool(c["download"]) and c["download"]["status"] == "done" and c["decision"] != "reject"
                   for c in self.candidates)

    def premium_downloaded(self):
        return sum(bool(c["download"]) and c["download"]["status"] == "done" and
                   c["decision"] != "reject" and is_prime(c) for c in self.candidates)

    def collection_satisfied(self):
        if any(c.get("text_required") and c["decision"] != "reject" and
               (c.get("download") or {}).get("status") == "done" and
               c["url"] not in self.text_attempted and not texts.text_present(self.out, c)
               for c in self.candidates):
            return False  # give existing audio one text retry, even if fallbacks already fill the target
        return (self.premium_downloaded() >= self.want_downloads or
                (self.scan_done and self.downloaded() >= self.want_downloads))

    def reset_text_attempts(self):
        self.text_attempted.clear()
        for c in self.candidates:
            if c.get("text_required") and not texts.text_present(self.out, c):
                c["text_retry_pending"] = True

    def reconcile_downloads(self):
        """Keep completion honest without removing the saved path, timestamp or decisions. Lock held."""
        changed = False
        for c in self.candidates:
            d = c["download"]
            if d and d["status"] == "done" and not (self.out / d["file"]).is_file():
                d.update(status="missing", error="Downloaded file is missing; download again to restore it.")
                changed = True
            if (c.get("text") or {}).get("status") == "done" and not texts.text_present(self.out, c):
                c["text"] = {**c["text"], "status": "missing", "reason": "Cached source text is missing"}
                changed = True
        return changed

    def enqueue(self, c):
        """An individual request stays in the saved queue until its transfer finishes. Lock held."""
        self.reconcile_downloads()
        d = c["download"]
        if not c.get("scan_eligible", True) or c["decision"] == "reject" or (d and d["status"] == "downloading"):
            return
        if d and d["status"] == "done" and d["quality"] == c["quality"]:
            return
        if c["url"] not in self.queue:
            self.queue.append(c["url"])
        c["download"] = {"status": "queued", "at": now()}

    def snapshot(self):
        """The page's view of the state, as JSON (serialized under the lock, since the threads mutate it)."""
        with self.lock:
            if self.reconcile_downloads():
                self.save()
            return json.dumps({"reader": self.args.name, "reader_url": self.args.url, "status": self.status, "page": self.page,
                    "checked": len(self.checked), "target": self.goal(), "good_prime": self.good_prime(),
                    "want_downloads": self.want_downloads, "downloaded": self.downloaded(),
                    "default_n": self.args.count, "range": self.args.range, "out": str(self.out.resolve()),
                    "candidates": [{**c, "prime": is_prime(c)} for c in self.candidates],
                    "skips": [{"url": u, **v} for u, v in self.checked.items() if v["reason"]]},
                              ensure_ascii=False)

    def mark_128_missing(self, c, why):
        """Record a failed attempt, not proof the file is absent. Allow the user to retry."""
        if c["section"]["url64"]:
            c["quality"] = "64"
        c["missing_128"] = {"why": why, "at": now()}


def selection_options(args):
    """Selection settings recorded so batch resumption can detect incompatible saved checks."""
    return {"language": getattr(args, "language", "English"), "range_minutes": args.range,
            "min_seconds": getattr(args, "min_seconds", 60), "order": getattr(args, "order", "alpha")}


def scan_project(st, p, refresh=False):
    """Check and record one project using the same rules in interactive and batch modes. Lock not held."""
    with st.lock:
        if p["url"] in st.checked and not refresh:
            return
        old = st.find(p["url"])
        if old and (old.get("source") or {}).get("project_id"):
            p = {**p, "project_id": old["source"]["project_id"]}
    if p["type"] == "Dramatic":
        reason = "dramatic reading"
    elif st.args.language and p["language"] != st.args.language:
        reason = f"language: {p['language']}"
    else:
        try:
            cand, reason = check(p, st.rid, st.args)
        except Exception as e:
            cand, reason = None, f"error: {e}"
    with st.lock:
        st.checked[p["url"]] = {"title": p["title"], "type": p["type"], "reason": reason}
        if not reason:
            cand["text_required"] = getattr(st.args, "download_texts", True)
            if old and (old.get("download") or old.get("decision")):
                # An existing choice must not silently become a different chapter/recording.
                old["last_scan"] = {"at": now(), "reason": None, "source": cand["source"],
                                    "section": cand["section"]}
                if not (old.get("source") or {}).get("url_text_source"):
                    old["source"] = cand["source"]
                old["scan_eligible"] = True
            elif old:
                # Retain a cached book if the refreshed unreviewed section uses the same source.
                if (old.get("source") or {}).get("gutenberg_id") == cand["source"].get("gutenberg_id") and old.get("text"):
                    cand["text"] = old["text"]
                else:
                    old.pop("text", None)
                old.update(cand)
                old.pop("missing_128", None)
                old.pop("text_retry_pending", None)
                old["scan_eligible"] = True
                old["last_scan"] = {"at": now(), "reason": None}
            else:
                st.candidates.append(cand)
        elif old:
            old["last_scan"] = {"at": now(), "reason": reason}
            if not reason.startswith("error:"):
                old["scan_eligible"] = False
        st.save()
    st.wake.set()


def rescan_reader(st, stop, timeout_minutes=60):
    """Fresh bounded metadata pass, preserving recorded choices/files and never downloading media."""
    deadline = time.monotonic() + timeout_minutes * 60
    with st.lock:
        st.checked.clear()
        st.page, st.scan_done, st.collecting = 0, False, False
        st.status = "rescanning"
        started = now()
        st.extra["last_rescan"] = {"started_at": started, "status": "rescanning"}
        st.save()
    found, seen = 0, set()
    status, detail = "rescanned", "listing exhausted"
    exhausted = False
    try:
        for page, projects in listing_pages(st.rid, st.args.order):
            with st.lock:
                st.page = page
            for p in projects:
                if stop.is_set():
                    status, detail = "scan paused", "resume with Rescan to start again from the first page"
                    break
                if time.monotonic() >= deadline:
                    status, detail = "scan incomplete", "reader time budget exceeded"
                    break
                if p["url"] in seen:
                    continue
                seen.add(p["url"])
                scan_project(st, p, refresh=True)
                with st.lock:
                    c = st.find(p["url"])
                    found += bool(c and not st.checked[p["url"]]["reason"] and c["decision"] != "reject" and is_prime(c))
                    enough = found >= st.goal()
                if enough:
                    detail = "candidate target reached"
                    break
            else:
                continue
            break
        else:
            exhausted = True
    except Exception as e:
        status, detail = "scan failed", str(e)
    with st.lock:
        errors = sum(bool(v.get("reason")) and v["reason"].startswith("error:") for v in st.checked.values())
        if errors and status == "rescanned":
            status = "scan incomplete"
            detail += f"; {errors} project checks failed"
        st.scan_done = exhausted
        st.status = status
        st.extra["last_rescan"] = {"started_at": started, "finished_at": now(), "status": status,
                                   "detail": detail, "checked": len(st.checked)}
        st.save()
    return {"status": status, "detail": detail}


def scanner(st):
    """Read the listing and check projects while there are fewer than `target` prime candidates."""
    args = st.args
    try:
        for page, projects in listing_pages(st.rid, args.order):
            with st.lock:
                st.page = page
            for p in projects:
                if st.stop.is_set():
                    return
                while True:  # wait while there are enough; a reject or "scan more" wakes this up
                    if st.stop.is_set():
                        return
                    with st.lock:
                        enough = st.good_prime() >= st.goal()
                        st.status = "paused: enough candidates" if enough else "scanning"
                    if not enough:
                        break
                    st.wake.wait(2)
                    st.wake.clear()
                scan_project(st, p)
        with st.lock:
            st.status = "done: listing exhausted"
    except Exception as e:
        with st.lock:
            st.status = f"stopped: {e}"
    with st.lock:
        st.scan_done = True
    st.wake.set()


def next_download(st):
    """The next candidate to download, or None. Called with the lock held."""
    st.reconcile_downloads()
    while st.queue:
        c = st.find(st.queue[0])
        if c and c.get("scan_eligible", True) and c["decision"] != "reject" and not (c["download"] and c["download"]["status"] == "done"):
            return c
        st.queue.pop(0)
    if st.collection_satisfied():
        return None
    pending = [c for c in st.candidates if c.get("scan_eligible", True) and c["decision"] != "reject" and
               (not c["download"] or c["download"]["status"] == "missing")]
    for c in pending:
        if is_prime(c):
            return c
    if not st.scan_done:
        return None  # more prime candidates may still turn up; backups only once the listing is exhausted
    return pending[0] if pending else None


def prepare_text(st, c):
    """No state lock during I/O; only attach provenance/text, preserving live review decisions."""
    source = c.get("source") or {}
    if not source or not source.get("project_id"):
        try:
            sections = read_project(c["url"], source.get("project_id"), c.get("title"))
            source = sections[0]["source"] if sections else source
        except Exception as e:
            result = {"status": "failed", "reason": f"Source lookup failed: {e}"}
        else:
            result = texts.fetch_book(source, st.out, getattr(st.args, "text_mirror", texts.DEFAULT_MIRROR))
    else:
        result = texts.fetch_book(source, st.out, getattr(st.args, "text_mirror", texts.DEFAULT_MIRROR))
    with st.lock:
        c["source"], c["text"] = source, result
        c.pop("text_retry_pending", None)
        st.text_attempted.add(c["url"])
        st.save()
    st.wake.set()


def download_next(st, cancelled=None, individual_only=False):
    """Perform one transfer. Return False when idle; the worker waits between attempts."""
    with st.lock:
        st.reconcile_downloads()
        existing = next((c for c in st.candidates if c.get("text_required") and c["decision"] != "reject"
                         and (not individual_only or c["url"] in st.queue)
                         and (c.get("download") or {}).get("status") == "done"
                         and c["url"] not in st.text_attempted and not texts.text_present(st.out, c)), None)
    if existing:
        prepare_text(st, existing)
        return True
    with st.lock:
        c = next_download(st)
        if not c:
            return False
        needs_text = c.get("text_required") and c["url"] not in st.text_attempted
    if needs_text:
        prepare_text(st, c)
        with st.lock:
            if c["decision"] == "reject" or (not is_prime(c) and c["url"] not in st.queue and not st.scan_done):
                return True  # keep searching before downloading a known backup
    with st.lock:
        if c["decision"] == "reject" or st.stop.is_set() or (cancelled and cancelled(c)):
            return True
        quality = c["quality"]  # playback controls may change the candidate during the transfer
        individual = c["url"] in st.queue
        c["download"] = {"status": "downloading", "individual": individual, "at": now()}
        st.save()  # persist intent before starting network I/O, including bulk transfers
    try:
        url = c["section"]["url128"] if quality == "128" else c["section"]["url64"]
        file = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
        folder = st.out / project_slug(c["url"])
        download(url, folder / file)
        result = {"status": "done", "quality": quality, "file": str(Path(project_slug(c["url"])) / file),
                  "at": now()}
    except Exception as e:
        result = {"status": "failed", "error": str(e), "at": now()}
    with st.lock:
        fallback = (result["status"] == "failed" and quality == "128" and
                    c["section"]["url64"] and c["decision"] != "reject")
        if result["status"] == "failed" and quality == "128":
            st.mark_128_missing(c, result["error"])
        if fallback:
            # Individual requests retry immediately; bulk backups keep their existing selection order.
            result = {"status": "queued", "at": now()} if individual else None
        elif result["status"] == "done" and quality == "128":
            c["quality"] = "128"
            c.pop("missing_128", None)
        if not fallback and c["url"] in st.queue:
            st.queue.remove(c["url"])
        c["download"] = result
        st.save()
    st.wake.set()
    return True


def downloader(st):
    while not st.stop.is_set():
        with st.lock:
            st.reconcile_downloads()
            if st.collecting and st.collection_satisfied():
                st.collecting = False
            working = st.collecting or bool(st.queue)
        if not working or not download_next(st, cancelled=lambda c: not st.collecting and c["url"] not in st.queue):
            st.wake.wait(2)
            st.wake.clear()


# ---------------------------------------------------------------- shared dashboard

def make_handler(st):
    """Single-reader API compatibility, using the shared dashboard and review controls."""
    from librivox_dashboard import Dashboard, make_handler as dashboard_handler
    return dashboard_handler(Dashboard.for_interactive(st))


class LocalServer(ThreadingHTTPServer):
    """Fail on an occupied port, including on Windows, before starting any background work."""

    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="the reader's name, used for the output folder")
    ap.add_argument("url", help="the reader's LibriVox page, e.g. https://librivox.org/reader/6281/")
    ap.add_argument("--projects", type=int, default=20, help="candidate projects to find (default 20)")
    ap.add_argument("--count", type=int, default=10, help="the page's default N for 'Download N' (default 10)")
    ap.add_argument("--range", type=float, nargs=2, default=[5, 15], metavar=("MIN", "MAX"),
                    help="preferred section length in minutes (default 5 15)")
    ap.add_argument("--min-seconds", type=float, default=60, help="never offer a section shorter than this")
    ap.add_argument("--out", default=None, help="output folder (default: downloads/<name> next to this script)")
    ap.add_argument("--order", choices=["alpha", "catalog_date"], default="alpha", help="listing order")
    ap.add_argument("--language", default="English", help="only projects in this language ('' for any)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-download-texts", dest="download_texts", action="store_false",
                    help="audio-only collection; do not prefer recordings with source text")
    ap.add_argument("--text-mirror", default=texts.DEFAULT_MIRROR, help="Gutenberg mirror with generated UTF-8 files")
    args = ap.parse_args()
    try:
        texts.validate_mirror(args.text_mirror)
    except ValueError as e:
        ap.error(str(e))

    rid = reader_id(args.url)
    out = Path(args.out or Path(__file__).parent / "downloads" / slug(args.name))
    import librivox_launch as batch
    from librivox_dashboard import Dashboard, serve_dashboard
    job = {**batch.DEFAULTS, "reader_id": rid, "url": args.url, "name": args.name,
           "name_source": "explicit", "out": str(out), "count": args.count, "projects": args.projects,
           "range_minutes": args.range, "min_seconds": args.min_seconds, "order": args.order,
           "language": args.language, "download_texts": args.download_texts, "text_mirror": args.text_mirror}
    # Compatibility launch: the same controller and controls as a JSON session, metadata only at startup.
    serve_dashboard(Dashboard(jobs=[job]), args.port, browse=True)


if __name__ == "__main__":
    sys.modules.setdefault("librivox_fetch", sys.modules[__name__])
    main()
