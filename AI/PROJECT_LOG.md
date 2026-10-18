# librivox-download: project log

The initial design and validation notes below record the 2026-10-11/12 state. Their status and next-step
statements are historical. See [PLAN.md](PLAN.md) for the current state; later changes are appended by date.

## 2026-10-11/12: initial project record

### Goal

Gather voice samples of one LibriVox reader for voice work, such as training a TTS voice. Given a reader's name
and LibriVox page, find recordings where that reader is the only voice,
let the user vet them by ear, and download the ones kept, as 128 kbps MP3s.

**What a good set looks like:** one sample from each of many projects, not hours from one book. Different projects
mean different recording sessions, mics and years, which is the variety voice work needs. It also suits
keeping training and held-out audio apart by book.

### Design decisions

- **LibriVox is the only thing scanned.** All decisions come from LibriVox's pages. archive.org (where LibriVox
  hosts the audio) is contacted only to stream or download the chosen file, never to look up metadata.
- **Solo means per section.** A section counts if its reader list is exactly this reader. Collaborative projects
  where the reader read one chapter are fine; the whole project needn't be solo.
- **Dramatic readings are skipped.** They're cast performances: each section lists several readers, and the rare
  solo sections are short narration.
- **Projects whose pages don't list readers per section are skipped.** No way to tell who's speaking.
- **One section per project:** the first one 5-15 minutes long (user's rule). If none is, the one closest to that
  range, and the candidate is a backup (user's decision). Never under a minute.
- **128 kbps, judged by file name** (`*_128kb.mp3`), derived from the 64 kbps play link when the chapter link isn't
  one. 64 kbps is suboptimal: used only when the 128 kbps file is missing (no such name, the player can't load it,
  or its download fails).
- **Prime candidates and backups.** Prime: the section is in the length range and has a 128 kbps file (`is_prime`).
  Everything else (64 kbps only, or no section in range) is a backup: listed below the prime candidates, not counted
  toward the goal. Some readers may not have enough prime recordings, which is why backups are kept at all.
  "Download N" takes a backup only once the listing is exhausted and no prime candidate is left; backups go in the
  order found.
- **Scanning is incremental.** The listing is read a page at a time and each project checked as its page comes in;
  scanning pauses once there are enough candidates: 20 prime, not rejected, or N if "Download N" asks for
  more. A reject, a failed 128 kbps download, "Scan 10 more" or a larger N resumes it. The 2x over-collection (20
  candidates for 10 downloads) allows for downloads that fail and samples the user rejects.
- **A local web page for vetting.** The user validates by ear: progress, candidates with players, Reject, Download.
  Downloads are done by the server, in the background, into the project's output folder, never as browser downloads.
  "Download N" takes candidates not rejected (the user doesn't have to approve each one).
- **Keep / Reject.** Keep records that the user listened and approved; it doesn't change what "Download N" takes
  (anything not rejected). Rejecting a downloaded sample doesn't delete its file.
- **`state.json` is the single record.** What's been checked (with skip reasons), each candidate, decisions, and
  downloads, the last "Download N" (`want_downloads`), with timestamps (`found_at`, `decided_at`, `download.at`,
  `missing_128.at`, top-level `updated_at`). Rewritten on every change, so a restart doesn't re-read project pages and rejected projects don't come back.
  There are no per-folder manifests: they duplicated it and went stale when a decision changed after download. If
  self-describing folders are needed (e.g. exporting to another project), generate them from `state.json` then.
- **Standard library only**, so it runs anywhere with Python 3.12.

### How LibriVox pages work (as of 2026-10)

- **Reader page** (`/reader/<id>/`): the project list is loaded by AJAX from
  `/reader/get_results?primary_key=<id>&search_category=reader&search_page=<n>&search_order=alpha&project_type=either`.
  It needs the `X-Requested-With: XMLHttpRequest` header, or the response is empty. 25 projects per page, as JSON
  with `results` (HTML) and `pagination` (HTML).
- **Each listing entry** has the project URL, title, and `book-meta`: "Complete | <type> | <language>", where type
  is Solo, Collaborative, Dramatic, Poetry_weekly or Poetry_fortnightly.
- **Project page**: `table.chapter-download`, one row per section, with a play link (`*_64kb.mp3`), a chapter link
  (usually `*_128kb.mp3`; older projects sometimes link the original upload instead), reader links
  (`/reader/<id>`, several in dramatic readings), and the time (HH:MM:SS).
- Some pages have no per-section readers (empty reader cells), and at least one returned HTTP 401
  (The Count of Monte Cristo, version 4 dramatic reading).

### Development history

#### 2026-10-11/12: first version

- **Script, then a page.** Started as a command-line script that found and downloaded whole solo projects. Reworked
  in steps after feedback:
  1. Per-section solo instead of whole projects; collaborative projects allowed.
  2. Dramatic readings briefly included, then dropped again once it was clear what they are.
  3. Removed the archive.org metadata lookups (had been used to confirm 128 kbps files existed).
  4. Incremental scanning with a stop condition, instead of reading the whole listing first.
  5. A local server and page for vetting, with one sample per project.
- **Became its own repo:** it started as a tool inside a voice project. AI-facing docs live in `AI/` (loaded by
  `CLAUDE.md`); `README.md` is for people.
- **Review fixes:** the downloader could take a 64 kbps candidate before the scan had started (it treated
  "starting" as "scan over"); now 64 kbps waits for `scan_done`. 64 kbps candidates got their own Backups section.
- **Keep button added; manifest.json dropped** in favour of `state.json` alone, with timestamps on every change.
- **`AI/` made assistant-neutral.** The repo is meant to work with any AI assistant: `AI/MEMORY.md` was rewritten
  without tool-specific references and now describes the layout (`AI/` holds everything, tool entry files only
  point to it, `README.md` is for people).
- **`AGENTS.md` and `AI/STRATEGY.md` added.** `AGENTS.md` is the shared entry file for assistants other than Claude
  Code. `AI/STRATEGY.md` describes the whole structure so an assistant can replicate it in another repo; the user
  sees this repo as a trial of that approach.
- **Output in `downloads/`** (user-created, git-ignored): the default `--out` is `downloads/<name>` next to the
  script, whatever the working directory.
- **Out-of-range candidates became backups** (user's decision): only prime candidates (in range, 128 kbps) count
  toward the 20, and backups of either kind share the section at the bottom of the page.
- **Card layout** (user's request): Keep / Reject left of the player, Download right of it. You play, listen, pause
  and decide, so the decision buttons sit next to the play button; downloading one by one is rare. Keep and Reject
  are toggles (user's request): the selected one is filled green or red, clicking it again clears the decision, and
  clicking the other switches directly. At phone width the player takes a full row with the buttons below it.
- **Kept / rejected counts** in the top bar, and a **done state** (user's request): once "Download N" has
  finished (`downloaded >= want_downloads`, N > 0), the background turns pale blue (`--done-bg`) and a
  "🎉 All N downloads completed" banner shows the output folder. `want_downloads` (the last N) is saved in
  `state.json`, so the done state shows immediately after a restart; it also means a restart resumes an unfinished
  "Download N".
- **Shared docs made self-contained** (`AI/STRATEGY.md` principles 7 and 8): the shared AI docs no longer mention
  local paths, sibling projects or this machine's run state; those moved to `AI/LOCAL.md`, which is git-ignored.
  Reader-specific figures were dropped (see `AI/MEMORY.md`).

### Code map (librivox_fetch.py)

- **LibriVox pages:** `listing_pages` (the AJAX listing, a page at a time), `read_project` (a project's section
  table), `file_urls` (128/64 kbps URLs by name), `pick_section`, `check` (candidate or skip reason), `is_prime`.
- **State:** class `State`, one lock, saved to `state.json` on every change. `goal()` is the number of prime
  candidates the scan aims for; `scan_done` is set once the listing is exhausted or the scan stopped.
- **Threads:** `scanner` (pauses at the goal, woken by an Event), `downloader` (picks via `next_download`).
- **Web:** `PAGE` (HTML + JS, polls `/api/state` every 1.5 s; cards are built once and updated in place so players
  aren't interrupted: `parts(c)` gives the text, the keep / reject buttons left of the player and the download
  button right of it, each replaced only when it changes), `make_handler` (GET `/`, `/api/state`; POST `decide`
  (keep / reject / null), `download`, `download_n`, `scan_more`, `missing_128`).

### Status at the time

Scanning against the live site works: it pauses at the goal, and a restart resumes from `state.json`. The page's
later changes (Keep / Reject toggles, prime / backup split, done state, saved N) were checked offline, from a saved
`state.json` with scanning and downloading turned off. Not yet tried against the live site: Keep / Reject in a real
session, and downloads.

### Open questions at the time

- **Where the samples go.** Nothing decides where downloads should end up in the project that uses them, or
  whether they're training or held-out audio there. That's the user's call.

### Known issues at the time

- **Any player error downgrades to 64 kbps.** The page reports "128 kbps missing" when the player fails for any
  reason, including a dropped connection, and the candidate becomes a backup. The page has no way to undo it (edit
  `state.json`, or delete `missing_128` and set `quality` back to "128", while the server is stopped).
- **HTML parsing by regular expressions.** `listing_pages` and `read_project` depend on LibriVox's current markup
  (described above). If LibriVox changes its pages, look there first.

### Next steps at the time

- Run the current version against a reader: check Keep / Reject and a download.

## 2026-10-18: download recovery and documentation maintenance

The status review found that completion trusted saved flags even when files were absent, individual requests
were lost on restart, and a failed individual 128 kbps request did not continue at 64 without another click.
The user authorized fixing these and bringing the docs into conformance with their updated strategy.

- Persist the individual queue and save in-flight intent before network I/O. Recover queued and interrupted
  transfers, including older state without a queue. Deduplicate repeated clicks. Individual fallback keeps its
  request through a restart; bulk fallback preserves prime priority and waits for scanning to finish.
- Reconcile completion with files on disk at startup and during UI/download selection. Mark missing files
  explicitly, preserving the old path/time and listening decision, and make them eligible for restoration.
- Make 128 kbps fallback reversible. Explain that a playback failure can be temporary, offer Retry 128 kbps,
  and retain existing 64 kbps recordings. Capture the actual transfer quality so a simultaneous player error
  cannot mislabel the saved file. Reject cancels queued work; already running transfers may finish and stay on disk.
- Fix the previously observed Windows duplicate-port behavior with exclusive binding, before any worker starts.
- Keep the standard-library single-script design and all existing selection rules. In particular, Keep remains
  an annotation; bulk downloading takes non-rejected candidates. No datasets or existing recordings were migrated.
- Follow the supplied strategy: MEMORY routes reading, PLAN holds the present, USAGE describes operational tasks
  and their prerequisites in plain language, entry files only point to MEMORY, and local setup stays ignored.
  The earlier mixed project notes above are retained as a dated historical record rather than current guidance.

Validation on Python 3.12.10: 15 offline tests pass, covering restart/fallback/missing-file recovery, durable
intent, decisions and selection semantics, transfer bytes through local HTTP, and occupied-port rejection.
CLI help passes. A fresh normal live run paused at the default candidate goal; browser Keep/Reject/clear and
one actual 128 kbps download passed, and the completed file/state survived a server restart. A local-only UI
fixture confirmed Retry 128 kbps restores the player selection and moves the card back to the prime list.
Existing user output was not used as a test fixture. This did not assess subjective playback/audio quality,
perform a full catalog survey, or exercise every remote failure mode. Normal use remains the next check.

## 2026-10-18: JSON-driven sequential batch collection

The user requested unattended collection for a list of reader URLs through a JSON batch file, especially for
assistant-assisted use. Added `librivox_batch.py` with defaults/per-reader overrides, whole-manifest validation,
a no-write/no-network dry run, ID-based output directories and a final machine-readable JSON summary. Names
are optional and default to ID-based labels without another metadata request. Relative output roots resolve
against the manifest, so launching from another directory doesn't move the collection.

The runner processes one reader at a time without a web server or background workers. It shares the existing
selection and transfer functions, including one section per project, prime priority, actual-exhaustion-only
backup selection and 128/64 fallback. The scanner's per-project logic was extracted into a shared function;
interactive selection behavior is unchanged. Batch stops once the requested total is met, without collecting
the interactive UI's extra candidates for listening.

Completion, insufficient eligible results, failures and interruption have distinct summary statuses and exit
codes. Individual failures permit subsequent readers; Ctrl+C preserves work and marks later readers not_run.
A per-reader time budget is checked between operations; existing network timeouts still govern in-flight I/O.
Each invocation retries previously failed transfers once. Existing state remains the single per-reader record,
including source project/section URLs, decisions and file paths. State now records selection settings; batch
refuses incompatible readers/filters or legacy state with unknown filters before changing it, requiring new
output instead. The batch JSON is collection intent; the summary is a report, not a replacement manifest.

Added `batch.example.json`, README command/schema documentation and the AI usage recipe. Personal
`*.local.json` configurations/reports are ignored. The guide covers read-only repository roles using external
configuration/output and `-B`, verifying results, and keeping listening judgments and downstream training separate.

Validation: 26 offline regression tests pass (15 existing, 11 batch). Batch checks include two-reader collection
through local HTTP with actual parsing and file transfers, defaults/overrides, invalid configurations, no-network
completed resumption, incompatible-state preservation, fallback, bounded failures, insufficiency, listing errors,
time budgets, interruption/recovery and CLI summary/exit codes. A live CLI smoke collected one recording in fresh
scratch output and exited successfully; rerunning the same configuration verified completed resumption. No existing
user recordings/state were used as fixtures. No full catalog survey, subjective listening or downstream training.
