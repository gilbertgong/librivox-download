"""Project-oriented library. Sampling state is never used as a whole-book download manifest.

Metadata: https://librivox.org/api/info (extended audiobooks, exact catalog URL identity).
"""
import copy
import hashlib
import html
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path

import librivox_fetch as app

FIELDS = "{id,title,authors,language,genres,url_librivox,url_text_source,num_sections,sections}"


def project_url(value):
    if not isinstance(value, str):
        raise ValueError("enter a LibriVox project URL")
    p = urllib.parse.urlsplit(value.strip())
    if (p.scheme not in ("http", "https") or p.netloc.lower() not in ("librivox.org", "www.librivox.org")
            or not re.fullmatch(r"/[a-zA-Z0-9][a-zA-Z0-9_-]*/?", p.path)
            or p.path.strip("/").lower() in ("reader", "api", "rss", "search")):
        raise ValueError("expected a LibriVox catalog project URL")
    return "https://librivox.org/" + p.path.strip("/") + "/"


def identity(url):
    return hashlib.sha256(project_url(url).encode()).hexdigest()[:16]


def clean(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()


def details(project):
    """Get all sections, including shared casts, short sections and every language."""
    url, page = project_url(project["url"]), None
    pid = (project.get("source") or {}).get("project_id")
    try:
        if not pid and not project.get("title"):
            page = app.get(url)
            pid = app.texts.source_info(page)["project_id"]
        book = app.api.project(app.get, url, pid, project.get("title"), fields=FIELDS)
        rows = app.api.sections(book, app.file_urls)
        authors = [clean(" ".join(str(a.get(k) or "") for k in ("first_name", "last_name")))
                   for a in book.get("authors", [])]
        reader_names = {}
        for section in book["sections"]:
            for reader in section["readers"]:
                rid = str(int(reader["reader_id"]))
                reader_names[rid] = clean(reader.get("display_name")) or clean(" ".join(str(reader.get(k) or "") for k in ("first_name", "last_name"))) or f"Reader {rid}"
        genres = [clean(g.get("name")) for g in book.get("genres", [])]
        return {"url": url, "title": clean(book["title"]), "authors": [a for a in authors if a],
                "language": clean(book.get("language")) or project.get("language", "Unknown"),
                "type": "Dramatic" if any("dramatic" in g.lower() for g in genres) else project.get("type", "Unknown"),
                "genres": genres, "reader_names": reader_names, "sections": rows,
                "source": rows[0]["source"], "metadata_status": "ready"}
    except Exception as error:
        page = page if page is not None else app.get(url)
        rows = app.read_project_html(url, page)
        if not rows:
            raise ValueError(f"No downloadable section metadata: {error}") from error
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        return {"url": url, "title": project.get("title") or (clean(title[1]).removesuffix(" | LibriVox") if title else app.project_slug(url)),
                "authors": [], "language": project.get("language", "Unknown"),
                "type": project.get("type", "Unknown"), "reader_names": {}, "sections": rows,
                "source": {**rows[0]["source"], "metadata_source": "html", "api_error": str(error)},
                "metadata_status": "ready"}


class Library:
    def __init__(self, output_root):
        self.root = Path(output_root).resolve() / "projects"
        self.path = self.root / "catalog.json"
        self.lock = threading.RLock()
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"projects": {}, "scans": {}, "include_dramatic": False}

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = app.now()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(self.path)

    def options(self, include):
        if not isinstance(include, bool):
            raise ValueError("include_dramatic must be true or false")
        with self.lock:
            self.data["include_dramatic"] = include
            self.save()

    def file(self, key, number):
        with self.lock:
            rows = self.data["projects"][key]["sections"]
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(rows):
                raise ValueError("unknown section")
            section = rows[number - 1]
            d = section.get("download") or {}
            if d.get("status") != "done" or not d.get("file"):
                return None
            path = (self.root / d["file"]).resolve()
            return path if path.is_relative_to(self.root / key) and path.is_file() else None

    def text_file(self, key):
        with self.lock:
            path = app.texts.text_present(self.root, self.data["projects"][key])
            root = self.root.parent / "texts" / "gutenberg"
            return path if path and path.resolve().is_relative_to(root) else None

    def snapshot(self, active=False):
        with self.lock:
            result = copy.deepcopy(self.data)
            if not active:
                for scan in result["scans"].values():
                    if scan.get("status") == "scanning":
                        scan["status"] = "interrupted"
            for key, project in result["projects"].items():
                for section in project.get("sections", []):
                    present = self.file(key, section["number"])
                    d = section.get("download") or {}
                    section["status"] = "missing" if d.get("status") == "done" and not present else d.get("status", "pending")
                    if not active and section["status"] == "downloading":
                        section["status"] = "interrupted"
                    section["audio_url"] = ("/project-media?" + urllib.parse.urlencode({"project": key, "section": section["number"]})) if present else None
                project["downloaded"] = sum(s["status"] == "done" for s in project.get("sections", []))
                project["seconds"] = sum(s.get("seconds") or 0 for s in project.get("sections", []))
                if not active and (project.get("download_request") or {}).get("status") == "downloading":
                    project["download_request"]["status"] = "interrupted"
                project["text_url"] = "/project-text?" + urllib.parse.urlencode({"project": key}) if self.text_file(key) else None
            result["out"] = str(self.root)
            return result

    def inspect(self, project, reader=None, include=False, refresh=False):
        key = identity(project["url"])
        with self.lock:
            old = self.data["projects"].get(key, {})
            readers = sorted(set(old.get("discovered_readers", []) + ([reader] if reader else [])))
            seed = {**old, **project, "url": project_url(project["url"]), "discovered_readers": readers}
            if "dramatic" in str(seed.get("type", "")).lower():
                seed["type"] = "Dramatic"
            if seed.get("type") == "Dramatic" and not include:
                self.data["projects"][key] = {**seed, "id": key, "metadata_status": old.get("metadata_status", "excluded"),
                                               "sections": old.get("sections", [])}
                self.save()
                return
            if old.get("metadata_status") == "ready" and not refresh:
                old["discovered_readers"] = readers
                self.save()
                return
        try:
            loaded = details(seed)
            fresh = loaded.pop("sections")
            previous = old.get("sections", [])
            audio_keys = lambda rows: [(s.get("url128"), s.get("url64")) for s in rows]
            protected = any((s.get("download") or {}).get("status") in ("done", "downloading", "queued") for s in previous)
            changed = protected and audio_keys(previous) != audio_keys(fresh)
            sections = []
            for number, row in enumerate(fresh, 1):
                old_section = next((s for s in old.get("sections", []) if s.get("url128") == row["url128"] and s.get("url64") == row["url64"]), {})
                sections.append({**row, "number": number, "download": old_section.get("download")})
            if changed:
                sections = previous
                loaded["source"] = old.get("source", loaded["source"])
                loaded["last_scan"] = {"at": app.now(), "sections": fresh}
                loaded["metadata_note"] = "The catalog's audio list changed. Saved section selection is preserved; use a different output root to collect the revised edition."
            loaded.update(id=key, sections=sections, discovered_readers=readers, error=None)
        except Exception as error:
            loaded = {**seed, "id": key, "metadata_status": "failed", "error": str(error), "sections": old.get("sections", [])}
        with self.lock:
            self.data["projects"][key] = {**old, **loaded}
            self.save()

    def scan(self, rid, stop, include=False, timeout_minutes=60):
        deadline = time.monotonic() + timeout_minutes * 60
        status, seen = "scanning", set()
        self.options(include)
        def progress(detail):
            with self.lock:
                self.data["scans"][rid] = {"status": status, "detail": detail, "checked": len(seen), "include_dramatic": include}
                self.save()
        progress("Reading all projects for this reader")
        try:
            for page, projects in app.listing_pages(rid, "alpha"):
                for project in projects:
                    if stop.is_set() or time.monotonic() >= deadline:
                        status = "paused" if stop.is_set() else "scan incomplete"
                        progress("Stopped between projects; scan again to continue using cached metadata")
                        return
                    key = identity(project["url"])
                    if key in seen:
                        continue
                    seen.add(key)
                    self.inspect(project, rid, include)
                    progress(f"Page {page}: {project['title']}")
            with self.lock:
                errors = sum(self.data["projects"][key].get("metadata_status") == "failed" for key in seen)
            status = "scan incomplete" if errors else "complete"
            progress(f"Listing exhausted; {errors} project metadata errors" if errors else "All listed projects checked")
        except Exception as error:
            status = "scan failed"
            progress(str(error))

    def download(self, key, reader, stop, download_texts=True, mirror=app.texts.DEFAULT_MIRROR):
        with self.lock:
            project = self.data["projects"][key]
            if project.get("metadata_status") != "ready":
                raise ValueError("load project metadata before downloading")
            sections = [s for s in project["sections"] if reader is None or reader in s["readers"]]
            if not sections:
                raise ValueError("this reader is not credited on any section")
            project["download_request"] = {"reader": reader, "status": "downloading", "sections": [s["number"] for s in sections]}
            self.save()
        if download_texts and not stop.is_set():
            text = app.texts.fetch_book(project.get("source", {}), self.root, mirror)
            with self.lock:
                project["text"] = text
                self.save()
        for section in sections:
            if stop.is_set():
                break
            if self.file(key, section["number"]):
                continue
            errors = []
            for quality, url in (("128", section.get("url128")), ("64", section.get("url64"))):
                if not url or stop.is_set():
                    continue
                relative = Path(key) / f"{section['number']:04d}_{quality}kb.mp3"
                with self.lock:
                    section["download"] = {"status": "downloading", "quality": quality, "file": relative.as_posix(), "at": app.now()}
                    self.save()
                try:
                    app.download(url, self.root / relative)
                    result = {"status": "done", "quality": quality, "file": relative.as_posix(), "at": app.now()}
                    if errors:
                        result["fallback_reason"] = "; ".join(errors)
                    with self.lock:
                        section["download"] = result
                        self.save()
                    break
                except Exception as error:
                    errors.append(f"{quality} kbps: {error}")
            else:
                with self.lock:
                    section["download"] = {"status": "failed", "error": "; ".join(errors) or "No supported audio URL", "at": app.now()}
                    self.save()
        with self.lock:
            complete = all(self.file(key, s["number"]) for s in sections)
            project["download_request"]["status"] = "complete" if complete else "paused" if stop.is_set() else "incomplete"
            self.save()
