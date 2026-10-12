# librivox-download

Find a LibriVox reader's solo recordings, one sample per project, vet them by ear on a local web page, and download
the ones you keep as 128 kbps MP3s.

Python 3.12, standard library only.

## Usage

```
python librivox_fetch.py "Beth Thomas" https://librivox.org/reader/6281/
```

Then open http://127.0.0.1:8765/. Stop the server with Ctrl+C; running it again resumes where it left off.

## How it works

- The reader's project listing is scanned in the background. A project is a candidate if one of its sections is
  read by this reader alone and is at least a minute long. Dramatic readings, other languages, and projects that
  don't list readers per section are skipped.
- Each candidate offers one section: the first 5–15 minutes long, or the closest to that range.
- Files are 128 kbps. Candidates with only 64 kbps (no 128 kbps file, or it failed to play or download) are kept
  as backups, in their own section, and don't count toward the target.
- Scanning stops at 20 candidates with 128 kbps that you haven't rejected. Rejecting one makes it look further;
  "Scan 10 more" raises the target.
- The page shows progress, a card per candidate (player, section, length, Keep, Reject, Download), the backups,
  and the skipped projects with reasons. Keep marks a sample you've listened to and approved.
- "Download N" (default 10) has the server download the first N candidates you haven't rejected, 128 kbps first;
  backups only if the reader's listing runs out of 128 kbps candidates.

## Options

| Option | Default | |
|---|---|---|
| `--projects` | 20 | candidates to find |
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
  chosen section, your keep / reject decisions, and each download, with the time of each change.
