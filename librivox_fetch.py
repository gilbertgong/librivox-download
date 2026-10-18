"""Find a LibriVox reader's solo recordings, one per project, and vet them on a local web page.

    python librivox_fetch.py "Beth Thomas" https://librivox.org/reader/6281/
    then open http://127.0.0.1:8765/

A reader's LibriVox page lists every project they took part in: solo books, collaborative books where they read a
few chapters, dramatic readings (cast performances, skipped), and some they only coordinated. The server reads that
listing a page at a time in the background and checks each project as it comes in. A project is a candidate if a
section's reader list is exactly this reader and the section is at least --min-seconds long. Projects whose pages
don't list readers per section are skipped. Everything is decided from LibriVox's pages, never archive.org.

One section per project is offered: the first one 5-15 minutes long (--range), or, if none is, the one closest to
that range. Its file is the 128 kbps one, judged by name (`*_128kb.mp3`). A 64 kbps file is suboptimal: it's used
only when a section has no 128 kbps name, or the 128 kbps file turns out to be missing (the player can't load it,
or its download fails).

A candidate is prime if its section is in the length range and has a 128 kbps file; otherwise (only 64 kbps, or
no section in range) it's a backup: shown in its own section below the prime ones, not counted toward the goal.
Scanning continues until there are --projects prime candidates that haven't been rejected (or N, if "Download N"
asks for more), so rejecting one makes the scan look further. On the page you can listen, keep, reject, download
one, or "download N": the server downloads, in the background, the first N candidates not rejected, prime first;
a backup is taken only once the listing is exhausted and no prime candidate is left.

Everything lives in <out> (default downloads/<name>): one folder per downloaded project with its MP3, and
state.json, the single record of what's been checked, decided (keep / reject) and downloaded, with the time of each
change. It's rewritten on every change, so a restart resumes where it left off.
"""
import argparse
import html
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
            projects.append({"url": url, "title": html.unescape(title),
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


def read_project(url):
    """The project page's sections: [{title, readers, seconds, url128, url64}]."""
    page = get(url)
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
    sections = read_project(project["url"])
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
    """A candidate that counts toward the goal: a section in the length range, with a 128 kbps file."""
    return c["quality"] == "128" and c["in_range"]


class State:
    """Everything the page shows, guarded by one lock and saved to state.json on each change."""

    def __init__(self, args, rid, out):
        self.args, self.rid, self.out = args, rid, out
        self.path = out / "state.json"
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.target = args.projects
        self.want_downloads = 0
        self.queue = []  # project URLs to download one by one, from the per-row buttons
        self.status = "starting"
        self.scan_done = False  # the listing is exhausted (or the scan stopped): no more candidates will come
        self.page = 0
        self.checked = {}  # project URL -> {title, type, reason}; reason None for candidates
        self.candidates = []
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.checked, self.candidates = saved["checked"], saved["candidates"]
            self.target = max(self.target, saved.get("target", 0))
            self.want_downloads = saved.get("want_downloads", 0)  # the last "Download N"
            for c in self.candidates:  # a download that was running when the server stopped starts over
                if c["download"] and c["download"]["status"] in ("queued", "downloading"):
                    c["download"] = None

    def save(self):
        self.out.mkdir(parents=True, exist_ok=True)
        data = {"reader": self.args.name, "reader_id": self.rid, "updated_at": now(), "target": self.target,
                "want_downloads": self.want_downloads,
                "checked": self.checked, "candidates": self.candidates}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def find(self, url):
        return next((c for c in self.candidates if c["url"] == url), None)

    def goal(self):
        """Prime candidates the scan aims for: the target, or more if "Download N" asks for more."""
        return max(self.target, self.want_downloads)

    def good_prime(self):
        return sum(is_prime(c) and c["decision"] != "reject" for c in self.candidates)

    def downloaded(self):
        return sum(bool(c["download"]) and c["download"]["status"] == "done" and c["decision"] != "reject"
                   for c in self.candidates)

    def snapshot(self):
        """The page's view of the state, as JSON (serialized under the lock, since the threads mutate it)."""
        with self.lock:
            return json.dumps({"reader": self.args.name, "reader_url": self.args.url, "status": self.status, "page": self.page,
                    "checked": len(self.checked), "target": self.goal(), "good_prime": self.good_prime(),
                    "want_downloads": self.want_downloads, "downloaded": self.downloaded(),
                    "default_n": self.args.count, "range": self.args.range, "out": str(self.out.resolve()),
                    "candidates": [{**c, "prime": is_prime(c)} for c in self.candidates],
                    "skips": [{"url": u, **v} for u, v in self.checked.items() if v["reason"]]},
                              ensure_ascii=False)

    def mark_128_missing(self, c, why):
        """The 128 kbps file isn't there: fall back to the 64 kbps one (suboptimal)."""
        c["quality"] = "64"
        c["missing_128"] = {"why": why, "at": now()}


def scanner(st):
    """Read the listing and check projects while there are fewer than `target` prime candidates."""
    args = st.args
    try:
        for page, projects in listing_pages(st.rid, args.order):
            with st.lock:
                st.page = page
            for p in projects:
                while True:  # wait while there are enough; a reject or "scan more" wakes this up
                    with st.lock:
                        enough = st.good_prime() >= st.goal()
                        st.status = "paused: enough candidates" if enough else "scanning"
                    if not enough:
                        break
                    st.wake.wait(2)
                    st.wake.clear()
                with st.lock:
                    if p["url"] in st.checked:
                        continue
                if p["type"] == "Dramatic":
                    reason = "dramatic reading"
                elif args.language and p["language"] != args.language:
                    reason = f"language: {p['language']}"
                else:
                    try:
                        cand, reason = check(p, st.rid, args)
                    except Exception as e:  # one broken project page shouldn't end the scan
                        cand, reason = None, f"error: {e}"
                with st.lock:
                    st.checked[p["url"]] = {"title": p["title"], "type": p["type"], "reason": reason}
                    if not reason:
                        st.candidates.append(cand)
                    st.save()
                st.wake.set()  # the downloader may be waiting for candidates
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
    while st.queue:
        c = st.find(st.queue.pop(0))
        if c and not (c["download"] and c["download"]["status"] == "done"):
            return c
    if st.downloaded() >= st.want_downloads:
        return None
    pending = [c for c in st.candidates if c["decision"] != "reject" and not c["download"]]
    for c in pending:
        if is_prime(c):
            return c
    if not st.scan_done:
        return None  # more prime candidates may still turn up; backups only once the listing is exhausted
    return pending[0] if pending else None


def downloader(st):
    while True:
        with st.lock:
            c = next_download(st)
            if c:
                c["download"] = {"status": "downloading"}
        if not c:
            st.wake.wait(2)
            st.wake.clear()
            continue
        sec = c["section"]
        url = sec["url128"] if c["quality"] == "128" else sec["url64"]
        file = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        folder = st.out / project_slug(c["url"])
        try:
            download(url, folder / file)
            result = {"status": "done", "quality": c["quality"], "file": str(Path(project_slug(c["url"])) / file),
                      "at": now()}
        except Exception as e:
            result = {"status": "failed", "error": str(e), "at": now()}
        with st.lock:
            if result["status"] == "failed" and c["quality"] == "128":
                st.mark_128_missing(c, result["error"])
                result = None  # eligible again, as a 64 kbps candidate
            c["download"] = result
            st.save()
        st.wake.set()


# ---------------------------------------------------------------- web page

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>LibriVox picker</title>
<style>
:root { --bg:#fafaf8; --done-bg:#eaf3fd; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e1dc; --card:#fff; --accent:#2f6fdb;
        --bad:#b3261e; --ok:#1e7a3c; --warn:#9a6700; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --done-bg:#14202e; --fg:#ecebe6; --muted:#9a9993; --line:#33332f; --card:#1f1f1d; --accent:#7aa7ff;
          --bad:#ff8a80; --ok:#6fd08c; --warn:#e3b341; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif; transition:background .6s; }
body.done { background:var(--done-bg); }
#complete { margin:0 0 18px; padding:14px 16px; border:1px solid var(--accent); border-radius:10px;
            background:var(--card); font-size:17px; font-weight:600; }
#complete .muted { display:block; font-size:14px; font-weight:400; margin-top:2px; }
main { max-width:1100px; margin:0 auto; padding:20px 16px 60px; }
h1 { font-size:22px; margin:0 0 4px; }
a { color:var(--accent); }
.muted { color:var(--muted); }
.bar { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; margin:14px 0 18px; padding:12px 14px;
       background:var(--card); border:1px solid var(--line); border-radius:10px; }
.bar b { font-variant-numeric:tabular-nums; }
button { font:inherit; padding:5px 11px; border-radius:7px; border:1px solid var(--line); background:var(--card);
         color:var(--fg); cursor:pointer; }
button:hover { border-color:var(--muted); }
button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
button.keep.on { background:var(--ok); border-color:var(--ok); color:var(--bg); }
button.reject.on { background:var(--bad); border-color:var(--bad); color:var(--bg); }
input[type=number] { width:64px; font:inherit; padding:4px 6px; border-radius:7px; border:1px solid var(--line);
                     background:var(--card); color:var(--fg); }
.card { padding:12px 14px; margin-bottom:10px;
        background:var(--card); border:1px solid var(--line); border-radius:10px; }
.card.rejected { opacity:.45; }
.card.kept { border-color:var(--ok); }
.title { font-weight:600; }
.tag { display:inline-block; font-size:12px; padding:1px 7px; border-radius:99px; border:1px solid var(--line);
       color:var(--muted); margin-left:6px; }
.tag.warn { color:var(--warn); border-color:var(--warn); }
.tag.ok { color:var(--ok); border-color:var(--ok); }
.tag.bad { color:var(--bad); border-color:var(--bad); }
.row { display:flex; gap:8px; align-items:center; margin-top:8px; }
.row audio { flex:1; min-width:0; height:34px; }
.decide, .dl { display:flex; gap:6px; flex-shrink:0; }
h2 { font-size:17px; margin:28px 0 4px; }
details { margin-top:24px; }
details li { margin:2px 0; }
@media (max-width:640px) { .row { flex-wrap:wrap; } .row audio { order:-1; flex-basis:100%; } .dl { margin-left:auto; } }
</style></head>
<body><main>
<h1 id="h"></h1>
<div class="muted" id="sub"></div>
<div class="bar">
  <span id="scan"></span>
  <span>Prime candidates (not rejected): <b id="good"></b> / <b id="target"></b> · backups: <b id="backups"></b></span>
  <span>Kept: <b id="kept"></b> · rejected: <b id="rejected"></b></span>
  <button onclick="post('scan_more', {n: 10})">Scan 10 more</button>
  <span style="flex:1"></span>
  <span>Downloaded: <b id="done"></b></span>
  <input type="number" id="n" min="1"> <button class="primary" onclick="downloadN()">Download N</button>
</div>
<div id="complete" hidden></div>
<p class="muted" id="prime-note"></p>
<p class="muted" id="empty">No prime candidates yet.</p>
<div id="list"></div>
<div id="backup-wrap" hidden>
  <h2>Backups</h2>
  <p class="muted">Only 64 kbps, or no section in the length range. Not counted toward the goal. Downloaded by
    "Download N" only once the listing is exhausted and no prime candidate is left.</p>
  <div id="backup"></div>
</div>
<details><summary class="muted" id="skipsum"></summary><ul id="skips"></ul></details>
</main>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const mins = s => s == null ? "?" : (s / 60).toFixed(1) + " min";
const cards = new Map();  // project URL -> {el, html, src, box}; each card is built once so its player keeps playing
let first = true;

async function post(path, body) {
  await fetch("/api/" + path, {method: "POST", headers: {"Content-Type": "application/json"},
                               body: JSON.stringify(body)});
  refresh();
}
function downloadN() { post("download_n", {n: parseInt($("n").value) || 0}); }

// One handler for every card's buttons, and one for players failing to load (a missing 128 kbps file).
for (const box of [$("list"), $("backup")]) {
  box.addEventListener("click", e => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const url = b.closest(".card").dataset.url;
    if (b.dataset.act === "keep") post("decide", {url, decision: "keep"});
    if (b.dataset.act === "reject") post("decide", {url, decision: "reject"});
    if (b.dataset.act === "undo") post("decide", {url, decision: null});
    if (b.dataset.act === "download") post("download", {url});
  });
  box.addEventListener("error", e => {
    if (e.target.tagName === "AUDIO" && e.target.dataset.q === "128")
      post("missing_128", {url: e.target.closest(".card").dataset.url});
  }, true);
}

// A card's text, its keep / reject buttons (left of the player) and its download button (right of it).
function parts(c) {
  const sec = c.section, d = c.download, rejected = c.decision === "reject", kept = c.decision === "keep";
  const tags = [`<span class="tag">${esc(c.type)}</span>`,
    kept ? `<span class="tag ok">kept</span>` : "",
    c.quality === "128" ? `<span class="tag ok">128 kbps</span>` : `<span class="tag warn">64 kbps only</span>`,
    c.in_range ? "" : `<span class="tag warn">outside length range</span>`,
    d ? `<span class="tag ${d.status === "done" ? "ok" : d.status === "failed" ? "bad" : ""}">${esc(d.status)}</span>` : ""
  ].join("");
  return {
    info: `<div class="title"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>${tags}</div>
      <div class="muted">${esc(sec.title)} · ${mins(sec.seconds)} ·
        ${c.solo_sections} of ${c.sections_total} sections solo
        ${d && d.error ? " · " + esc(d.error) : ""}${c.missing_128 ? " · 128 kbps missing: " + esc(c.missing_128.why) : ""}</div>`,
    // toggles: the selected one is coloured, and clicking it again clears the decision
    decide: `<button class="keep${kept ? " on" : ""}" aria-pressed="${kept}" data-act="${kept ? "undo" : "keep"}">Keep</button>` +
      `<button class="reject${rejected ? " on" : ""}" aria-pressed="${rejected}" data-act="${rejected ? "undo" : "reject"}">Reject</button>`,
    dl: !rejected && !(d && d.status === "done") ? `<button data-act="download">Download</button>` : "",
  };
}

function render(candidates) {
  $("empty").hidden = candidates.some(c => c.prime);
  $("backup-wrap").hidden = candidates.every(c => c.prime);
  for (const c of candidates) {  // candidates are only ever appended, so order is stable
    let k = cards.get(c.url);
    if (!k) {
      const el = document.createElement("div");
      el.className = "card"; el.dataset.url = c.url;
      el.innerHTML = `<div class="info"></div>
        <div class="row"><div class="decide"></div><audio controls preload="none"></audio><div class="dl"></div></div>`;
      k = {el, html: {}, src: null, box: null};
      cards.set(c.url, k);
    }
    const html = parts(c), src = c.quality === "128" ? c.section.url128 : c.section.url64;
    for (const [part, h] of Object.entries(html))  // only touch what changed, never the player
      if (h !== k.html[part]) { k.el.querySelector("." + part).innerHTML = h; k.html[part] = h; }
    if (src !== k.src) {  // new, or downgraded to 64 kbps
      const a = k.el.querySelector("audio");
      a.dataset.q = c.quality; a.src = src; k.src = src;
    }
    const box = c.prime ? "list" : "backup";
    if (box !== k.box) { $(box).appendChild(k.el); k.box = box; }  // new, or demoted to a backup
    k.el.classList.toggle("rejected", c.decision === "reject");
    k.el.classList.toggle("kept", c.decision === "keep");
  }
}

async function refresh() {
  const s = await (await fetch("/api/state")).json();
  if (first) {
    $("h").textContent = s.reader;
    $("sub").innerHTML = `<a href="${esc(s.reader_url)}" target="_blank" rel="noopener">${esc(s.reader_url)}</a>` +
      ` · saving to ${esc(s.out)}`;
    $("n").value = s.want_downloads || s.default_n;
    $("prime-note").textContent = `Prime: a section ${s.range[0]}–${s.range[1]} min long, at 128 kbps.`;
    first = false;
  }
  $("scan").innerHTML = `${esc(s.status)} · listing page <b>${s.page}</b> · <b>${s.checked}</b> projects checked`;
  $("good").textContent = s.good_prime; $("target").textContent = s.target;
  $("backups").textContent = s.candidates.filter(c => !c.prime && c.decision !== "reject").length;
  $("kept").textContent = s.candidates.filter(c => c.decision === "keep").length;
  $("rejected").textContent = s.candidates.filter(c => c.decision === "reject").length;
  $("done").textContent = s.downloaded + (s.want_downloads ? " of " + s.want_downloads : "");
  const complete = s.want_downloads > 0 && s.downloaded >= s.want_downloads;  // "Download N" has finished
  document.body.classList.toggle("done", complete);
  $("complete").hidden = !complete;
  if (complete) $("complete").innerHTML = `🎉 All ${s.want_downloads} downloads completed` +
    `<span class="muted">Saved to ${esc(s.out)}</span>`;
  render(s.candidates);
  $("skipsum").textContent = `Skipped projects (${s.skips.length})`;
  $("skips").innerHTML = s.skips.map(k =>
    `<li><a href="${esc(k.url)}" target="_blank" rel="noopener">${esc(k.title)}</a>
     <span class="muted">[${esc(k.type)}] ${esc(k.reason)}</span></li>`).join("");
}
refresh(); setInterval(refresh, 1500);
</script></body></html>
"""


def make_handler(st):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.send(200, PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self.send(200, st.snapshot(), "application/json")
            else:
                self.send(404, "not found", "text/plain")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with st.lock:
                c = st.find(body.get("url", ""))
                if self.path == "/api/decide" and c:
                    if body.get("decision") not in ("keep", "reject", None):
                        self.send(400, "bad decision", "text/plain")
                        return
                    c["decision"], c["decided_at"] = body.get("decision"), now()
                elif self.path == "/api/download" and c:
                    if c["download"] and c["download"]["status"] == "failed":
                        c["download"] = None
                    st.queue.append(c["url"])
                    c["download"] = c["download"] or {"status": "queued", "at": now()}
                elif self.path == "/api/download_n":
                    st.want_downloads = max(0, int(body.get("n", 0)))
                elif self.path == "/api/scan_more":
                    st.target += max(0, int(body.get("n", 0)))
                elif self.path == "/api/missing_128" and c and c["quality"] == "128":
                    st.mark_128_missing(c, "player couldn't load it")
                else:
                    self.send(404, "not found", "text/plain")
                    return
                st.save()
            st.wake.set()
            self.send(200, "{}", "application/json")

    return Handler


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
    args = ap.parse_args()

    rid = reader_id(args.url)
    st = State(args, rid, Path(args.out or Path(__file__).parent / "downloads" / slug(args.name)))
    threading.Thread(target=scanner, args=(st,), daemon=True).start()
    threading.Thread(target=downloader, args=(st,), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(st))
    print(f"{args.name} (reader {rid}): open http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
