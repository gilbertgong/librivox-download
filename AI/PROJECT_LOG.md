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

## 2026-10-18: shared Overview and Review dashboard

The user refined batch collection into the primary workflow with the same dashboard for single-reader use.
Agreed on two navigable pages: Overview for per-reader progress/counts/errors and collection controls, and
Review for everything in saved state, grouped by reader/project and filterable by status/decision/reader.
The proposed saved HTML index was dropped in favor of reopening saved state directly.

Added `librivox_dashboard.py` and `dashboard.html`; removed the old embedded single-reader page and routed both
commands to the shared interface. Default batch startup binds the loopback server before starting a sequential
collection worker and stays open after completion. `--headless` preserves the exiting JSON-summary workflow.
`--review PATH` loads an output root, reader directory or state file without scanning, downloading, queue recovery
or completion rewrites on startup. Local audio is served from saved paths within the reader directory, with
HEAD/range support for seeking. Missing files are labeled in the view without changing saved state just by viewing.

Keep/Mark bad/Clear decision writes back to the existing state and preserves other fields, transfer records and
files. Full saved state and skipped reasons remain expandable. State save preserves unknown metadata; live
collection/review share locks and atomically register the active State to prevent stale decision writes from
overwriting a transfer. Polling updates existing cards without replacing audio elements.

Review-only mode exposes no collection controls. Completed readers remain idle after a bad decision; explicit
Collect / resume fills targets. During active collection, rejected files don't count toward the requested total.
Pause stops between operations and leaves subsequent readers unstarted. Closing the server requests a stop and
waits for workers; in-flight network operations still obey their connection/read timeouts. Single-reader mode
keeps candidate scanning/source previews and explicit per-card downloads, but its idle worker doesn't restart
collection merely because a recording was rejected. The dashboard's normal exit0 indicates server shutdown,
while headless outcome codes retain their original meaning.

Validation: 38 offline tests pass, including all previous tests and dashboard state-only/legacy review,
decision persistence, local media HEAD/ranges/missing paths, path containment, explicit replacement, live
decision/transfer synchronization, pause, CLI routing and binding before work. Browser checks with isolated
synthetic audio passed Overview-to-reader navigation, filters, Mark bad/Clear persistence after reload, actual
local playback, phone-width layout without horizontal overflow, and a clean console. Real batch/single-reader
CLI entry points showed the shared dashboard using scratch collections, with batch completion and explicit
resume leaving the server available. Test servers stopped; existing user output wasn't used as a fixture,
and research jobs were left alone.

## 2026-10-18: URL-only readers and cached display names

The user requested a simpler readers list because LibriVox pages already contain display names. Verified the
shared `Works read by NAME | LibriVox` title on three reader pages, then added plain URL entries alongside
existing objects for count/filter/name overrides. Names resolve at collection time, after resume validation,
and save with their source in state. Explicit names override cached names; existing meaningful saved labels
are reused. Failed lookups use Reader ID and retry on a later invocation instead of blocking collection.
Display names retain punctuation, HTML entities and date annotations. Directory identity remains the reader ID.
Dry-run validation stays offline, and review mode continues reading saved names without network requests.

Updated the example, README, plan and usage guide. Validation: 43 tests pass, including mixed URL/object entries,
actual local HTTP name resolution in the two-reader workflow, cached no-network resumption, explicit precedence,
entity/date parsing, missing/empty titles, network failures and later recovery. The implemented name parser also
resolved the provided live reader URL successfully without downloading any audio.

## 2026-10-18: in-place terminal download progress

The user requested that repeated per-transfer counters reuse one terminal line. Added terminal-aware stderr
progress that redraws with a carriage return, clears leftover characters if the text shrinks, and ends the line
before final statuses/errors, including interruption. Duplicate counts are suppressed. Redirected logs retain
newline-separated distinct updates without control characters; stdout JSON is unchanged. No active downloader
was found before editing. Terminal/redirection checks and the full 45-test suite pass; no collection launched.

## 2026-10-18: reader ID inputs

The user requested reader_id as an alternative to reader URLs. Batch entries now accept integer/digit-string
IDs directly and objects with reader_id plus overrides. All forms normalize to the canonical reader URL/ID;
duplicates are detected across formats and a supplied ID/URL pair must agree. Booleans, fractions, nonpositive
or malformed IDs are rejected. Name lookup/cache behavior is unchanged. Updated the example and operational
docs. All 47 tests pass, including normalization, overrides, conflicts and cross-format duplicates. Parser
changes apply on subsequent launches; no collection was launched for validation.
## 2026-10-18: downloaded duration on Overview

Added a per-reader Duration column in hours:minutes:seconds, as requested. It sums saved LibriVox section
lengths for completed downloads whose local files remain present, including recordings marked bad. Missing,
pending and failed downloads are excluded. This uses existing snapshot fields in the browser, with no audio
decoding, new dependencies or backend changes; refreshing the page updates an already running dashboard.
README and plan updated. JavaScript syntax and focused calculation checks pass for empty collections,
rejected/missing/failed files, rounding, absent duration metadata and totals over 24 hours. No collection launched.

## 2026-10-18: source books and premium replacement

The user requested source provenance and accompanying Gutenberg texts, enabled by default, with missing text
considered degraded like 64 kbps audio. Capture the LibriVox project ID and Online text URL from the section
page already fetched; normalize Gutenberg links without title matching or an extra API request. The new
librivox_text module downloads original whole-book UTF-8 bytes through a Gutenberg-listed mirror, spaces
requests, refuses main-site redirects and caches by Gutenberg ID across readers/projects. Record the actual
URL, retrieval time, byte count and SHA-256 alongside the text, preserving its header/footer. Gutendex timed
out during investigation; verified the listed mirror's generated text path directly, avoiding that dependency.

Batch download_texts defaults true and text_mirror is configurable; the single-reader CLI offers
--no-download-texts and --text-mirror. Text settings can change when resuming existing selection state.
Premium means preferred length, 128 kbps and downloaded source text when enabled. Unknown text is provisional
until checked; known degraded candidates wait until listing exhaustion. Resume enriches completed recordings
without another audio transfer and searches for premium replacements while keeping earlier audio and review
decisions. Counts may exceed the target. Missing/failed text gets one retry per candidate per collection pass,
including explicit single-reader resumption; failures do not prevent fallback audio. Summaries expose premium
and degraded counts, with a completed-fallback explanation. Pause/shutdown are checked between text and audio.
Review shows source/local-text links, statuses and separate degradation reasons; Overview adds premium counts.
Review-only state/cache inspection does not fetch or rewrite anything. Source books are not chapter transcripts
or validated audio/text alignments.

Validation: 61 offline tests pass, covering source/legacy URL capture, defaults/overrides, mirror retrieval,
shared cache and provenance, corrupt-cache preservation, invalid payloads/forbidden redirects, premium selection,
exhausted fallbacks, later text recovery, legacy enrichment, replacement without deletion, audio-only mode,
read-only local text serving/missing detection/path containment, explicit single-reader retries, review decisions
during text I/O and pause boundaries. Dashboard JavaScript syntax passes. A separate live one-book smoke check
successfully downloaded and reused the cached original text; browser checks confirmed premium counts, source
and local-text links, and missing-text explanations with no console errors. The temporary review server was
stopped. Existing user collections/configs and research jobs were not modified.

## 2026-10-18: compact Overview reader table

The user requested reader IDs under resolved names and more space for the reader column. Added smaller ID
labels, widened the name column, shortened Target/Downloaded/Marked bad to Goal/Files/Bad, and removed the
redundant Available column. Summary cards now show Readers, Downloaded files and Premium recordings. Numeric
columns stay compact; the collection action column is absent in review-only mode. Files includes completed
local downloads marked bad; Bad includes all rejected candidates, even undownloaded ones. Counts and selection
logic are unchanged. README and plan updated. JavaScript syntax and a browser layout/console check passed
against an isolated review fixture; no user state was edited. The temporary review server was stopped.

## 2026-10-18: reader profile links

Linked the smaller Overview Reader ID labels to the corresponding LibriVox reader pages, opening in a new
tab. Name links still open local Review. Updated README/plan; dashboard JavaScript syntax check passes.

## 2026-10-18: downloaded-first Review ordering

Review now shows completed recordings with present local audio first within each reader, followed by pending
and other undownloaded candidates. Rejected downloaded files stay in the downloaded group. Initial rendering
uses a stable sorted copy; later status changes use CSS ordering without detaching audio elements or changing
saved state. README/plan updated. JavaScript syntax/ordering checks and a browser check with deliberately
reversed fixture data passed, with no console errors. The isolated read-only server was stopped.

## 2026-10-18: ignored batch metadata

Batch JSON now accepts _ignore at the top level, in defaults and in reader objects. Any JSON value is allowed;
its contents are neither interpreted nor included in resolved jobs. Other unknown fields still fail validation.
The field does not disable its containing reader. README/plan updated. All 62 offline tests pass, including a
regression proving ignored nested settings/invalid reader data leave resolved jobs unchanged. No active downloader
was found before editing; no collection or user state changed.

## 2026-10-18: API-first project details and explicit Rescan

The user requested using the API wherever possible and a Review Rescan button. Added a standard-library API
adapter using the official extended audiobooks endpoint for sections, reader IDs, duration, audio URLs and
source links. Known project IDs query directly; unknown IDs use paginated exact-title lookup with mandatory
catalog-URL identity matching, including http/https/www variants. Sort sections numerically. Missing/unsupported
API fields, identity misses or request failures fall back to HTML, recording the reason in source provenance.
Reader listings and name lookup still use the website because the documented API has no reader-search endpoint.
Legacy text enrichment now uses the same API-first project path. No dependency or selection-default changes.

Review now offers Rescan for the selected reader or all readers sequentially, including when opened with
--review. Explicit rescan clears old checked-project results and restarts at page one, rechecking skips/errors
within the normal candidate goal and reader time budget. It only refreshes metadata, never downloads audio or
books. Preserve recordings, choices, review decisions, cached books and custom metadata; unreviewed pending
candidates may refresh, and alternatives for protected choices appear in last_scan details. Retain semantically
ineligible old candidates but exclude them from new transfer/queue selection. Normalize project identity to
avoid duplicates while retaining existing URLs for protected cards. Review startup and decision edits still do
not start network work. Saved selection settings are required for review-only rescan; unknown legacy settings
are not invented or silently rewritten.

Rescan has Pause scan and visible per-reader result/error details. Distinguish candidate target, actual listing
exhaustion, timeout, pause and failures. Serialize registration/review writes and collection/rescan starts.
Stop/join old single-reader workers before resetting checks, restart only its idle downloader afterward, and
start scanning again on a subsequent collection/scan-more request. Existing media and decisions survive both
API rechecks and concurrent review actions. Updated README, plan and operational usage instructions.

Validation: all 78 offline tests pass (62 prior plus 16 API/rescan checks). Local HTTP batch integration now
exercises API data without project HTML; tests cover exact identity, pagination, direct IDs, section order,
incomplete data and fallback, shared readers, fresh scan bounds, old skip recovery, read-only media preservation,
custom fields, http/www identity variants, semantic ineligibility/queue guards, listing failure vs exhaustion,
pause, live decisions, busy/legacy guards, POST routing, reader scope and single-reader worker lifecycle.
JavaScript syntax passes. A live one-project metadata check returned sections and source provenance in one API
request with no HTML/audio/text requests. Browser verification against an isolated saved API fixture exercised
Rescan, observed disabled/active controls, rediscovered a previously skipped project and showed completion with
no console errors or media downloads. Temporary server stopped; no existing user collections/configs/jobs changed.

## 2026-10-18: quiet browser disconnects

The user reported ConnectionAbortedError / WinError10053 while writing a dashboard polling response. Catch
BrokenPipeError, ConnectionResetError and ConnectionAbortedError at the HTTP connection boundary, covering
request reads and response headers/bodies. Mark the connection closed. Media streaming also handles the same
specific exceptions. File/mutation error handlers let disconnects reach that boundary rather than incorrectly
sending a second 404/400 response. Other errors are not suppressed, and completed decisions remain saved when
the browser disconnects before receiving their response. README and plan updated.

Validation: all 81 offline tests pass, including simulated disconnects during headers, JSON, audio and decision
responses, plus propagation of unrelated I/O errors. All 15 dashboard tests also pass under the reported MSYS2
Python3.14 interpreter; existing HTTP-error fixture objects emitted ResourceWarnings during test cleanup.
The user's active batch was left running; the loaded server receives this fix on its next launch.


## 2026-10-20 — One collection workflow, with manual controls on Review

Consolidated the normal launch paths around the sequential batch controller. A valid empty JSON object or
empty/omitted readers list now opens Overview reader entry. URL/ID additions and collection target changes
save to that manifest while preserving other settings and _ignore notes; externally changed JSON is not
overwritten. First addition to an empty session sets auto_collect=false so manual sessions reopen idle.
Populated batches retain automatic collection by default; --browse suppresses it for one dashboard launch.
Headless collection and state-only --review remain available.

At the user's request, manual controls live above each reader's recordings on Review: metadata browse/rescan,
Scan 10 more, Total, Collect / resume and Pause. Pending candidates offer remote previews; per-card Download
and quality retry now work in configured sessions. Explicit downloads drain their request queue without
filling the saved bulk target or fetching unrelated candidates' source books. One worker serializes scanning/collection/individual transfers; decisions
remain writable during operations. Overview keeps reader entry, progress and bulk controls. The older
name/URL CLI forwards into this same controller with a metadata-only startup pass and its original output
location. Compatibility APIs remain for older integrations.

Validation: 92 offline tests pass on Python 3.12 and 3.14, including eleven new session/manual workflow checks.
JavaScript syntax passes. A browser check using synthetic local metadata/audio verified empty-session reader
entry, JSON persistence, metadata-only browsing, remote playback, and one individual download while another
candidate stayed pending. No external collection or existing user output was used. Python 3.14 reports the
existing HTTPError fixture cleanup ResourceWarnings; all assertions pass.


## 2026-10-20 — Explicit launcher name and automatic session creation

Renamed librivox_batch.py to librivox_launch.py so the command to run is apparent. Updated imports, tests
and current usage docs; historical log entries retain the original name. No duplicate old launcher remains.
Without a filename the launcher uses session.local.json in the current working directory. Normal dashboard
launches create a missing session file containing {} using exclusive creation, preserving existing files
and reporting invalid JSON. Explicit missing filenames work the same way when their parent directory exists.
Dry-run and headless commands keep their existing no-creation behavior and require a valid existing file;
--review uses only the requested saved output. The default *.local.json filename is already ignored by Git.

Validation: 95 offline tests pass on Python 3.12 and 3.14. Added checks for no-argument/default startup,
explicit missing-file creation, reopening without overwriting settings, invalid-file preservation and no
session creation from dry-run/headless/review. Checks use temporary directories, not user configurations.


## 2026-10-20 — Listener-oriented project library

User authorized a small listener workflow alongside reader sampling: full reader project discovery, direct
project URLs, whole-project downloads and an optional Include dramatic readings checkbox. Added Projects as
a third dashboard page, with title/author search, API author/language/genre/reader metadata, total duration,
section credit lists and source/local players. Details prefer the official extended audiobooks API with exact
URL identity, retaining HTML fallback. Reader display names come from display_name. No global catalog crawl.

Project scans explicitly traverse a reader's full listing with no sample cap/language/length/solo filter;
configured timeout or60minutes, Pause and cached progress bound the work. Dramatic listings are recorded but
their details skipped by default. Enable the checkbox and rescan or load details to include them; hiding
cached projects never deletes them. This does not alter sampling rules or add sampling jobs. Downloads choose
an entire project or sections crediting a selected reader (including shared casts), reuse completed files,
restore missing files, retry failures explicitly and fall back128to64. Save progress before network work.
One dashboard worker serializes project operations with sampling. Whole-project state lives separately in
output_root/projects/catalog.json and URL-derived project directories; source books share the text cache,
and missing text does not block a requested whole book. No project work resumes automatically on startup.
Read-only output review can browse the cached project library/local players, with no project mutation controls.

Metadata refresh preserves completed section records. If the audio list changes, retain the selected list
and provenance, record the new alternative and explain using fresh output for that revised edition; existing
files cannot silently become downloads attributed to different URLs. Interrupted requests display as such on
reopen without rewriting state. Section lists render only when expanded, preserving player elements during
polling. Launcher startup now prints the absolute settings JSON path; creation also prints the initial {}.

Validation: 110 offline tests pass on Python3.12 and3.14, including15 project-library tests plus launcher
output assertions. JavaScript syntax and diff checks pass. A bounded live lookup of known project52 validated
full section metadata/authors/display names from the API, with no media downloads. Synthetic browser checks
verified reader scan, dramatic reveal/load, direct URL lookup, reader-scoped solo/shared downloads, completing
a whole project while reusing saved sections, and local playback without errors. Existing user sessions,
recordings, settings and running dashboard were not used as fixtures or restarted. Restart loads the new page.


## 2026-10-20 — Opened-project ordering and focused project view

The user found newly opened projects at the bottom and wanted names to focus on a project rather than
navigate away. Successful URL opens now promote that project to the top of the current results and scroll
it into view when metadata arrives. Project title buttons open a native modal containing only that project's
metadata, download controls and section players; the external LibriVox link is smaller underneath. Shared
card rendering keeps controls consistent in both views. Polling preserves modal players and section expansion.
Close/Escape returns focus to the project name and stops modal playback; opening a modal pauses other players.
The modal also exposes Pause and operation errors while the rest of the page is inactive.

Validation: browser checks with synthetic local metadata/audio confirmed new/existing URL promotion, focused
content, working reader-scoped downloads and live status inside the modal, Escape/Close and restored focus.
No browser console errors. JavaScript syntax and all110 offline tests pass. Documentation updated; no data
migration, backend selection change or new real-world downloads. Reload the dashboard page for these UI changes.

## 2026-10-25 — Mountable downloader component

Added librivox_web.py and vendored BSD-licensed microweb: the established standalone CLI and combined hosts
use one set of routes around the existing Dashboard controller. Factories defer controller/session setup
and workers until after binding. HTTP handlers drain before pause/join shutdown. Compatibility make_handler
delegates to the same app. Frontend navigation/API requests and returned local audio/text links work under
mount prefixes, including per-reader review links. Headless selection/collection code is unchanged.
Documented component settings, library read interface revision 1 and vendored source provenance. Existing
110 regressions plus component tests exercise quiet construction, bind failure, settings paths, mounted
pages, decisions, audio HEAD/ranges and worker shutdown. A separate synthetic-workbench proof used only
generated audio and disposable state, including standalone/combined HTTP and browser playback checks.
No actual voice workbench, research code, live queue, real downloads or production state was modified.

Final validation: all 114 tests pass on Python 3.12 and 3.14; Python 3.14 still reports existing HTTPError
fixture cleanup ResourceWarnings. The mounted browser check found and fixed a root-relative per-reader
review link. Navigation, local playback and the synthetic downstream task then worked under the shared shell.
The vendored runtime matches the upstream development file byte-for-byte; syntax/link/LF/whitespace checks pass.

## 2026-10-25 — Component discovery manifest

After checkpointing the adapter, added microweb-component.json for optional local discovery consoles. It identifies
the existing factory and defaults to a settings-relative session.json with collect=false. No controller,
standalone CLI, dependency installation or network behavior changed. A test verifies that the shipped manifest's
factory/defaults construct quietly and start in an isolated host settings directory.
The manifest uses a components array (one panel here, order 10); a host can combine it with several components
from another repo. Refreshed the vendored development runtime for optional banner placement and updated its
checksum. 115 tests pass on Python 3.12 and 3.14; isolated browser checks show the downloader and its Review
page under a shared synthetic Machine banner. Existing Python 3.14 HTTPError fixture ResourceWarnings remain.


## 2026-10-27 — Updater-only bootstrap for an explicit upgrade test

The user wants to test microweb's updater rather than replace the complete runtime. Its integration
snapshot still had a numeric-only parser despite a prefixed label and partial manual updater edits.
Patched only the updater section to accept vMAJOR.MINOR.PATCH and explicitly upgrade locally edited
files with an exact-byte backup, validating incoming checksum/version/syntax without requiring old-release
bytes. Framework code and v0.1.0 label remain as before. The user will perform the actual upgrade;
no --update was run here. THIRD_PARTY and assistant usage describe this temporary patched-snapshot state.
All 115 downloader tests and all 12 upstream updater tests pass against this copy under MSYS2 Python3.14.


## 2026-10-27 — Console entry point, source package and selectable sessions

The user agreed to console.py as the primary standalone entry point, application implementation under
src/, JSON session selection in the UI, and a sessions/ directory with named creation. Moved implementation
and frontend into src/librivox_download/ with relative imports. Root console.py bootstraps the source
checkout and exports the component factory; legacy launch/fetch commands and the uniquely named web
adapter remain thin compatibility shims. The vendored microweb.py stays at the root. Selection/download
algorithms and existing saved-data paths are preserved; the legacy fetch default still points to root downloads/.

Without a filename console.py opens a picker, writing nothing. Existing JSON files from the launch directory
and sessions/ are listed with validation status. New named sessions are exclusively created in sessions/,
adding .json if omitted, with auto_collect=false and output_root=../downloads. That preserves the normal
launch-directory downloads location; existing configs retain their file-relative output semantics. sessions/
and microweb.py.bak are ignored. Explicit CLI JSON still supports automatic collection, browse, dry-run and
headless operations. The old launcher retains its no-argument session.local.json behavior.

The header displays the active filename with full path on hover. Change session validates first, then
pauses and joins old work asynchronously before swapping only the downloader controller. The server,
browser URL and other mounted components stay running. New UI-opened sessions remain idle even if their
saved auto_collect is true. Session generations reject stale UI writes; frontend card/audio/project state
resets on a switch. Shutdown joins pending transitions, and failed transition reloads leave the old session
available and paused. Review-only launches, including empty libraries, do not allow switching. The discovery
manifest now opens the picker by default using the host's settings directory; explicit session settings remain.

All 125 tests pass on Python 3.12 and Python 3.14 (including MSYS2). New tests cover config validation,
exclusive naming/path bounds, no-write startup, staged worker draining, failure recovery, stale writes,
mounted routes, read-only mode and an isolated copied checkout with site packages disabled. Browser checks
created and reopened scratch sessions, rejected unrelated JSON and switched between configs while remaining
idle; no external requests or real recordings were used. The check server was stopped after verification.
Existing Python 3.14 HTTPError fixture cleanup warnings remain non-failing. JavaScript syntax and whitespace
checks pass. Updated README/AI/component docs, and refreshed provenance to the user's exact v0.1.2 runtime.
No sessions, saved state, downloads, backup files or research data were migrated or deleted; no commit/push.

## 2026-10-27 — Persistent layout and sidebar views

Moved Overview, Review and Projects to left section navigation while retaining the existing controls,
typography and tables. The session header and sidebar stay visible on desktop; narrow screens use
horizontal navigation. Internal links switch views in place, preserve unsent form values and use browser
history so Back, reload and reader-filter links work. Existing endpoints also support direct navigation.
All 125 offline tests pass; JavaScript syntax checks and isolated browser checks cover view switching,
unsent values, filter restoration through Back, reader-scoped links and reload. No downloads were started.

## 2026-10-28 — Explain disabled reader entry

The user encountered a disabled Add reader control during collection and chose to retain the idle-only
restriction. Added an inline status explanation with instructions to wait or pause, associated with the
button for accessibility; it disappears when work is idle. No collection or mutation behavior changed.

## 2026-11-04 — Portable reader download paths

Reader downloads used native Windows separators while downstream consumers expected slash-separated
relative paths. Persist new download.file values using as_posix(); normalize legacy separators before
file reconciliation and on collection/review saves. Scope normalization to candidate download.file,
preserving decisions, completion metadata and unrelated fields. Project downloads already use this format.
Added regressions for successful transfer paths, legacy reload/file identity, idempotence, metadata
preservation and review writes. 129 offline tests pass on Python 3.12 and Python 3.14.
No audio, consumer code or derived inventories changed. Affected live reader state was repaired separately
with a backup and file-identity checks; derived consumer inventories still require coordinated recovery.
Running hosts pick up the source fix after restart.

## 2026-11-21 — Installable package

Added Python 3.12+ wheel/sdist metadata, bundled HTML, installed CLI/module entry and namespaced
vendored runtime, retaining checkout launchers. Hosts can explicitly supply their framework; old
shared-module hosts remain supported. Legacy single-reader output now defaults to the launch directory,
not package files. No selection, state, scanning or download behavior changed.

Removed the unnecessary root microweb wrapper; tests import the namespaced runtime and copied-checkout
checks no longer copy the wrapper. Updater instructions use the installed module or direct vendor path.

Removed THIRD_PARTY.md at the user's request; runtime provenance stays in AI/USAGE.md and
the upstream license remains embedded in microweb.py. Removed obsolete packaging metadata and links.

Consolidated root launchers into librivox_web.py, retaining existing component exports and discovery
while delegating standalone startup to the installed CLI. Removed console.py and the legacy root launch/fetch
wrappers. Added BSD 2-Clause LICENSE matching microweb and distribution license metadata. Shortened the
README to basic setup/use, preserving the detailed guide in docs/usage.md.

## 2026-11-24 — Readers added by a host

The component gained `add_readers(ids, count)` so a host can add readers it knows of, saved in one write,
leaving the dashboard as the session file's only writer. It only adds: a first version looked names up and
added nothing while busy, and a slow site held up the whole list. A goal of 0 was tried and dropped, so that
added readers bring no new collection behaviour.

A host may now name a session that doesn't exist yet under sessions/: it is created like a new session (folder,
`output_root: ../downloads`), where `{}` would have failed without the folder and put downloads inside it.
132 offline tests pass on Python 3.12.

## 2026-11-25 — Scan target is twice the goal

The user had asked for scanning to look for twice the goal; the code used `max(20, goal)`. A configured
reader's target is now 2 × its goal. Targets already saved in `state.json` still apply when larger.
