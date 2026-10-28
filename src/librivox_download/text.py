"""Source-book provenance and shared Gutenberg text cache (standard library only).

Mirror policy/list: https://www.gutenberg.org/policy/robot_access.html
https://www.gutenberg.org/MIRRORS.ALL
The generated UTF-8 collection uses cache/epub/ID/pgID.txt. Never scrape the main site.
"""
import hashlib
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_MIRROR = "https://gutenberg.pglaf.org"
DELAY = 2.0
_lock = threading.Lock()
_last_request = 0.0


def validate_mirror(url):
    if not isinstance(url, str):
        raise ValueError("text_mirror must be an HTTP(S) mirror URL")
    p = urllib.parse.urlsplit(url)
    if (p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or
            p.query or p.fragment or p.hostname.lower() in ("gutenberg.org", "www.gutenberg.org")):
        raise ValueError("text_mirror must be an HTTP(S) mirror URL, not the main Gutenberg website")
    return url.rstrip("/")


def gutenberg_id(url):
    p = urllib.parse.urlsplit(url or "")
    if p.hostname not in ("gutenberg.org", "www.gutenberg.org"):
        return None
    m = re.match(r"/(?:ebooks|etext|files|cache/epub)/(\d+)(?:\D|$)", p.path)
    return str(int(m[1])) if m and int(m[1]) > 0 else None


def source_record(project_id, url):
    gid = gutenberg_id(url)
    return {"project_id": project_id, "url_text_source": url, "gutenberg_id": gid,
            "gutenberg_url": f"https://www.gutenberg.org/ebooks/{gid}" if gid else None}


def source_info(page):
    """The page's Online text link is the API's url_text_source; RSS identifies its project."""
    source = None
    for href, label in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
        if re.sub(r"<[^>]+>", "", html.unescape(label)).strip().lower() == "online text":
            source = html.unescape(href)
            break
    project = re.search(r'https?://(?:www\.)?librivox\.org/rss/(\d+)', page)
    return source_record(project[1] if project else None, source)


def cache_path(reader_out, gid):
    if not re.fullmatch(r"[1-9][0-9]*", str(gid)):
        return None
    return Path(reader_out).parent / "texts" / "gutenberg" / str(gid) / "source.txt"


def text_present(reader_out, candidate):
    text = candidate.get("text") or {}
    path = cache_path(reader_out, (candidate.get("source") or {}).get("gutenberg_id"))
    return path if text.get("status") == "done" and path and path.is_file() else None


class MirrorRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_mirror(newurl)  # refuse redirects to the main site before making a request there
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_book(source, reader_out, mirror=DEFAULT_MIRROR):
    """Return a status record. Failures never prevent audio collection. Cache writes are atomic."""
    global _last_request
    gid = source.get("gutenberg_id")
    dest = cache_path(reader_out, gid)
    if dest is None:
        return {"status": "unsupported" if source.get("url_text_source") else "missing",
                "reason": "Source is not a recognized Gutenberg URL" if source.get("url_text_source") else "No online text link"}
    url = validate_mirror(mirror) + f"/cache/epub/{gid}/pg{gid}.txt"
    metadata = dest.with_name("source.json")
    try:
        with _lock:
            if dest.exists():
                record = json.loads(metadata.read_text(encoding="utf-8"))
                if record.get("gutenberg_id") != gid or record.get("sha256") != hashlib.sha256(dest.read_bytes()).hexdigest():
                    raise ValueError("Existing text cache failed its provenance/checksum check; preserved for inspection")
            else:
                time.sleep(max(0, DELAY - (time.monotonic() - _last_request)))
                _last_request = time.monotonic()
                req = urllib.request.Request(url, headers={"User-Agent": "librivox-download (source-text collection)"})
                opener = urllib.request.build_opener(MirrorRedirectHandler())
                with opener.open(req, timeout=60) as response:
                    actual = response.geturl()
                    validate_mirror(actual)
                    if response.headers.get_content_type() != "text/plain":
                        raise ValueError("Mirror did not return plain text")
                    payload = response.read()
                    expected = int(response.headers.get("Content-Length") or 0)
                if expected and len(payload) != expected:
                    raise IOError("Incomplete source-text download")
                decoded = payload.decode("utf-8-sig")
                if "project gutenberg" not in decoded[:4096].lower() or decoded.lstrip().startswith("<"):
                    raise ValueError("Mirror response is not a recognizable Gutenberg UTF-8 text")
                record = {"gutenberg_id": gid, "gutenberg_url": source.get("gutenberg_url"),
                          "download_url": actual, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_suffix(".txt.part")
                part.write_bytes(payload)  # retain the original bytes, including header/footer
                meta_part = metadata.with_suffix(".json.part")
                meta_part.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
                part.replace(dest)
                meta_part.replace(metadata)
            return {**record, "status": "done", "file": f"../texts/gutenberg/{gid}/source.txt"}
    except Exception as e:
        return {"status": "failed", "reason": str(e), "attempted_url": url}
