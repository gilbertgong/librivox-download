"""Official catalog API adapter. Reader discovery still needs the reader listing.

https://librivox.org/api/info
No upstream code is vendored here.
"""
import html
import json
import math
import re
import urllib.parse

import librivox_text as texts

ENDPOINT = "https://librivox.org/api/feed/audiobooks/"
PAGE_SIZE = 10


def project_key(url):
    p = urllib.parse.urlsplit(url or "")
    return ((p.hostname or "").removeprefix("www.").lower(), p.path.rstrip("/"))


def project(get, url, project_id=None, title=None, fields=None):
    """Resolve an exact project URL, never choose a recording solely by its book title."""
    if not project_id and not title:
        raise LookupError("Need a project ID or title for API lookup")
    offset = 0
    while True:
        params = {"format": "json", "extended": 1, "limit": PAGE_SIZE,
                  "fields": fields or "{id,title,url_librivox,url_text_source,num_sections,sections}"}
        if project_id:
            params["id"] = project_id
        else:
            params.update(title=title, offset=offset)
        data = json.loads(get(ENDPOINT + "?" + urllib.parse.urlencode(params)))
        books = data.get("books") if isinstance(data, dict) else None
        if not isinstance(books, list):
            raise ValueError("API response has no books list")
        for book in books:
            if project_key(book.get("url_librivox")) == project_key(url):
                return book
        if project_id or len(books) < PAGE_SIZE:
            raise LookupError("API search did not contain the exact project URL")
        offset += len(books)


def sections(book, file_urls):
    """Normalize the extended response to the selector's existing section representation."""
    rows = book.get("sections")
    if not isinstance(rows, list) or len(rows) != int(book["num_sections"]):
        raise ValueError("API sections are incomplete")
    if not rows:
        raise ValueError("API project has no sections")
    source = texts.source_record(str(book["id"]), book.get("url_text_source") or None)
    source["metadata_source"] = "api"
    result = []
    for row in sorted(rows, key=lambda s: int(s["section_number"])):
        readers = row["readers"]
        if not isinstance(readers, list):
            raise ValueError("API section readers are missing")
        seconds = float(row["playtime"])
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("API section duration is invalid")
        url128, url64 = file_urls(row.get("listen_url") or "", row.get("listen_url"))
        if not url128 and not url64:
            raise ValueError("API audio URL does not identify a supported quality")
        result.append({"source": source, "title": html.unescape(re.sub(r"<[^>]+>", "", row["title"])).strip(),
                       "readers": sorted(set(str(int(r["reader_id"])) for r in readers)),
                       "seconds": seconds, "url128": url128, "url64": url64})
    return result
