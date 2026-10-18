# librivox-download

Find a LibriVox reader's solo recordings, one sample per project, vet them by ear on a local web page, and download
samples you haven't rejected, preferring 128 kbps MP3s with 64 kbps fallback.

Python 3.12, standard library only.

## Usage

```
python librivox_fetch.py "Beth Thomas" https://librivox.org/reader/6281/
```

Then open http://127.0.0.1:8765/. Stop the server with Ctrl+C; running it again resumes where it left off.
Individual download requests and unfinished bulk targets survive restarts. Interrupted transfers restart from
the beginning; they do not resume from a byte offset. Use a separate `--out` for another reader or new filters.

## Batch downloads

For unattended collection from several readers, copy [batch.example.json](batch.example.json) to
`batch.local.json`, replace the example readers with your choices, and run:

```sh
python -B librivox_batch.py batch.local.json --dry-run
python -B librivox_batch.py batch.local.json
```

Batch mode runs without a browser or web server. Readers are processed sequentially, one section per project,
using the same selection and 128/64 kbps fallback rules. It stops downloading for each reader when their total
count is reached. Backups are used only after the listing is exhausted. It doesn't make listening judgments.

The JSON has an optional `defaults` object, an `output_root`, and a nonempty `readers` list. Each reader supplies
`url`, optionally `name`, and any overrides of the defaults. Without a name, the display label is `Reader ID`.
The sample IDs/names in the example are placeholders to replace before collection.

| Setting | Default | Meaning |
|---|---|---|
| `count` | 10 | total non-rejected completed recordings per reader, including earlier downloads |
| `language` | `English` | project language; empty string permits any |
| `range_minutes` | `[5, 15]` | preferred section length; closest eligible section is a backup |
| `min_seconds` | 60 | minimum section length |
| `order` | `alpha` | listing order: `alpha` or `catalog_date` |
| `timeout_minutes` | 60 | per-reader budget, checked between operations |

`output_root` defaults to `downloads` **relative to the batch JSON file**, independent of the working directory.
Each reader gets `<output_root>/<reader_id>/state.json` and project audio subdirectories. Reader IDs remain
stable when names change. Duplicate IDs and invalid settings are rejected before collection begins.

Run the same batch again to resume. Failed transfers receive one new attempt per invocation; failures are not
retried indefinitely within a run. Existing files and decisions are preserved. Saved state must belong to that
reader and record matching selection settings; older state without settings or a changed language/range/minimum/
order is refused with a message to choose a new output root. Count and time budget can change on resumption.
Do not run two processes against the same output directory at once.

Progress is printed to stderr; the final JSON summary is printed to stdout, so it can be saved separately:

```sh
python -B librivox_batch.py batch.local.json > batch-summary.local.json
```

Each reader is reported as `completed`, `insufficient`, `failed`, or `interrupted`; readers remaining after
Ctrl+C are `not_run`. Failures and insufficient results allow the next reader to proceed. Exit status is 0 if
all targets are met, 1 for incomplete/failed readers, 2 for invalid configuration, or 130 for interruption.
An operation already in progress may finish after the configured time budget; network calls retain their
existing connection/read timeouts. Ctrl+C stops the batch without leaving background workers or a server.
Per-reader state remains the authoritative record; the final summary is an outcome report for that invocation.

## How it works

- The reader's project listing is scanned in the background. A project is a candidate if one of its sections is
  read by this reader alone and is at least a minute long. Dramatic readings, other languages, and projects that
  don't list readers per section are skipped.
- Each candidate offers one section: the first 5–15 minutes long, or the closest to that range.
- A candidate is **prime** if that section is in the range and has a 128 kbps file. The rest are **backups**: no
  section in the range, or only 64 kbps (no 128 kbps file, or it failed to play or download). Backups are listed
  below the prime candidates and don't count toward the target.
- Scanning stops at 20 prime candidates that you haven't rejected. Rejecting one makes it look further;
  "Scan 10 more" raises the target.
- The page shows progress (including how many you've kept and rejected), a card per candidate (section, length, and Keep / Reject left of the player, Download right of it), the backups,
  and the skipped projects with reasons. Keep marks a sample you've listened to and approved.
- "Download N" (default 10) has the server download the first N candidates you haven't rejected, prime first;
  backups only if the reader's listing runs out of prime candidates. When all N are done, the page turns pale
  blue and says so.
- An individual Download request tries 64 kbps automatically if its 128 kbps transfer fails. After a playback
  error, Retry 128 kbps lets you try that player URL again; an error can be temporary. If you've already downloaded
  64 kbps, click Download after retrying to request the 128 kbps version. Existing recordings are kept.
- Completed downloads count only while their recorded files exist. Missing files are marked on their cards
  and can be downloaded again; an unfinished bulk target also restores missing eligible samples.

## Options

| Option | Default | |
|---|---|---|
| `--projects` | 20 | prime candidates to find |
| `--count` | 10 | the page's default N for "Download N" |
| `--range MIN MAX` | 5 15 | preferred section length, minutes |
| `--min-seconds` | 60 | never offer a shorter section |
| `--out` | `downloads/<name>` | output folder (the default is next to the script) |
| `--order` | alpha | listing order: `alpha` or `catalog_date` |
| `--language` | English | `''` for any |
| `--port` | 8765 | |

## Output

- `<out>/<project>/`: the downloaded MP3.
- `<out>/state.json`: the record of everything: each project checked (and why it was skipped), each candidate's
  chosen section, your keep / reject decisions, queued requests and each download, with the time of each change.

Rejecting a downloaded sample doesn't delete it. Keep is a listening annotation; Download N takes any candidate
you haven't rejected, and N includes samples already downloaded in this output directory.

## Checks and assistant help

Run the offline regression checks from the repo root:

```sh
python -B -m unittest discover -s tests -v
```

They cover interactive and batch workflows using temporary files and local HTTP fixtures, with no third-party
dependencies or external requests. Personal `*.local.json` batch files/reports are ignored by Git.
For assistant-guided setup, smoke tests and downloads, see [AI/USAGE.md](AI/USAGE.md).
[AI/STRATEGY.md](AI/STRATEGY.md) describes how the repo keeps context for AI-assisted work.
