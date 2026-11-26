# Using this repo with an assistant

Read `AI/MEMORY.md` first. The [README](../README.md) describes the tool and how it behaves: sessions and files,
what gets collected, batch settings, source texts and whole projects. [STRATEGY.md](STRATEGY.md) explains these
instructions. This guide covers operational tasks, without requiring the development history.

## Task behavior

Treat the tasks below like makefile targets described in plain language. A request for a task includes its
necessary prerequisites: inspect what is already valid, complete missing prerequisites, then perform the task
and check its outcome. Reuse valid setup rather than repeating it. There is no task runner to install or write.

Do not invent reader choices or download targets. Ask for missing required inputs while completing independent
setup. Use a separate scratch output for checks; never overwrite or delete existing recordings or state.
Check for an existing server before launching another, and stop only the process started for the current check.

## Install dependencies / set up

Prerequisite: a local checkout and permission to run a Python interpreter.

1. Check that a working Python 3.12 or newer interpreter is available; the supported baseline is 3.12.
2. Use an existing suitable interpreter. If none exists, explain that Python must be installed and follow the
   user's environment preferences. No third-party Python dependencies, virtual environment, model weights or
   build tools are required.
3. From the repo root run `python -B librivox_web.py --help` with that interpreter.

Success: help exits successfully. Do not install unrelated audio/AI libraries.

## Check / update the vendored web runtime

The runtime is the single file `src/librivox_download/microweb.py`.

Only on explicit request: `python src/librivox_download/microweb.py --check-update` reads the upstream release
manifest without changing files. `python src/librivox_download/microweb.py --update` installs its release,
including over local edits, after checking downloaded checksum/version/syntax and preserving current bytes in
microweb.py.bak. An existing backup must be kept elsewhere or removed deliberately first; it is never overwritten.
The vendored file currently matches upstream v0.2.3 exactly. Do not patch or update it silently.
The source is [gilbertgong/microweb v0.2.3](https://github.com/gilbertgong/microweb/tree/v0.2.3),
SHA-256 `48926f7429ad3c47f2ed6140e6a6ec871ea7ab71ee8e00f59de63495095d8687`;
its BSD 2-Clause license text remains embedded in the file.
An authorized upgrade should be followed by the offline downloader tests and provenance refresh here. Startup/import never performs automatic checks or updates.

## Run smoke test / test

Prerequisite: setup above. This task is offline and does not download source recordings.

1. From the repo root run `python -B -m unittest discover -s tests -v`.
2. The tests create and clean their own temporary output, serve local HTTP fixtures on automatically allocated
   ports, and do not contact LibriVox, Gutenberg mirrors or the audio host. They need temporary-directory access and loopback sockets.
3. Report the result. If execution restrictions block temporary files or sockets, distinguish that from a test
   assertion failure and use the environment's normal approval mechanism if needed.

Success: every test passes. No existing download directory has been used as a fixture.

## Find samples / start the tool

Prerequisites: setup; a writable session directory and free loopback port. Internet access is needed only
when the user requests metadata, remote previews or downloads. Use documented selection defaults.

1. Launch `python -B librivox_web.py [SESSION.json] [--port PORT]`; see the README's Sessions and files. Without
   a filename it opens session.local.json in the launch directory: check whether that is the user's before writing
   to it. Do not overwrite invalid or existing session files. A file named on the command line starts collecting
   unless its auto_collect is false or --browse is given. Headless/dry-run require an explicit existing file.
2. On Overview, Add a reader accepts a LibriVox URL or ID and target, saves it to the session, and stays idle.
   Follow the reader link to Review. Browse / rescan finds candidates without audio/text downloads.
3. Review provides per-reader Total, Collect / resume, Scan 10 more and Pause, plus per-card Download and
   Retry 128 kbps. Pending candidates have source previews; saved files use local players. Keep / Mark bad
   records the user's judgments. Never invent listening decisions.
4. Manual controls use one sequential worker; wait for completion or pause before starting another operation.
   Reader additions and target changes persist in JSON; `_ignore` and other settings survive. External JSON
   edits require reopening the file via Change session before further UI configuration writes. An initially empty session saves
   auto_collect=false after its first addition, so future launches remain manual.
5. Leave scanning at normal limits. Do not survey a catalog or increase targets unless requested.

Success: the UI is reachable, shows the intended reader/output, and offers candidates or explains skips/errors.
A request to start the tool leaves it running for the user; a bounded test stops its own server when finished.

## Download sources / download recordings

Here, sources means the selected reader's recordings and their linked Gutenberg books, not models or a separate source-code checkout.
Prerequisites: find samples above; the user's requested count or individual selection; enough disk space and
internet access to LibriVox, the audio host and the configured Gutenberg mirror. This request includes setup
and scanning if they have not already happened.

1. For new multi-reader requests, prefer the batch task below. Use Download on a Review
   card or set Total and use Collect / resume above that reader's recordings. N is the total wanted, not additional
   samples (README, What gets collected). Replacements preserve older recordings, so the saved count can exceed N.
2. Watch transfer status. An individual 128 kbps failure automatically tries 64 without another click.
3. Check that completed records point to actual files under the output directory. A failed or missing status is
   not complete. Retry a failed download manually; inspect its error if it fails again.
4. If a 128 kbps player attempt failed temporarily, use Retry 128 kbps to select that URL again. This doesn't
   start a download. If a 64 kbps file is already saved, Download then requests the selected 128 kbps version;
   the existing 64 kbps file remains on disk.

Success: the requested individual transfers are done, or the bulk target is reached with files present. If
insufficient eligible candidates exist or a remote request fails, report the actual status rather than claiming
success. Never raise scan limits or substitute another reader without a reason grounded in the user's request.

## Batch download / collect a list of readers

Prerequisites: setup, the user's reader URLs and target count per reader, output destination, internet access
and disk space. This task includes preparing the JSON and running the existing batch tool. It requires no
browser automation, HTTP API orchestration, additional libraries or new wrapper scripts.

1. Read the README's Batch collection section and `batch.example.json`. Prepare a `*.local.json` batch file using
   the requested URLs/reader IDs and agreed defaults/overrides. Don't invent names or listening decisions.
2. Confirm the count is a total number of recordings per reader, not additional recordings or a duration target.
   Set download_texts false only for audio-only requests. A different text_mirror must serve the same layout;
   never substitute the main Gutenberg website.
3. Set `output_root` explicitly if the user chose a destination. Relative paths are relative to the JSON file.
   If operating under a role with read-only repository access, place both JSON and output outside the repo and
   invoke Python with `-B`. Respect that role's authorization boundaries for data collection.
4. Run `python -B librivox_web.py PATH_TO_BATCH --dry-run`. Review the resolved settings and output directories.
   This validates the entire configuration without writing output or contacting remote services. Check that no
   other job is using the same output directories before starting actual collection.
5. If the user wants a browsable dashboard, run `python -B librivox_web.py PATH_TO_BATCH [--port PORT]` and open
   the printed loopback URL. Collection starts automatically unless auto_collect is false or --browse is supplied. Overview shows progress and explicit collection/
   pause controls; Review shows all saved candidates and decisions. The server remains available after completion.
   If the request is for unattended command execution, use `--headless` so it exits when collection finishes.
   Only headless mode guarantees a JSON-only stdout summary; progress remains on stderr. To save that summary,
   redirect stdout to a separate report, never the input JSON or a state file. No custom wrapper is needed.
6. Inspect each reader's dashboard outcome or the headless exit status/summary, then check saved file paths. Report completed,
   insufficient and failed readers separately, including premium/degraded totals and fallback details. A failed reader does not stop subsequent readers. Time budgets
   are checked between operations, so allow an in-flight request to finish or hit its network timeout.
7. Rerun the same JSON to resume interrupted work or make another attempt at failed transfers; the README lists
   which settings may change. Missing text retries once per candidate per pass, and completed audio may gain text
   without another audio transfer. Older saved state without recorded selection settings is refused. Preserve it
   and choose new output, rather than editing away the check.

Success: all requested targets are met with files present, or a precise partial/failure report explains which
readers remain incomplete. The README gives the headless exit statuses; a dashboard's normal exit 0 only means it
closed normally, so inspect reader outcomes.
Leave the dashboard open when requested for use; otherwise stop your own test server and wait for its current
operation. Do not schedule future retries or launch downstream dataset preparation/training without instruction.

## Review existing output / mark bad

Prerequisites: setup and the user's existing output root, reader directory or state.json. No batch JSON, internet
access, migration or new index is needed. This request authorizes opening the dashboard; it doesn't authorize
making subjective listening decisions or collecting replacements unless the user requests those actions.

1. Run `python -B librivox_web.py --review OUTPUT_PATH [--port PORT]` and open the printed loopback URL. It reads
   the root state file or immediate reader subdirectories. An empty root is supported; duplicate reader IDs
   require opening the intended reader directory explicitly. Legacy saved state can be reviewed without conversion.
2. Overview shows saved readers, counts and last status. Review links preserve the reader selection. Review
   includes every saved candidate, not only completed downloads. Filter by reader/status/decision and expand
   skipped projects, recording details or full saved state when needed. Players use local files; missing files
   are labeled without rewriting the saved completion record simply because the page was opened.
3. Keep / Mark bad / Clear decision persists to the same state file and preserves recordings and other metadata.
   Mark bad excludes a file from available counts. It doesn't delete files or start new collection for a
   completed reader. The user may listen and make these decisions; don't invent approval judgments.
4. Review-only mode has no collection controls. To collect replacements, open the existing batch JSON and use
   its requested totals, or Collect / resume for a reader in an already-open collection dashboard. During an
   active reader's collection, rejected recordings don't count toward its target; a finished reader stays idle.
   Review also offers an explicit Rescan: select one reader or All readers and click it only when requested.
   It refreshes metadata from page one, retries skipped checks and preserves downloads/decisions, within the
   normal candidate target and time budget. It does not download audio or texts. Saved selection settings are
   required; legacy state without them remains reviewable, but use new configured output for scanning.
5. Close with Ctrl+C when finished, or leave it available if the user requested an ongoing review session.

Success: the saved records and local audio are browsable and requested decisions persist after reload. Opening
review mode or clearing a decision starts no scanner/downloader. No separate review database or HTML export exists.

## Rescan / refresh catalog metadata

Use the existing Review Rescan button for the selected reader, or All readers, after ensuring collection is
idle. It uses the project's API-first lookup with an HTML fallback, while reader discovery still uses the
website. Monitor reader status and Pause scan if requested. The last scan record distinguishes target reached,
actual listing exhaustion, timeout, pause and failures. Do not increase scan targets for a catalog survey.
Downloaded/reviewed recordings retain their chosen section and provenance; refreshed alternatives are available
in recording details. Unreviewed pending candidates may refresh. No media transfer occurs until a subsequent
explicit collection request. Do not delete cached audio/texts, clear listening decisions or edit saved filters
to force a rescan. Ordinary review startup remains offline.

## Live smoke check

Prerequisites: setup, a user-specified reader, internet access, fresh scratch output and a free port.

Start a scratch JSON session with default selection limits, a fresh output_root and a free `--port`. Check the UI and a
Keep/Mark bad/clear cycle. If the request includes testing downloads, request one offered sample and verify the
saved file and state; otherwise do not start media transfers. Restart with the same scratch arguments and check
that decisions and completion persist. Stop the check's own server. Retain scratch recordings unless the user
has authorized their removal. Judge tool behavior, not the particular reader's candidate distribution.

## Resume / recover missing downloads

Prerequisite: the original output directory and the same reader/selection arguments.

Stop with Ctrl+C and relaunch using that output. Saved individual requests, interrupted transfers and an
unfinished bulk target remain saved. In a manual session, explicitly resume collection or click Download again. Transfers begin again rather than resuming byte offsets. Missing completed
files appear as missing and can be downloaded again, automatically if needed by an active bulk target.
If files were deliberately moved, explain why the original output no longer counts them; do not move them
back, delete them, or reset the user's decisions without a request. No manual JSON editing is normally needed.


## Browse projects / download a whole book

Prerequisites: setup, a JSON session with writable output_root, the user's reader URL/ID or project URL, and
internet access when scanning/previewing/downloading. Check for an existing dashboard first. Launch with
--browse to avoid starting configured sample collection. Startup prints the settings-file path; creating a
missing session also prints its initial {} contents. Do not replace an existing configuration.

1. Open Projects. Scan all projects accepts a reader URL/ID without adding a sampling job. Open project accepts
   a LibriVox catalog URL. Full reader scans are explicitly requested operations, not a prerequisite for ordinary
   sample collection. They include all languages/lengths, with normal per-reader time budget, and no sample cap.
2. Include dramatic readings defaults false. Enable it only when the requested scope includes those projects.
   Repeat the reader scan or load a project's details to fetch previously excluded sections. Disabling hides
   cached projects and keeps files. Sample filtering remains unchanged.
3. Opening a project URL moves it to the top of the current page and scrolls it into view. Click a project
   name for a focused modal with players and download controls; Close or Escape returns to the list. The small
   LibriVox page link opens the external catalog. Inspect the title/edition, authors, reader credits and sections.
   Whole-project requests include everyone;
   reader-scoped requests include sections where that reader is one of the credits, including shared casts.
   Get the user's intended download scope rather than treating whole-book and sample collection as interchangeable.
4. Use Download entire project or choose a reader and Download reader's sections. Project/audio/text state lives
   under output_root/projects/catalog.json, with URL-derived project directories and the shared Gutenberg cache.
   No sample state or decisions are modified. Missing text is nonfatal; failed transfers stay visible.
5. Pause stops between operations. Repeat the same download request to reuse completed sections and retry failed
   or missing ones. Reopening never resumes project work automatically. Interrupted intent remains visible.
   Loading output_root with --review shows cached metadata/local audio only, without project write controls.
6. Report downloaded versus requested sections and any failures/fallbacks. Do not infer that a reader narrated
   an entire collaborative book, remove old recordings, or survey the global catalog. A changed catalog audio
   list keeps previously selected/downloaded sections and records the new alternative; use fresh output to
   download that revised edition rather than rewriting the existing recording's provenance.

Success: the intended project/scope is recorded, chosen sections exist locally and play through the dashboard,
or a precise partial outcome explains failed/paused sections. Source books follow configured text preferences;
there is no alignment, conversion or packaging step. Ordinary page startup does not make network requests.

## Host as a component

Follow docs/components.md. Omit session_file/review_root for the picker, or supply one absolute path
(or resolve a relative path against settings_dir). The host settings directory is the launch-directory
equivalent for the picker and its sessions/ subdirectory.
For a smoke check use a fresh scratch session and collect=false. Construction must not write files or start
workers; startup follows socket binding. Check mounted navigation, decisions and local playback, then close
the host and verify owned collection services stop. Do not use a live production library for integration tests.


## Open / create / switch sessions

The session strip identifies the active JSON file; hover for its full path. New session accepts a filename,
not an arbitrary path, and never overwrites. Open session accepts a listed file; invalid JSON must leave the
current session intact. Switching pauses old work and drains its owned worker before replacing only the
downloader controller. It stays on the same browser URL and does not restart a shared host or other tools.
The UI reports the pending session while waiting and starts the new session idle, regardless of auto_collect.
Existing state, downloads and decisions are preserved. Stale UI mutations carry a session generation and
are rejected after a switch; panels discard old audio/card caches. Review-only launches do not offer switching.
For checks use scratch sessions/output; do not switch a live user collection unless that action is requested.

## Source layout

librivox_web.py is the thin primary entry point and exposes create_component. The named application package
is under src/librivox_download/ (launch, web, dashboard, sessions, fetch, api, projects, text, dashboard.html).
The microweb runtime is vendored inside that package. The single root librivox_web.py
launches the shared CLI or exposes component factories; keep factory imports quiet and use package-relative imports internally.
No package installation is needed when running librivox_web.py from a source checkout, even from another directory.
