# Using this repo with an assistant

Read `AI/MEMORY.md` first. The [README](../README.md) describes the tool; [STRATEGY.md](STRATEGY.md) explains
these instructions. This guide covers operational use without requiring the development history.

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
3. From the repo root run `python -B librivox_batch.py --help` with that interpreter.

Success: help exits successfully. Do not install unrelated audio/AI libraries.

## Run smoke test / test

Prerequisite: setup above. This task is offline and does not download source recordings.

1. From the repo root run `python -B -m unittest discover -s tests -v`.
2. The tests create and clean their own temporary output, serve local HTTP fixtures on automatically allocated
   ports, and do not contact LibriVox or the audio host. They need temporary-directory access and loopback sockets.
3. Report the result. If execution restrictions block temporary files or sockets, distinguish that from a test
   assertion failure and use the environment's normal approval mechanism if needed.

Success: every test passes. No existing download directory has been used as a fixture.

## Find samples / start the tool

Prerequisites: setup; internet access; reader name and LibriVox reader URL; desired output directory and free port.
Use the documented defaults unless the user asks otherwise. Reuse existing state only for that reader and the
same selection options; a fresh output directory is appropriate for a new selection.

1. Run `python librivox_fetch.py "READER NAME" https://librivox.org/reader/READER_ID/` from the repo root.
   Add `--out OUTPUT_DIRECTORY` or `--port PORT` as needed. Default output is `downloads/<name>` next to the script.
2. Open the printed loopback URL. Check the reader/output and that status progresses from scanning to paused or
   listing exhausted. A stopped/error status is a failure to investigate, not successful exhaustion.
3. Leave scanning at its normal limits; do not run side queries to survey the reader's entire catalog.
4. Use Overview for collection controls and Review for candidates. Explain Keep/Mark bad and the prime/backup
   split if needed. Keep marks approval; bulk downloading requires only
   that a candidate has not been rejected. Do not make listening decisions for the user.

Success: the UI is reachable, shows the intended reader/output, and offers candidates or explains skips/errors.
A request to start the tool leaves it running for the user; a bounded test stops its own server when finished.

## Download sources / download recordings

Here, sources means the selected reader's recordings, not models or a separate source-code checkout.
Prerequisites: find samples above; the user's requested count or individual selection; enough disk space and
internet access to the audio host. This request includes setup and scanning if they have not already happened.

1. For new multi-reader requests, prefer the batch task below. In single-reader mode, use Download on a Review
   card or set N and use Collect / resume on Overview. The collection target means N total
   non-rejected completed samples in this output, including earlier downloads; it is not N additional samples.
2. Watch transfer status. An individual 128 kbps failure automatically tries 64 without another click. Bulk
   downloading favors primes and waits until scanning finishes before using backups.
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

1. Read the README's Batch downloads section and `batch.example.json`. Prepare a `*.local.json` batch file using
   the requested URLs/reader IDs and agreed defaults/overrides. Prefer URL strings or positive integer IDs for
   readers sharing defaults; use an object with url or reader_id for overrides, including an optional explicit
   name. Digit-string IDs are accepted too. All forms can mix; matching IDs/URLs resolve to one directory identity.
   The tool fetches a
   missing name once at collection time and caches it in state, reusing saved names on subsequent runs. Name
   lookup failures fall back to Reader ID without blocking collection and retry on a later invocation. Dry runs
   remain offline with placeholder labels. Reader IDs identify directories. Don't invent names or listening decisions.
2. Confirm the count is a total number of recordings per reader, not additional recordings or a duration target.
   The tool takes one section per project. State the existing 64 kbps fallback policy if it matters to the request;
   strict 128-only collection and automatic transcript collection are not supported by this batch schema.
3. Set `output_root` explicitly if the user chose a destination. Relative paths are relative to the JSON file.
   If operating under a role with read-only repository access, place both JSON and output outside the repo and
   invoke Python with `-B`. Respect that role's authorization boundaries for data collection.
4. Run `python -B librivox_batch.py PATH_TO_BATCH --dry-run`. Review the resolved settings and output directories.
   This validates the entire configuration without writing output or contacting remote services. Check that no
   other job is using the same output directories before starting actual collection.
5. If the user wants a browsable dashboard, run `python -B librivox_batch.py PATH_TO_BATCH [--port PORT]` and open
   the printed loopback URL. Collection starts automatically. Overview shows progress and explicit collection/
   pause controls; Review shows all saved candidates and decisions. The server remains available after completion.
   If the request is for unattended command execution, use `--headless` so it exits when collection finishes.
   Only headless mode guarantees a JSON-only stdout summary; progress remains on stderr. To save that summary,
   redirect stdout to a separate report, never the input JSON or a state file. No custom wrapper is needed.
6. Inspect each reader's dashboard outcome or the headless exit status/summary, then check saved file paths. Report completed,
   insufficient and failed readers separately. A failed reader does not stop subsequent readers. Time budgets
   are checked between operations, so allow an in-flight request to finish or hit its network timeout.
7. Rerun the same JSON to resume interrupted work or make another attempt at failed transfers. Changing count or
   timeout is allowed; changing selection filters requires a new output root. Older saved state without recorded
   selection settings is also refused. Preserve it and choose new output, rather than editing away the check.

Success: all requested targets are met with files present, or a precise partial/failure report explains which
readers remain incomplete. Headless exit 0 means all complete; 1 means incomplete/failed, 2 configuration error
and 130 interruption. A dashboard's normal exit0 only means it closed normally; inspect reader outcomes.
Leave the dashboard open when requested for use; otherwise stop your own test server and wait for its current
operation. Do not schedule future retries or launch downstream dataset preparation/training without instruction.

## Review existing output / mark bad

Prerequisites: setup and the user's existing output root, reader directory or state.json. No batch JSON, internet
access, migration or new index is needed. This request authorizes opening the dashboard; it doesn't authorize
making subjective listening decisions or collecting replacements unless the user requests those actions.

1. Run `python -B librivox_batch.py --review OUTPUT_PATH [--port PORT]` and open the printed loopback URL. It reads
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
5. Close with Ctrl+C when finished, or leave it available if the user requested an ongoing review session.

Success: the saved records and local audio are browsable and requested decisions persist after reload. Opening
review mode or clearing a decision starts no scanner/downloader. No separate review database or HTML export exists.

## Live smoke check

Prerequisites: setup, a user-specified reader, internet access, fresh scratch output and a free port.

Start the normal tool with default selection limits and the scratch `--out`/`--port`. Check the UI and a
Keep/Mark bad/clear cycle. If the request includes testing downloads, request one offered sample and verify the
saved file and state; otherwise do not start media transfers. Restart with the same scratch arguments and check
that decisions and completion persist. Stop the check's own server. Retain scratch recordings unless the user
has authorized their removal. Judge tool behavior, not the particular reader's candidate distribution.

## Resume / recover missing downloads

Prerequisite: the original output directory and the same reader/selection arguments.

Stop with Ctrl+C and relaunch using that output. Saved individual requests, interrupted transfers and an
unfinished bulk target resume. Transfers begin again rather than resuming byte offsets. Missing completed
files appear as missing and can be downloaded again, automatically if needed by an active bulk target.
If files were deliberately moved, explain why the original output no longer counts them; do not move them
back, delete them, or reset the user's decisions without a request. No manual JSON editing is normally needed.
