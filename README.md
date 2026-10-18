# librivox-download

Collect a LibriVox reader's solo recordings, one sample per project, and review them in a local dashboard.
Give it a JSON list of readers to collect sequentially, then listen and mark recordings to keep or reject.
Python 3.12, standard library only.

## Collect a batch

Copy [batch.example.json](batch.example.json) to `batch.local.json`, replace the example readers, then run
these commands from the repo root:

```sh
python -B librivox_batch.py batch.local.json --dry-run
python -B librivox_batch.py batch.local.json
```

Open the printed address (default http://127.0.0.1:8765/). Collection starts automatically. The dashboard stays
open after all readers finish; Ctrl+C closes it. Use `--port 8766` if another instance uses the default port.
The dry run validates and prints resolved jobs without writing output or contacting remote services.

## Two dashboard pages

- **Overview:** reader progress, current activity/errors, requested totals, downloaded/available/rejected counts,
  and total downloaded duration per reader (hours:minutes:seconds, using saved LibriVox section lengths).
  Duration includes files marked bad and excludes missing files. The page also provides collection controls
  and links to review all recordings or one reader. Collect / resume starts another pass for all readers or the
  selected reader. Pause collection stops after the current operation, keeping its progress.
- **Review:** all saved candidates grouped by reader/project, local audio players, section lengths and qualities,
  source links, download statuses/errors, and Keep / Mark bad / Clear decision. Filter by reader, download status
  or decision. Expand skipped projects for reasons, recording details for individual metadata, and saved state
  details for everything else in `state.json`. Polling doesn't replace audio players while you're listening.

Mark bad records the existing rejection decision; it never deletes the audio. Available means a completed file
exists and isn't rejected, not that someone has listened and approved it. During active collection, rejected
files don't count toward the target. Once a reader finishes, marking something bad **does not restart collection**.
Use Collect / resume explicitly to fill the target with replacements. The last collection result and the current
available count are shown separately.

## Reopen for review

```sh
python -B librivox_batch.py --review downloads
```

The path may be an output root containing reader folders, a single reader directory, or a `state.json` file.
Review mode starts no scanning or downloading and doesn't change state merely by opening it. Decisions you make
are saved back to the existing state files, preserving other metadata. Legacy state without selection settings
can also be reviewed. Collection controls are unavailable: open the batch JSON to collect replacements.

Local players use the saved files, with seeking support. Missing files are labeled; source URLs remain available
as links. There is no generated HTML index or separate review database. The dashboard reconstructs its view from
saved state, so you can close it and reopen it later. It binds only to this computer's loopback address.

## Batch JSON

The file has an optional `defaults` object, an `output_root`, and a nonempty `readers` list. Readers can be plain
URLs, integer reader IDs, or digit strings. Use an object with `url` or `reader_id` to override a setting or
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
| `count` | 10 | total non-rejected completed recordings per reader, including earlier downloads |
| `language` | `English` | project language; empty string permits any |
| `range_minutes` | `[5, 15]` | preferred section length; closest eligible section is a backup |
| `min_seconds` | 60 | minimum section length |
| `order` | `alpha` | listing order: `alpha` or `catalog_date` |
| `timeout_minutes` | 60 | per-reader budget, checked between operations |

`output_root` defaults to `downloads` **relative to the JSON file**, independent of the working directory.
Each reader gets `<output_root>/<reader_id>/state.json` and project audio subdirectories. Reader IDs stay stable
when names change. Duplicate IDs and invalid settings are rejected before collection begins.

Run the same batch again or use Collect / resume to continue. Failed transfers receive one new attempt per
invocation/pass; failures aren't retried indefinitely. Existing files and listening decisions are preserved.
Collection requires state with the same reader and recorded selection settings. Older state with unknown
filters, or changed language/range/minimum/order, requires a new output root; existing data remains reviewable.
Count and time budget may change on resumption. Do not run two processes against the same output directory.

## Headless collection

For an assistant or script that needs a command which exits when collection finishes:

```sh
python -B librivox_batch.py batch.local.json --headless > batch-summary.local.json
```

Progress goes to stderr and the final JSON summary goes to stdout. In a terminal the download counter updates
on one line; redirected logs contain distinct counter updates on separate lines, without terminal controls.
Each reader reports `completed`,
`insufficient`, `failed`, or `interrupted`; remaining readers after Ctrl+C are `not_run`. Failures and insufficient
results allow the next reader to proceed. Exit status is 0 if all targets are met, 1 for incomplete/failed
readers, 2 for invalid configuration, or 130 for interruption. These outcome codes apply to headless mode;
closing a dashboard normally returns 0, and collection outcomes remain on its Overview page.

An operation already in progress may finish after a pause request or time budget. Existing connection/read
timeouts govern in-flight network operations. Ctrl+C requests a stop and waits for the current operation;
Ctrl+C again forces shutdown. Interrupted transfer intent remains saved for resumption. No worker/server is
left running after normal shutdown. The final headless summary is an outcome report for that invocation;
per-reader state is authoritative. Personal `*.local.json` batch files and reports are ignored by Git.

## How recordings are selected

All selection metadata comes from LibriVox; the audio host is contacted only for chosen playback/download URLs.
A project is eligible if a section lists exactly the requested reader and meets the minimum length. Dramatic
readings, other languages, and pages without individual section readers are skipped. Collaborative books are fine.

Each project offers the first section in the preferred range, otherwise the closest eligible section. In-range
128 kbps candidates are prime; other candidates are backups. Collection prefers primes and uses backups only
after the listing is exhausted. A 128 kbps transfer failure makes a candidate eligible for 64 kbps fallback.
Keep is a listening annotation, not a download prerequisite. No transcripts are downloaded or listening judgments
made automatically.

## Ad hoc single-reader use

```sh
python -B librivox_fetch.py "READER NAME" https://librivox.org/reader/READER_ID/
```

This opens the same dashboard and scans for candidates. On Overview, choose a total and Collect / resume, or
use Download on a Review card. Single-reader mode also offers remote source previews for undownloaded candidates,
Retry 128 kbps after a failed preview, and Scan 10 more. Completed recordings play from disk.

| Option | Default | Meaning |
|---|---|---|
| `--projects` | 20 | prime candidates to gather for browsing |
| `--count` | 10 | initial collection total shown in the dashboard |
| `--range MIN MAX` | 5 15 | preferred length in minutes |
| `--min-seconds` | 60 | minimum section length |
| `--out` | `downloads/<name>` | output folder, default next to the script |
| `--order` | alpha | `alpha` or `catalog_date` |
| `--language` | English | empty string permits any |
| `--port` | 8765 | loopback dashboard port |

Queued individual requests and unfinished collection targets survive restarts. Transfers restart from the
beginning of their `.part` file rather than resuming byte offsets. Use a new output directory for a different
reader or changed selection filters. Existing files are never deleted by Keep/Mark bad/quality changes.

## Checks and assistant help

```sh
python -B -m unittest discover -s tests -v
```

Tests cover collection and review using temporary files and local HTTP fixtures; no third-party dependencies
or external requests. [AI/USAGE.md](AI/USAGE.md) describes assistant-guided setup, collection and review.
[AI/STRATEGY.md](AI/STRATEGY.md) explains how the repo keeps context for AI-assisted work.
