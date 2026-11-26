# Usage guide

Collect a LibriVox reader's solo recordings, one sample per project, and review them in a local dashboard.
Give it a JSON list of readers to collect samples sequentially, or browse and download complete projects for listening.
Source books download by default when a recording links to Project Gutenberg. Python 3.12, standard library only.

The dashboard also supports [hosting as a component in a shared console](components.md).
Its [microweb](https://github.com/gilbertgong/microweb) framework is bundled with license text embedded in file; no package installation is required.
`microweb-component.json` also enables local discovery by optional shell launchers, with automatic collection disabled.

## Launch the dashboard

From the repo root, run:

```sh
python -B librivox_web.py
```

Without a filename, the dashboard opens `session.local.json` in the directory you launched from, creating it as
`{}` the first time; recordings then go to `downloads/` beside it. **Change session** shows the session picker:
choose an existing JSON file or use **New session** and enter a filename. New files live under `sessions/` in the
launch directory; that folder is ignored by Git. The picker also lists JSON files directly in the launch
directory, including existing batch files, and reports invalid configurations. Existing files are never replaced.
A `.json` extension is added to new names if omitted.

The header shows **Session: filename**; hover for the full path. **Change session** opens the picker again.
Opening a session pauses current work, waits for the current operation to finish, and loads the selected
configuration without restarting the server or other hosted components. Recordings and decisions stay saved.
Sessions opened from the picker stay idle until you explicitly collect or scan.

To launch a particular session directly, use `python -B librivox_web.py sessions/my-readers.json` or an existing
JSON path anywhere else. An explicit missing file is created as `{}` if its parent directory exists.
Invalid existing files are reported rather than replaced. Dry runs and headless runs require an explicit,
existing valid file. Startup prints the full settings-file path.

New sessions created through the picker set `auto_collect: false` and `output_root: "../downloads"`, so
recordings still go under the launch directory's `downloads/`, outside `sessions/`. Existing configurations
keep their own paths: relative output roots are always resolved against the JSON file's directory. Set distinct
output roots if separate sessions need independent libraries or different selection settings.

Reader entry is available while collection is idle. During scanning or downloading, an explanation beside
the disabled control tells you to wait or pause collection before adding another reader.

Overview opens with **Add a reader**: enter a reader URL or ID and a collection goal. The dashboard saves it
in that JSON file. Follow the reader's name to **Review**, where the controls above their recordings let you:

- **Browse / rescan**: find candidates and refresh metadata without downloading audio or books.
- **Scan 10 more**: raise the candidate target by ten and refresh the scan.
- Set **Total**, then **Collect / resume** to collect that many premium recordings in total.
- **Download** an individual candidate, or retry a failed download, without filling the bulk target.
- Listen to remote **Source previews** before downloading; completed recordings play from disk.
- Use **Retry 128 kbps** after a failed preview or fallback. This selects the quality; Download requests it.

The first reader added to an empty session sets `auto_collect` to `false`, so reopening it stays idle.
`{"readers": []}` also works; use a valid JSON object rather than a zero-byte file. A populated batch still
collects automatically by default. Add `"auto_collect": false` to keep it manual, or use `--browse` for a
single launch without automatic collection. Reader additions and Total changes are saved to the manifest;
other settings and `_ignore` notes are preserved. If the JSON changes outside the dashboard, use **Change session**
to reopen that file before changing readers or totals through the UI. One worker runs collection, scanning or an
individual download at a time; Pause stops after the current operation. Listening decisions remain available.

## Collect a batch

Copy [batch.example.json](../batch.example.json) to `batch.local.json`, replace the example readers, then run
these commands from the repo root:

```sh
python -B librivox_web.py batch.local.json --dry-run
python -B librivox_web.py batch.local.json
```

Open the printed address (default http://127.0.0.1:8765/). Collection starts automatically. The dashboard stays
open after all readers finish; Ctrl+C closes it. Use `--port 8766` if another instance uses the default port.
The dry run validates and prints resolved jobs without writing output or contacting remote services.

## Three dashboard views

Use the left sidebar to switch between Overview, Review and Projects. The session header and sidebar stay
in place while the content changes, preserving entered values without a page reload. On narrow screens,
the navigation appears above the content. Browser Back, bookmarks and reload retain the selected view
and review filters.

- **Overview:** reader names with smaller reader IDs below linking to their LibriVox pages, current activity/errors, and compact columns for
  Goal, Files, Duration, Premium and Bad. Files counts completed downloads still present, including bad files.
  Premium counts preferred recordings; Bad counts all rejected candidates, including ones not downloaded.
  Duration uses saved LibriVox section lengths, shown as hours:minutes:seconds. It includes files marked bad
  and excludes missing files. The page also provides collection controls
  and links to review all recordings or one reader. Collect / resume starts another pass for all readers or the
  selected reader. Pause collection stops after the current operation, keeping its progress.
- **Review:** all saved candidates grouped by reader, with downloaded recordings first and pending/other
  undownloaded candidates below them. Each project has audio players, section lengths and qualities,
  source links, download statuses/errors, and Keep / Mark bad / Clear decision. Filter by reader, download status
  or decision. Expand skipped projects for reasons, recording details for individual metadata, and saved state
  details for everything else in `state.json`. Per-reader manual controls sit above the recordings when opened
  with a JSON file. Polling doesn't replace audio players or reset an edited Total while you're listening.

- **Projects:** whole-book browsing, section players and project downloads. Scan a reader's complete listing
  or open a project URL, with optional dramatic readings and title/author search.

For reader samples, Mark bad records the existing rejection decision; it never deletes the audio. During active collection, rejected
files don't count toward the target. Once a reader finishes, marking something bad **does not restart collection**.
Use Collect / resume explicitly to fill the target with replacements. The last collection result and the current
file and premium counts are shown separately. Summary cards show readers, downloaded files and premium recordings.

## Browse and download projects

Open **Projects** in a JSON session. Enter a reader URL or ID and choose **Scan all projects**, or enter a
catalog project URL and **Open project**. A project card shows authors, language, type, sections, duration
and downloaded count when the source metadata supplies them. Opening a URL puts that project first and
scrolls it into view on the current page. Click a project name for a focused modal with its sections and
download controls; Close or Escape returns to the list. A smaller LibriVox page link sits underneath the name.
Expand its section list to preview audio;
completed sections use local players. Search by title or author.

**Include dramatic readings** is off by default. Scanning records excluded dramatic projects without loading
their sections. Enable the checkbox, then scan the reader again or use **Load / refresh details** on a project
to load those sections. Disabling it hides cached dramatic projects without deleting anything. Ordinary reader
sampling continues to exclude dramatic readings and require solo sections.

Project scanning covers the reader's entire listing, with every language and section length, rather than the
sampling candidate target. It is an explicit network operation and downloads no audio or books. Progress saves
between projects; Pause stops after the current operation. The reader's configured time budget applies, or
60 minutes for an unconfigured reader. Repeat a scan to reuse successful cached metadata and retry failures;
use Load / refresh details to refresh a successfully loaded project. This browses readers' projects, not the
entire LibriVox catalog. Reader scans here do not add or alter sampling jobs in the JSON session.

Choose **Download entire project**, or select a credited reader and **Download reader's sections**. The latter
includes shared cast sections crediting that reader. Downloads run sequentially, prefer 128 kbps and fall back
to 64 kbps after failure. Repeat the same request to resume or retry: completed files still present are reused,
missing files are restored, and failed sections receive another attempt. Pause and interrupted requests keep
their progress but never restart automatically when you reopen the dashboard.

Project downloads save separately under `<output_root>/projects/<project-key>/`, with one file per section.
`<output_root>/projects/catalog.json` records metadata, scans, section credits, requests and transfer results;
project keys are derived from catalog URLs, so projects discovered through several readers share one copy.
Sample `state.json` files and recordings are independent. Metadata refresh preserves downloads; if the audio
list has changed, the saved selection is retained and the revised list recorded for inspection. Use another
output root for that revised edition. Existing audio is never deleted.

Source-book downloads follow the session defaults (or the configured reader's overrides for reader-scoped
requests) and share the existing Gutenberg cache. Missing text is reported but does not prevent whole-project
audio downloads. Metadata comes from the official API with an HTML fallback; unavailable author/type/credit
information is shown as unknown rather than invented. Opening the output root with `--review` also shows its
saved Projects library and local players, with scanning and download controls unavailable.

## Reopen for review

```sh
python -B librivox_web.py --review downloads
```

The path may be an output root containing reader folders, a single reader directory, or a `state.json` file.
Review mode starts no scanning or downloading and doesn't change state merely by opening it. Decisions you make
are saved back to the existing state files, preserving other metadata. Legacy state without selection settings
can also be reviewed. Collection controls are unavailable: open the batch JSON to collect replacements.

### Refresh metadata with Rescan

On Review, select a reader and click **Rescan**, or choose All readers to refresh them sequentially. This starts
from the first reader-list page and rechecks projects, including previous skips/errors. It stops at the
candidate target, listing exhaustion, or the reader time budget. In a collection dashboard the target is twice the
reader's collection total (review mode uses at least 20); a larger target already saved for the reader is kept.
Pause scan stops after the current check. Use this when catalog information changes or you want to retry earlier
checks.

Rescan only refreshes metadata: it does not collect audio or books. Downloaded/reviewed candidates retain their
chosen section, recordings and decisions; refreshed alternatives are recorded in their details. Unreviewed,
undownloaded candidates can refresh their section/quality. Previous files and custom metadata are preserved.
Candidates that are no longer eligible remain visible but are not selected for new transfers. Collection must
be idle before a rescan. To download newly discovered candidates, use Collect / resume in a collection dashboard.

The button works in review-only mode using saved selection settings, without changing them. Legacy state with
unknown filters remains reviewable but needs a new configured collection for scanning. Rescan results and errors
appear under each reader. Ordinary review startup, playback and decisions never start a scan automatically.

Local players use the saved files, with seeking support. Missing files are labeled; source URLs remain available
as links. There is no generated HTML index or separate review database. The dashboard reconstructs its view from
saved state, so you can close it and reopen it later. It binds only to this computer's loopback address.
Cancelled browser connections (for example, during navigation or stopped playback) close quietly rather than
printing a traceback; other unexpected request-handler errors remain visible in the console.

## Batch JSON

The file has an optional `defaults` object, an `output_root`, and a `readers` list (empty or omitted for manual entry). Readers can be plain
URLs, integer reader IDs, or digit strings. An optional `_ignore` field at the top level, in `defaults`, or in
a reader object can hold any JSON value (notes, parked settings, or unused reader lists); its contents are
ignored and never included in resolved jobs. It does not disable the reader object containing it.
Use an object with `url` or `reader_id` to override a setting or
supply a custom `name`. These forms can mix:

```json
{
  "defaults": {"count": 10},
  "readers": [
    "https://librivox.org/reader/6281/",
    {"reader_id": 456, "count": 15}
  ]
}
```

A simple ID-only list also works: `"readers": [6281, 456]`. IDs must be positive integers or digit strings.
If an object supplies both `url` and `reader_id`, they must match. Duplicate readers are rejected across all
input formats, including IDs with leading zeros.

Without an explicit name, collection fetches the reader's display name from their LibriVox page and caches it
in `state.json`, including any dates/punctuation in that name. Saved names are reused on subsequent runs; an
explicit JSON name takes precedence. If lookup fails, collection continues as `Reader ID` and tries the name
again on a later invocation. Dry runs remain offline and show pending names as `Reader ID`. Output directory
identity always uses the reader ID. Replace the sample URLs in the example file with your desired readers.

| Setting | Default | Meaning |
|---|---|---|
| `count` | 10 | preferred number of premium recordings per reader; degraded fallbacks fill shortages after listing exhaustion |
| `language` | `English` | project language; empty string permits any |
| `range_minutes` | `[5, 15]` | preferred section length; closest eligible section is a backup |
| `min_seconds` | 60 | minimum section length |
| `order` | `alpha` | listing order: `alpha` or `catalog_date` |
| `timeout_minutes` | 60 | per-reader budget, checked between operations |
| `download_texts` | `true` | download linked Gutenberg books and treat missing text as degraded; `false` selects audio only |
| `text_mirror` | `https://gutenberg.pglaf.org` | mirror root serving generated UTF-8 files under `cache/epub/ID/pgID.txt` |

`output_root` defaults to `downloads` **relative to the JSON file**, independent of the working directory.
Each reader gets `<output_root>/<reader_id>/state.json` and project audio subdirectories. Reader IDs stay stable
when names change. Duplicate IDs and invalid settings are rejected before collection begins.

Run the same batch again or use Collect / resume to continue. Failed transfers receive one new attempt per
invocation/pass; failures aren't retried indefinitely. Existing files and listening decisions are preserved.
Collection requires state with the same reader and recorded selection settings. Older state with unknown
filters, or changed language/range/minimum/order, requires a new output root; existing data remains reviewable.
Count, time budget and text settings may change on resumption. Do not run two processes against the same output
root, including its shared text cache.

## Source books

Each candidate records the LibriVox project ID and `url_text_source` from its API record (the catalog page labels
this **Online text**). Recognized Gutenberg links also record the ebook ID and canonical landing-page URL.
The same project-details request supplies sections and source provenance. HTML is a fallback when API details
are unavailable; older saved candidates can be enriched without changing their selected recording.

Collection downloads the linked whole book as UTF-8 plain text from a
[Gutenberg-listed mirror](https://www.gutenberg.org/MIRRORS.ALL), following its
[automated-download guidance](https://www.gutenberg.org/policy/robot_access.html). It uses the mirror's generated
text path directly, without a Gutendex dependency or requests to the main Gutenberg website. Mirror requests
are spaced at least two seconds apart. Alternate `text_mirror` values must serve that same directory layout;
redirects to the main website are refused.

Books are cached once under `<output_root>/texts/gutenberg/<id>/source.txt`, shared across readers/projects.
The original bytes and Gutenberg header/footer remain intact. `source.json` records the actual download URL,
retrieval time, byte count and SHA-256 checksum; candidate state links the recording to this cache. Review cards
show the source link, text status and **Open local text**. Keep the shared `texts` directory when moving a collection.

Missing links, non-Gutenberg sources and failed downloads remain explicit statuses and make the recording
degraded when text downloads are enabled. They do not stop audio collection. Failed/missing text gets one new
attempt per candidate on a later collection pass, while valid cached books are reused. Existing completed audio
can gain source metadata/text on resumption without being downloaded again. Review-only mode does none of this
network work and does not rewrite state merely because a cached text has gone missing.

This retrieves **whole source books**, not chapter transcripts or aligned passages. It does not clean the text,
extract chapters or establish that every spoken word matches the downloaded edition.

## Headless collection

For an assistant or script that needs a command which exits when collection finishes:

```sh
python -B librivox_web.py batch.local.json --headless > batch-summary.local.json
```

Progress goes to stderr and the final JSON summary goes to stdout. In a terminal the download counter updates
on one line; redirected logs contain distinct counter updates on separate lines, without terminal controls.
Each reader reports `completed`,
`insufficient`, `failed`, or `interrupted`; remaining readers after Ctrl+C are `not_run`. Failures and insufficient
results allow the next reader to proceed. Exit status is 0 if all targets are met, 1 for incomplete/failed
readers, 2 for invalid configuration, or 130 for interruption. These outcome codes apply to headless mode;
closing a dashboard normally returns 0, and collection outcomes remain on its Overview page.
The summary includes `premium` and `degraded` counts. A completed reader can include degraded fallbacks when
the listing has been exhausted; its detail field says so.

An operation already in progress may finish after a pause request or time budget. Existing connection/read
timeouts govern in-flight network operations. Ctrl+C requests a stop and waits for the current operation;
Ctrl+C again forces shutdown. Interrupted transfer intent remains saved for resumption. No worker/server is
left running after normal shutdown. The final headless summary is an outcome report for that invocation;
per-reader state is authoritative. Personal `*.local.json` batch files and reports are ignored by Git.

## How recordings are selected

All selection metadata comes from LibriVox; the audio host is contacted only for chosen playback/download URLs.
The [official API](https://librivox.org/api/info) supplies project sections, reader IDs, durations and source-text
links. Known project IDs are queried directly; otherwise an exact-title API search is paginated and the catalog
URL must match before a result is used. Sections are ordered by their section number. Unsupported/incomplete
API data or request failures fall back to the project page; provenance records the fallback reason. The reader
listing and reader-name lookup still use the website because the documented API has no reader-search endpoint.
A project is eligible if a section lists exactly the requested reader and meets the minimum length. Dramatic
readings, other languages, and pages without individual section readers are skipped. Collaborative books are fine.

Each project offers the first section in the preferred range, otherwise the closest eligible section. In-range
128 kbps candidates with downloaded source text are premium (called prime internally); other candidates are
backups. Disabling text downloads removes the text requirement. Collection prefers premiums and uses backups only
after the listing is exhausted. A 128 kbps transfer failure makes a candidate eligible for 64 kbps fallback.
Keep is a listening annotation, not a download prerequisite. Listening judgments are never made automatically.
Resuming with degraded downloads searches for premium replacements, preserving earlier files and decisions;
the downloaded count can exceed the target. Completed collections stay idle until explicitly resumed.

Downloaded audio paths in reader `state.json` use forward slashes, including on Windows. Older backslash
paths are normalized when collection loads/saves the state or an explicit review edit saves it. Audio files
keep their existing names and locations. Tools that already derived records from older paths may need
to rebuild those records.

Queued requests and interrupted transfers are preserved. Resume a collection explicitly, or request an individual
Download again. Transfers restart from the beginning of their `.part` file rather than resuming byte offsets.
Existing files are never deleted by Keep/Mark bad/quality changes.

