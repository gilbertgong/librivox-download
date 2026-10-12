# librivox-download: project log

## Goal

Gather voice samples of one LibriVox reader for voice work (first: Beth Thomas, reader 6281, for
`../kokoro-evovoice`). Given a reader's name and LibriVox page, find recordings where that reader is the only voice,
let the user vet them by ear, and download the ones kept, as 128 kbps MP3s.

**What a good set looks like:** one sample from each of many projects, not hours from one book. Different projects
mean different recording sessions, mics and years, which is the variety voice work needs. It also matches
kokoro-evovoice's practice of separating training and held-out audio by book.

## Design decisions

- **LibriVox is the only thing scanned.** All decisions come from LibriVox's pages. archive.org (where LibriVox
  hosts the audio) is contacted only to stream or download the chosen file, never to look up metadata.
- **Solo means per section.** A section counts if its reader list is exactly this reader. Collaborative projects
  where the reader read one chapter are fine; the whole project needn't be solo.
- **Dramatic readings are skipped.** They're cast performances: each section lists several readers, and the rare
  solo sections are short narration.
- **Projects whose pages don't list readers per section are skipped.** No way to tell who's speaking.
- **One section per project:** the first one 5-15 minutes long (user's rule). If none is, the one closest to that
  range, flagged on the page: the AI assistant's choice, not yet confirmed (see open questions). Never under a minute.
- **128 kbps, judged by file name** (`*_128kb.mp3`), derived from the 64 kbps play link when the chapter link isn't
  one. 64 kbps is suboptimal: used only when the 128 kbps file is missing (no such name, the player can't load it,
  or its download fails).
- **64 kbps candidates are backups.** Tracked and shown in a separate "Backups" section, but not counted toward the
  goal. Some readers may not have enough 128 kbps recordings, which is why they're kept at all. "Download N" takes a
  backup only once the listing is exhausted and no 128 kbps candidate is left.
- **Scanning is incremental.** The listing is read a page at a time and each project checked as its page comes in;
  scanning pauses once there are enough candidates: 20 with 128 kbps, not rejected, or N if "Download N" asks for
  more. A reject, a failed 128 kbps download, "Scan 10 more" or a larger N resumes it. The 2x over-collection (20
  candidates for 10 downloads) allows for downloads that fail and samples the user rejects.
- **A local web page for vetting.** The user validates by ear: progress, candidates with players, Reject, Download.
  Downloads are done by the server, in the background, into the project's output folder, never as browser downloads.
  "Download N" takes candidates not rejected (the user doesn't have to approve each one).
- **Keep / Reject.** Keep records that the user listened and approved; it doesn't change what "Download N" takes
  (anything not rejected). Rejecting a downloaded sample doesn't delete its file.
- **`state.json` is the single record.** What's been checked (with skip reasons), each candidate, decisions, and
  downloads, with timestamps (`found_at`, `decided_at`, `download.at`, `missing_128.at`, top-level `updated_at`).
  Rewritten on every change, so a restart doesn't re-read project pages and rejected projects don't come back.
  There are no per-folder manifests: they duplicated it and went stale when a decision changed after download. If
  self-describing folders are needed (e.g. exporting to kokoro-evovoice), generate them from `state.json` then.
- **Standard library only**, so it runs anywhere with Python 3.12.

## How LibriVox pages work (as of 2026-10)

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

## Log

### 2026-10-11/12: first version

- **Script, then a page.** Started as a command-line script that found and downloaded whole solo projects. Reworked
  in steps after feedback:
  1. Per-section solo instead of whole projects; collaborative projects allowed.
  2. Dramatic readings briefly included, then dropped again once it was clear what they are.
  3. Removed the archive.org metadata lookups (had been used to confirm 128 kbps files existed).
  4. Incremental scanning with a stop condition, instead of reading the whole listing first.
  5. A local server and page for vetting, with one sample per project.
- **Beth Thomas, for reference:** 331 projects listed: 175 dramatic, 137 collaborative (13 of them multilingual),
  16 poetry, and only 3 solo (Philippians, War Letters From A Young Queenslander, The Wishing Horse of Oz).
  A dry run of the command-line version found solo sections in at least 4 collaborative projects in the first
  listing pages (The Art of Kissing, Astounding Stories 15 and 16, Balloons).
- **Moved** out of `kokoro-evovoice/tools/` into this project. AI-facing docs live in `AI/` (loaded by
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

- **Output moved to `downloads/`** (user-created, git-ignored): the default `--out` is now `downloads/<name>` next
  to the script, whatever the working directory. The first run's `state.json` was moved from `librivox/beth_thomas/`
  to `downloads/beth_thomas/` and the old `librivox/` folder removed.

## Code map (librivox_fetch.py)

- **LibriVox pages:** `listing_pages` (the AJAX listing, a page at a time), `read_project` (a project's section
  table), `file_urls` (128/64 kbps URLs by name), `pick_section`, `check` (candidate or skip reason).
- **State:** class `State`, one lock, saved to `state.json` on every change. `goal()` is the number of 128 kbps
  candidates the scan aims for; `scan_done` is set once the listing is exhausted or the scan stopped.
- **Threads:** `scanner` (pauses at the goal, woken by an Event), `downloader` (picks via `next_download`).
- **Web:** `PAGE` (HTML + JS, polls `/api/state` every 1.5 s; cards are built once and updated in place so players
  aren't interrupted), `make_handler` (GET `/`, `/api/state`; POST `decide` (keep / reject / null), `download`,
  `download_n`, `scan_more`, `missing_128`).

## Status

The server/page version has been run once (2026-10-11), before the Keep button and timestamps were added. The scan
ran and paused at the 20-candidate goal; nothing was kept, rejected or downloaded. Its `state.json` loads in the
current version. Not yet tried: Keep / Reject, downloads, and resuming with the current code.

## Open questions

- **Where the samples go.** Nothing decides where downloads should end up for kokoro-evovoice, or what role they play
  there. Its config (`../kokoro-evovoice/voices/beth_thomas.toml`) points at `G:\Dev\claude\reference\beth_thomas_full\`
  (64 kbps chapters, used now as train/held-out by book). Whether new samples go there, and whether they're
  training or held-out audio, is the user's call.
- **No section in 5-15 minutes.** The script offers the closest one, flagged "outside length range". Alternatives:
  skip the project, or show it as a backup.

## Known issues

- **Any player error downgrades to 64 kbps.** The page reports "128 kbps missing" when the player fails for any
  reason, including a dropped connection, and the candidate moves to Backups. The page has no way to undo it (edit
  `state.json`, or delete `missing_128` and set `quality` back to "128", while the server is stopped).
- **HTML parsing by regular expressions.** `listing_pages` and `read_project` depend on LibriVox's current markup
  (described above). If LibriVox changes its pages, look there first.

## Next steps

- Run the current version against Beth Thomas: check the page, Keep / Reject, and a download.
