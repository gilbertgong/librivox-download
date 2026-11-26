# librivox-download

Download and review [LibriVox](https://librivox.org/) recordings in a local web dashboard.
Collect samples from a list of readers, or browse and download complete audiobook projects.
Linked Project Gutenberg texts download alongside the audio by default.

Requires **Python 3.12+**. No third-party runtime dependencies.

## Quick start

Clone the repository, then from its folder:

```sh
python librivox_web.py
```

Open the printed local URL and add readers by URL or ID. Browse recordings, listen, download, and mark
recordings to keep or avoid. The dashboard is reachable only from this computer; use `--port` if 8765 is taken.

## Sessions and files

A session is a JSON file listing readers and their settings.

- Without a filename, the dashboard opens `session.local.json` in the current folder, creating it the first time.
  Pass a path to open another; a missing file is created if its folder exists. **Change session** switches to
  another session or creates one in `sessions/`.
- Recordings go to the session's `output_root`: by default `downloads/` beside the session file. Sessions created
  in the dashboard use `../downloads`, so they share the launch folder's library.
- Existing session files are never replaced. After editing one by hand, reopen it with **Change session** before
  changing readers or totals in the dashboard.
- Switching sessions pauses the current work, waits for the operation in progress, and opens the new one idle.
- Each reader's candidates, decisions and downloads are recorded in `<output_root>/<reader id>/state.json`.
  Don't run two processes against the same output folder.

## What gets collected

- One section per project, taken from sections that reader reads alone. Collaborative books count; dramatic
  readings don't. English only, unless configured otherwise.
- A **premium** recording is 5–15 minutes long, 128 kbps and has its source text. Other recordings of at least a
  minute are **backups**. A failed 128 kbps download falls back to 64 kbps, which makes the recording a backup.
- Collection uses backups only after reading the reader's **whole listing**. A reader with few premium recordings
  can be scanned for a long time before enough are downloaded.
- The goal (**Total**) is how many premium recordings you want altogether, including earlier downloads. Backups
  make up a shortfall.
- **Collect / resume** scans only until the goal is met. **Rescan** looks for twice the goal in premium candidates
  (at least 20 in review mode), or for a larger target already saved for the reader.
- You can **Download** any single candidate yourself, backup or not.
- **Mark bad** deletes nothing. The recording stops counting, but a finished reader isn't collected again until you
  click **Collect / resume**.
- **Pause** stops after the current operation. Interrupted downloads start over from the beginning of the file.

## Batch collection

Copy [batch.example.json](batch.example.json) and list your readers:

```json
{
  "defaults": {"count": 10},
  "output_root": "downloads",
  "readers": [
    "https://librivox.org/reader/123/",
    456,
    {"reader_id": 789, "count": 15, "name": "Custom name"}
  ]
}
```

```sh
python librivox_web.py batch.local.json
```

Opening a file this way **starts collecting**, one reader at a time, unless it contains `"auto_collect": false`
or you pass `--browse`. Adding the first reader to an empty session in the dashboard sets `auto_collect` to false.

A reader is a URL, an ID or an object, and may appear only once. These settings go in `defaults` or in a reader
object:

| Setting | Default | Meaning |
|---|---|---|
| `count` | 10 | the goal: premium recordings wanted per reader |
| `language` | `"English"` | project language; `""` allows any |
| `range_minutes` | `[5, 15]` | preferred section length |
| `min_seconds` | 60 | shortest section considered |
| `order` | `"alpha"` | listing order: `"alpha"` or `"catalog_date"` |
| `timeout_minutes` | 60 | time budget per reader, checked between operations |
| `download_texts` | `true` | download source texts and require them for premium |
| `text_mirror` | `"https://gutenberg.pglaf.org"` | Gutenberg mirror serving `cache/epub/ID/pgID.txt` |

- A reader object may set `name`. Otherwise the name is fetched from LibriVox and saved; until then it shows as
  `Reader <id>`.
- `_ignore`, at the top level, in `defaults` or in a reader object, holds notes or parked values. It doesn't
  disable the reader containing it.
- Run the same file again to resume. Each run retries failed downloads once. `count`, `timeout_minutes` and text
  settings can change; changing `language`, `range_minutes`, `min_seconds` or `order` needs a new `output_root`.
- `--dry-run` checks the file and prints the resolved readers without writing or contacting anything.
- `--headless` collects without a dashboard: progress on stderr, a JSON summary on stdout. Exit status 0 means
  every goal was met, 1 an incomplete or failed reader, 2 invalid configuration, 130 interrupted.

To reopen saved recordings without scanning or downloading:

```sh
python librivox_web.py --review downloads
```

## Source texts

When a recording links to a Project Gutenberg book, the **whole book** is saved as plain text. It isn't split into
chapters or aligned with the audio. Books come from a Gutenberg mirror, never the main site, and are shared in
`<output_root>/texts/`, so move that folder along with a collection. A missing or non-Gutenberg text doesn't stop
the audio download, but makes the recording a backup. `"download_texts": false` turns texts off, along with that
requirement.

## Whole projects

The **Projects** view downloads complete books, or one reader's sections of them, into `<output_root>/projects/`,
separate from reader samples. Repeat a request to resume or retry it; it never resumes by itself.

## More

- [Mounting the dashboard in a shared console](docs/components.md)
- [Assistant guide](AI/USAGE.md)

## License

[BSD 2-Clause](LICENSE). The bundled [microweb](https://github.com/gilbertgong/microweb)
framework retains its embedded license. This software license does not cover downloaded recordings or texts.
