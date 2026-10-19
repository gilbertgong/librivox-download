# Current project plan

## Goal

Gather one solo section per LibriVox project for a chosen reader, listen and record decisions in a local web UI,
and download a varied set of samples, interactively or from a JSON list of readers. Different projects provide
different recording sessions; downstream training and held-out splits remain the user's decision.

## Current direction

Keep the Python 3.12 standard-library tool and its solo-reader/length selection rules. Source books download
by default; missing text joins 64 kbps and out-of-range length as a degraded fallback. The interactive script also
provides shared state, scanning and transfer functions. JSON batch collection is the primary workflow;
batch and ad hoc single-reader commands share a two-page dashboard. Review-only startup loads saved state
without starting collection. A headless option remains for automation. No installation/build step is needed.

## Approach and reasons

- Scan only LibriVox metadata. Contact the audio host only for chosen playback/download URLs; this avoids
  unnecessary metadata requests and keeps selection grounded in the reader and project pages.
- Solo means the section's reader list is exactly the requested reader. Collaborative books are eligible;
  dramatic readings, other languages (unless disabled), and pages without per-section reader lists are skipped.
- Offer the first section in the preferred 5–15 minute range, otherwise the closest, never under one minute.
  One sample per project provides recording variety without taking entire books.
- A prime candidate is in range, selected at 128 kbps and has downloaded source text when enabled. Unchecked
  text is provisional until collection checks it. All other candidates are backups. Pause scanning at
  20 non-rejected prime candidates, or the bulk download target if larger. Rejecting/demoting one resumes scanning.
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
- Capture source URL/project ID from the already-fetched LibriVox page. Normalize Gutenberg IDs, fetch original
  whole-book UTF-8 text through a listed mirror, and cache once under output_root/texts/gutenberg/ID with checksum,
  actual URL and retrieval time. No main-site scraping or Gutendex dependency. download_texts defaults true;
  false disables text-based degradation. Text settings can change on resume without invalidating section checks.
  Missing/unsupported/failed text stays visible, retries once per candidate on a later pass and never prevents
  fallback audio collection. Review-only reads state/cache without network or migration. Exact chapter text,
  text cleanup and audio/text alignment are outside this feature.
- The readers list accepts URL strings, positive integer/digit-string reader IDs, and objects with url or
  reader_id plus per-reader overrides. An optional _ignore field at the top level, in defaults or in reader
  objects accepts arbitrary JSON and has no effect on jobs; all other unknown fields remain errors.
  IDs normalize before duplicate/matching-URL checks. Names resolve from the
  LibriVox reader-page title at collection time, cache in state, and preserve display punctuation/dates. Explicit
  names take precedence, followed by cached labels. Failed lookup uses Reader ID and retries next invocation;
  dry runs and review mode never fetch names. Directories remain ID-based so display names don't move data.
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

## Results so far

The existing tool's live LibriVox scanning works with normal default limits. Offline HTTP regression checks
cover decisions, individual request persistence, recovery from older state files, interrupted transfers,
missing-file completion, quality fallback/retry, bulk selection rules and exclusive server binding.
See the latest dated log entry for validation of the maintenance changes and its limits.

## Orientation

- `librivox_fetch.py`: parsing/selection, State, scanner/downloader, single-reader CLI and compatibility API.
  `download_next` performs one bounded transfer; `downloader` runs explicit requests/active collections.
- `librivox_dashboard.py` and `dashboard.html`: shared Overview/Review server, UI, local audio and decisions.
- `tests/test_librivox_fetch.py`: isolated standard-library tests with temporary output and local HTTP fixtures.
- `librivox_batch.py`: validated JSON settings, resume checks, sequential reader lifecycle and final JSON summary.
- `librivox_text.py`: source links, Gutenberg URL normalization, spaced mirror requests and shared text cache.
- `tests/test_texts.py`: offline mirror/provenance/retry, legacy enrichment and premium replacement checks.
- `batch.example.json`: example defaults, reader overrides and output root; copy to an ignored `*.local.json`.
- `tests/test_batch.py`: offline batch validation, local HTTP collection, resume, failure and interruption tests.
- `tests/test_dashboard.py`: state-only review, media ranges, decisions, concurrent collection and CLI controls.
- `README.md`: running the tool, options and output.
- `AI/USAGE.md`: assistant instructions for setup, smoke tests and normal use.
- `AI/PROJECT_LOG.md`: initial design record and dated maintenance history.
- `downloads/`: ignored default output; no samples or per-reader state ship with the repo.

## Known limitations

- LibriVox HTML parsing uses regular expressions tied to the site's current markup. If scanning breaks after a
  site change, inspect `listing_pages` and `read_project` first.
- Failed project-page checks are saved as skips. A listing-level exception stops scanning; the existing worker
  treats that as scanning finished, which also permits bulk backups. Read the UI status before judging coverage.
- Completion checks confirm that the recorded file exists, not that MP3 content is valid or unmodified.
- A 64 kbps transfer failure stays failed until manually requested again; there is no unlimited retry loop.
- Batch mode retries failed transfers once on the next invocation. Its time budget is checked between
  operations, not a hard interruption of an in-flight network operation. No concurrent writers to one output.
- Reuse an output directory for the same reader and selection options. Existing checked projects are not
  re-evaluated when CLI filters change; use a fresh `--out` to make a new selection.

## Open questions and next steps

No implementation decision is waiting on the user. Shared collection/review dashboard and JSON batch mode
are implemented and tested. Use the tool for the next requested sample collection, keeping any
downstream dataset placement or training/held-out split separate from download selection. Revisit parsing or
recovery only when actual use reveals another problem.
