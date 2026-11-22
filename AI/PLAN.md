# Current project plan

## Goal

Gather one solo section per LibriVox project for a chosen reader, listen and record decisions in a local web UI,
and download a varied set of samples, interactively or from a JSON list of readers. Different projects provide
different recording sessions; downstream training and held-out splits remain the user's decision.

## Current direction

The HTTP layer now uses vendored microweb and a quiet `librivox_web.create_component(settings)` factory.
Standalone CLI and combined hosting share routes and lifecycle; controller/selection/download logic is
unchanged. Prefix-aware frontend and media links support mounting. See [component and library contracts](../docs/components.md).
No actual voice workbench is included here.
console.py is the primary source-checkout entry point. Application modules and frontend live under
src/librivox_download/, with package-relative imports. Source-checkout use remains installation-free; pyproject.toml also
builds an installable distribution with dashboard HTML, namespaced framework and a librivox-download
command / python -m librivox_download entry. Component hosts may pass framework= explicitly. The root web adapter and
legacy launch/fetch scripts are compatibility shims. The vendored microweb runtime lives inside librivox_download and still matches v0.1.2 exactly.
There is no root framework wrapper; tests and updater commands use the namespaced runtime. See THIRD_PARTY.md.

With no filename, console.py opens a session picker. It lists JSON files in the launch directory and
sessions/ with validation status. New session creates a named file exclusively under sessions/; that
folder and microweb.py.bak are ignored. UI-created configs explicitly retain ../downloads and disable
auto collection. Existing explicit JSON paths retain their own config-relative output roots. The header
names the active session with its full path on hover. Change session validates before pausing/draining
owned work and swaps only the downloader controller; the web host and other components keep running.
Newly opened sessions remain idle. Generation checks reject stale UI writes after switching.

The component discovery manifest opens the same picker in the host-supplied settings directory, with
collection disabled. Explicit session_file/review_root settings remain supported; review-only mode has
no session switching. Existing session files, output directories, recordings and decisions are not migrated.
All 133 tests pass on Python 3.12 and MSYS2/UCRT64 Python 3.14, including package portability and session creation/validation/draining/mounted tests.
Browser checks use generated data and scratch sessions; no production collection or research work is used.

Keep the Python 3.12 standard-library tool and its solo-reader/length selection rules. Source books download
by default; missing text joins 64 kbps and out-of-range length as a degraded fallback. The interactive script also
provides shared state, scanning and transfer functions. JSON batch collection is the primary workflow;
manual entry and automatic batches use one JSON session and three-view dashboard. Empty JSON objects open
reader entry; manual controls live with recordings on Review. console.py starts the picker or an explicit
JSON session. The compatibility librivox_launch.py retains its old default session.local.json behavior.
Explicit missing dashboard session paths create {}; headless/dry-run require existing valid files.
The older single-reader CLI is a compatibility
launch into that same controller. Review-only startup loads saved state
without starting collection. Projects adds full-reader catalog discovery and whole-project or credited-reader
section downloads for listeners, independent of sampling state. Opened URLs are promoted to the top of the
current project list. Project names open a focused native dialog, with a separate small catalog-page link. A headless option remains for sample automation. No installation/build step is needed.

## Approach and reasons

- Component factories perform no writes or worker startup; initialization follows socket binding. The host
  drains requests before pausing/joining owned collection services. Existing make_handler delegates to the
  same routes. The normal CLI retains its session-file creation behavior; component factories defer it to startup.

- Scan only LibriVox metadata. Contact the audio host only for chosen playback/download URLs; this avoids
  unnecessary metadata requests. Use the official extended audiobooks API for project sections/readers/durations
  and source links. Query known project IDs directly; otherwise paginate exact-title searches and require an
  exact normalized catalog URL match. Never choose an edition solely by its title. Normalize section order.
  Retain the reader-listing AJAX endpoint and name-page lookup: the documented API has no reader-search route.
  Unsupported/incomplete API data or request failures fall back to HTML, with provenance/error recorded.
- Solo means the section's reader list is exactly the requested reader. Collaborative books are eligible;
  dramatic readings, other languages (unless disabled), and pages without per-section reader lists are skipped.
- Offer the first section in the preferred 5–15 minute range, otherwise the closest, never under one minute.
  One sample per project provides recording variety without taking entire books.
- A prime candidate is in range, selected at 128 kbps and has downloaded source text when enabled. Unchecked
  text is provisional until collection checks it. All other candidates are backups. Pause scanning at
  20 non-rejected prime candidates, or the bulk download target if larger. During collection, rejecting/demoting one allows further scanning; idle manual sessions require an explicit scan.
- Prefer filename-derived 128 kbps URLs; fall back to 64 after an unsuccessful attempt. A player error does not
  prove a file is absent, so the UI explains the failure and offers Retry 128 kbps.
- Download N selects anything not rejected, prime first; Keep is an annotation, not a prerequisite. Bulk backups
  wait until scanning finishes and no eligible prime remains. Explicit individual requests can take a backup
  immediately and retain their request through the 128-to-64 fallback.
- `state.json` is the single record of checked projects, decisions, transfer results, the individual queue and
  the last bulk target. Save transfer intent before network I/O so interrupted work can restart. Transfers restart
  from the beginning of their `.part` file; they do not perform HTTP range resume.
- Verify completed paths on startup and while serving/selecting downloads. Missing files get a visible `missing`
  status, keeping their recorded path, completion timestamp and listening decision. They do not count as complete;
  an active bulk target can restore them, or the user can request them individually.
- Never delete recordings when rejecting a sample or switching quality. Retrying 128 changes the selected
  playback URL; an existing 64 kbps download remains recorded until a new Download request replaces that record.
  Both audio files remain on disk after an upgrade.
- Bind the loopback server before starting workers and reject duplicate port use, including on Windows, so a
  second launch cannot silently compete with an existing session.
- Batch mode seeks each reader's requested premium total, resumes by reader ID and requires matching saved selection
  settings. It validates the full manifest first and processes one reader at a time. Headless mode is synchronous;
  dashboard mode uses one collection worker with shared state locks,
  reports insufficiency separately from failures, and continues after individual failures. A configurable
  per-reader time budget is checked between operations. Only actual listing exhaustion permits batch backups.
  This keeps AI-assisted collection bounded and observable while reusing the existing selection/transfer logic.
- Collection now seeks the requested premium total, accepting degraded files only after listing exhaustion.
  Explicit resumption with degraded existing downloads looks for premium replacements without deleting files
  or decisions, so total saved files can exceed the target. Summaries include premium/degraded counts.
- Capture source URL/project ID from the API project record, with page parsing as a fallback. Normalize Gutenberg IDs, fetch original
  whole-book UTF-8 text through a listed mirror, and cache once under output_root/texts/gutenberg/ID with checksum,
  actual URL and retrieval time. No main-site scraping or Gutendex dependency. download_texts defaults true;
  false disables text-based degradation. Text settings can change on resume without invalidating section checks.
  Missing/unsupported/failed text stays visible, retries once per candidate on a later pass and never prevents
  fallback audio collection. Review-only startup reads state/cache without network or migration. Exact chapter text,
  text cleanup and audio/text alignment are outside this feature.
- The readers list accepts URL strings, positive integer/digit-string reader IDs, and objects with url or
  reader_id plus per-reader overrides. An optional _ignore field at the top level, in defaults or in reader
  objects accepts arbitrary JSON and has no effect on jobs; all other unknown fields remain errors.
  IDs normalize before duplicate/matching-URL checks. Names resolve from the
  LibriVox reader-page title at collection time, cache in state, and preserve display punctuation/dates. Explicit
  names take precedence, followed by cached labels. Failed lookup uses Reader ID and retries next invocation;
  dry runs and review mode never fetch names. Directories remain ID-based so display names don't move data.
- Empty or omitted readers are valid; validate defaults even with no readers. Overview adds readers by URL/ID
  and saves them to the supplied manifest, preserving settings and notes. The first manual addition disables
  automatic collection for future launches. auto_collect defaults true for populated batches; --browse suppresses
  collection for one launch. Refuse UI configuration writes if the manifest changed externally.
- Review provides per-reader metadata browse/rescan, increased scan target, editable collection total and Pause,
  remote previews and individual Download/quality retry. Target edits persist in JSON. Explicit individual
  requests drain only their queue and never fill a saved bulk target. One worker serializes these operations;
  decisions remain editable during network work. Review-only sessions retain no collection controls.
- Overview summarizes reader activity/errors/counts, per-reader downloaded duration and explicit collection
  controls, with smaller reader IDs below names linking to LibriVox in a new tab. Compact Goal/Files/Duration/Premium/Bad columns reserve space
  for names; the redundant Available column/card was replaced by file/premium counts. Bad includes rejected
  undownloaded candidates, so Files minus Bad is not a reliable available-file count.
  Duration sums saved section lengths for completed files still present, including rejected files,
  and displays hours:minutes:seconds; it does not decode audio. Review presents all saved
  candidates, downloaded first per reader and pending/other undownloaded entries below, local players,
  decision/status/reader filters, skipped reasons and expandable full state. Polling reorders completed cards
  without detaching their audio elements. Review
  reads legacy state without conversion or side effects. Keep/Mark bad/Clear writes only the requested decision
  and timestamp, preserving other metadata and recordings. There is no saved HTML index or review database.
- Completed readers stay idle when a recording is marked bad; Collect / resume explicitly fills their target.
  During active collection, rejected recordings don't count toward its total. Pause/shutdown stop between
  operations and wait for in-flight work; the dashboard remains open when a batch completes. Loopback audio
  serving supports seeking and stays inside each reader's output directory.
  Broken-pipe, reset and aborted browser connections close quietly at the request boundary, including header,
  polling, decision-response and media writes. Other exceptions remain visible; disconnects after a successful
  mutation do not trigger a second response or undo the saved operation.
- Review's explicit Rescan refreshes the selected reader or all readers sequentially, including in review-only
  mode with saved selection settings. Restart from page one, clear checked-project results and recheck skipped
  projects within the normal candidate target/time budget. Preserve downloads, decisions, chosen reviewed/audio
  sections and custom metadata; unreviewed pending sections can refresh. Retain ineligible old candidates but
  exclude them from new transfers. No audio/book downloads during rescan. Pause and status/error reporting are
  available. Compatibility APIs stop/join old single-reader workers before resetting checks; leave collection idle afterward and
  restart scanning only when requested. State inspection alone still performs no network work.

## Project library

Projects is an explicit listener workflow, available in JSON sessions: full reader-list scans and direct
catalog URLs. Include dramatic readings defaults false, persists in catalog state, hides cached dramatic
projects and skips their detail fetch until enabled. Repeat scan or Load / refresh details loads excluded
entries. No language, duration, solo-credit or sample-count filter applies. Scans reuse successful cached
metadata, retry failures, record exact exhaustion/failure/pause and use configured reader timeout or60minutes.
API fields add authors/language/genres/sections; reader labels use display_name. HTML fallback remains available.

Keep project state under output_root/projects/catalog.json and URL-derived project-key directories. Never
reuse or migrate sample state.json to represent a whole book. Discovering the same project through several
readers shares its section downloads. Download whole projects or sections crediting a chosen reader, including
shared casts. Prefer128, fallback64, retain files and intent, resume explicitly; reuse existing completed paths.
Metadata refresh preserves downloads; a changed audio list retains the old selection and records alternatives
rather than relabeling files as new recordings. Source books share the existing text cache; missing text is
nonfatal for this explicit whole-book workflow. One dashboard worker serializes project and sampling work.
Review-only output can show cached projects/local players, with no project mutation controls. Project sections
are rendered lazily when expanded and existing players survive polling. No global catalog crawler, automatic
whole-project jobs/headless interface or listening decisions on project sections are implemented.

## Results so far

The existing tool's live LibriVox scanning works with normal default limits. Offline HTTP regression checks
cover decisions, individual request persistence, recovery from older state files, interrupted transfers,
missing-file completion, quality fallback/retry, bulk selection rules and exclusive server binding.
See the latest dated log entry for validation of the maintenance changes and its limits.

The UI uses a persistent session header and left section navigation for Overview, Review and Projects.
View links switch content in place; history tracks views and review filters. Native links remain usable
for bookmarks, reload and opening another tab. Navigation becomes horizontal on narrow screens.

## Orientation

- `console.py`: primary standalone entry point and component export; legacy root scripts are small adapters.
- `src/librivox_download/web.py`: mounted routes and lifecycle; `sessions.py`: picker and controller switching.
- `tests/test_sessions.py`: session creation, invalid configs, draining/stale requests and copied-checkout portability.

- `src/librivox_download/fetch.py`: parsing/selection, State, scanner/downloader, compatibility single-reader CLI and legacy API.
  `download_next` performs one bounded transfer; `downloader` runs explicit requests/active collections.
- `src/librivox_download/dashboard.py` and its adjacent `dashboard.html`: Overview/Review/Projects server, UI, local audio and decisions.
- `tests/test_librivox_fetch.py`: isolated standard-library tests with temporary output and local HTTP fixtures.
- `src/librivox_download/launch.py`: validated JSON settings, resume checks, sequential reader lifecycle and final JSON summary.
- `src/librivox_download/text.py`: source links, Gutenberg URL normalization, spaced mirror requests and shared text cache.
- `src/librivox_download/projects.py`: whole-project metadata, saved library, full reader scans and scoped section downloads.
- `tests/test_projects.py`: discovery, dramatic inclusion, scoped download/recovery, metadata preservation and HTTP/media.
- `src/librivox_download/api.py`: official API lookup by ID or exact title plus URL identity, normalized sections.
- `tests/test_api_rescan.py`: API matching/fallback, fresh scan bounds, preservation, concurrency and worker lifecycle.
- `tests/test_texts.py`: offline mirror/provenance/retry, legacy enrichment and premium replacement checks.
- `batch.example.json`: example defaults, reader overrides and output root; copy to an ignored `*.local.json`.
- `tests/test_batch.py`: offline batch validation, local HTTP collection, resume, failure and interruption tests.
- `tests/test_dashboard.py`: state-only review, media ranges, decisions, concurrent collection and CLI controls.
- `tests/test_unified.py`: empty sessions, reader entry/persistence, manual controls, queue isolation and startup policy.
- `README.md`: running the tool, options and output.
- `AI/USAGE.md`: assistant instructions for setup, smoke tests and normal use.
- `AI/PROJECT_LOG.md`: initial design record and dated maintenance history.
- `downloads/`: ignored default output; no samples or per-reader state ship with the repo.

Reader download.file metadata uses portable forward-slash relative paths. Legacy backslashes are
normalized before file reconciliation and when saving collection or explicit review edits. Read-only
views do not migrate state on disk; derived inventories in consuming tools require their own rebuild.

## Known limitations

- Reader listing/name and fallback HTML parsing still depend on site markup. Project details normally use the
  API; inspect `src/librivox_download/api.py` and `read_project` if its schema changes.
- Failed project checks are saved as skips. Explicit Rescan retries them; listing failures are reported without
  enabling bulk backups. Legacy scanner APIs remain for compatibility, outside the normal launch paths.
- Completion checks confirm that the recorded file exists, not that MP3 content is valid or unmodified.
- A 64 kbps transfer failure stays failed until manually requested again; there is no unlimited retry loop.
- Batch mode retries failed transfers once on the next invocation. Its time budget is checked between
  operations, not a hard interruption of an in-flight network operation. No concurrent writers to one output.
- Reuse an output directory for the same reader and selection options. Changed selection filters require a fresh output root for collection. Explicit Rescan rechecks
  metadata using the existing filters, never silently changes selection settings.

## Open questions and next steps

No implementation decision is waiting on the user. Shared collection/review dashboard and JSON batch mode
are implemented and tested. Use the tool for the next requested sample collection, keeping any
downstream dataset placement or training/held-out split separate from download selection. Revisit parsing or
recovery only when actual use reveals another problem.
