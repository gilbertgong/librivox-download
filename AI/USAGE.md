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
3. From the repo root run `python -B librivox_fetch.py --help` with that interpreter.

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
4. Explain Keep/Reject and the prime/backup split if needed. Keep marks approval; bulk downloading requires only
   that a candidate has not been rejected. Do not make listening decisions for the user.

Success: the UI is reachable, shows the intended reader/output, and offers candidates or explains skips/errors.
A request to start the tool leaves it running for the user; a bounded test stops its own server when finished.

## Download sources / download recordings

Here, sources means the selected reader's recordings, not models or a separate source-code checkout.
Prerequisites: find samples above; the user's requested count or individual selection; enough disk space and
internet access to the audio host. This request includes setup and scanning if they have not already happened.

1. Use Download on a particular card or set N and use Download N in the running UI. Download N means N total
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
   the requested URLs and agreed defaults/overrides. Names are optional; the tool uses reader IDs for directory
   identity and an ID-based display label when a name is absent. Do not invent names or listening decisions.
2. Confirm the count is a total number of recordings per reader, not additional recordings or a duration target.
   The tool takes one section per project. State the existing 64 kbps fallback policy if it matters to the request;
   strict 128-only collection and automatic transcript collection are not supported by this batch schema.
3. Set `output_root` explicitly if the user chose a destination. Relative paths are relative to the JSON file.
   If operating under a role with read-only repository access, place both JSON and output outside the repo and
   invoke Python with `-B`. Respect that role's authorization boundaries for data collection.
4. Run `python -B librivox_batch.py PATH_TO_BATCH --dry-run`. Review the resolved settings and output directories.
   This validates the entire configuration without writing output or contacting remote services. Check that no
   other job is using the same output directories before starting actual collection.
5. Run `python -B librivox_batch.py PATH_TO_BATCH`. To save its JSON summary, redirect stdout to a separate report
   path; progress remains on stderr. Never redirect onto the batch input or a per-reader state file. Readers run
   sequentially and the command exits when all readers are handled. It needs no detached server or UI.
6. Inspect the exit status and each result, then check completed state paths against disk. Report completed,
   insufficient and failed readers separately. A failed reader does not stop subsequent readers. Time budgets
   are checked between operations, so allow an in-flight request to finish or hit its network timeout.
7. Rerun the same JSON to resume interrupted work or make another attempt at failed transfers. Changing count or
   timeout is allowed; changing selection filters requires a new output root. Older saved state without recorded
   selection settings is also refused. Preserve it and choose new output, rather than editing away the check.

Success: all requested targets are met with files present, or a precise partial/failure report explains which
readers remain incomplete. Exit 0 means all complete; 1 means incomplete/failed, 2 configuration error and 130
user interruption. Ctrl+C produces a partial summary and marks remaining readers not_run. Stop after that
request; do not schedule future retries or launch downstream dataset preparation/training without instruction.

## Live smoke check

Prerequisites: setup, a user-specified reader, internet access, fresh scratch output and a free port.

Start the normal tool with default selection limits and the scratch `--out`/`--port`. Check the UI and a
Keep/Reject/clear cycle. If the request includes testing downloads, request one offered sample and verify the
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
