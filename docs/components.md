# Standalone and combined consoles

The normal `librivox_web.py` dashboard uses the same mountable application and component lifecycle
as a combined console. Collection, saved state, review decisions and project downloads retain their existing
controller. Headless collection and dry runs remain independent of the web host.

## Component factory

```python
from pathlib import Path
from librivox_download.web import create_component
from librivox_download import microweb
from librivox_download.microweb import Shell

downloads = create_component({"settings_dir": Path("my-data").resolve(), "collect": False}, framework=microweb)
shell = Shell(title="Tools")
shell.add(downloads, prefix="/downloads")
shell.run("127.0.0.1", 8765)
```

Alternatively call `downloads.run("127.0.0.1", 8765)` for standalone hosting. A combined host can pass
its own compatible microweb module using framework= so Component, App, Response and HTTPError share
its classes. The example above uses the downloader's bundled module. If omitted, standalone use selects the namespaced bundled copy; older
checkout hosts that preloaded a top-level microweb module remain supported. No generic top-level
microweb module is installed. The source-only librivox_web adapter remains available. Other tools
should use their own package namespaces.

| Setting | Meaning |
|---|---|
| `session_file` | JSON session, created at startup if missing: directly under `<settings_dir>/sessions/` as New session creates one (with the folder); elsewhere as `{}`, whose parent must already exist |
| `review_root` | Existing library, reader directory or state.json to review; alternative to session_file |
| `settings_dir` | Absolute directory for relative settings paths and the session picker; defaults to launch directory when no path is supplied |
| `collect` | Startup collection; false disables it; omitted follows the session's existing auto_collect setting |

Omit both session_file/review_root for Open/New session inside the panel, or supply one to select it at startup.
Review defaults to no automatic collection and disables session switching. Factories
do not create files, initialize the controller, bind sockets or start workers. Initialization happens after
binding. A missing/invalid configuration fails startup and the host cleans up components already started.

Routes are relative to the application root. The host supplies `/downloads` once; frontend URLs are relative,
and responses qualify local media/text URLs for the mount. Standalone paths and data formats are unchanged.

On shutdown the host drains accepted requests, then the component requests pause and waits for owned
collection services to finish their current operation. Saved intent and files remain. It does not stop other
consoles, external workers or training processes. An occupied port fails before component workers start.
The compatibility `make_handler(dashboard)` remains available, delegating to these same routes.

## Adding readers from a host

The component has one method for its host, `add_readers(ids, count)`, taking LibriVox reader IDs and a goal.
It adds the ones the open session doesn't list yet with that goal, in one write, and returns. Nothing is
looked up: as with any reader entered without a name, a later scan or collection fetches the name. Listed
readers stay as they are. An invalid ID or goal, or a session file edited outside the dashboard, raises an
error and adds nothing.

It also adds while the session is collecting, scanning or downloading; the running operation keeps to the
readers it started with. Nothing is added before the component starts or when it has no session open.

## Optional discovery launcher

The repository also ships `microweb-component.json` for optional consoles that scan installed checkout folders.
Clone this repository under such a console's components/ directory and restart that launcher. Its manifest
mounts the factory as `downloads` with `collect: false` and opens the session picker by default.
The root declares component_api 1 and a components array containing one panel with order 10. A single
repository may provide several components; other tools can supply panels or shared banners in the same host.
The host supplies settings_dir outside the checkout; no dependency installation or network acquisition is
performed by discovery. Startup data creation follows binding. This does not change the normal standalone CLI.

## Sessions and source package

librivox_web.py exposes the primary factory, backed by src/librivox_download/web.py and the named application
package. The root librivox_web.py is retained as a quiet adapter for existing discovery/explicit launchers.
The namespaced microweb runtime lives in that package; direct checkout use needs no installation.

For the picker, settings_dir takes the place of a standalone launch directory. Existing JSON files there
and in its sessions/ subdirectory are listed. New named sessions are created only under sessions/, with
output_root=../downloads and auto_collect=false. A host's missing session_file directly under sessions/ is
created the same way at startup; other explicit paths keep their existing semantics.
The directory must exist when opening an existing configuration; creation of sessions/ follows a user action or
such a host setting.

POST api/session_open selects a listed path; api/session_new creates a basename (adding .json if omitted).
Both validate before pausing the current controller, then asynchronously stop/join owned workers and replace
only this component's controller. api/dashboard exposes session.active/name/files/directory, switching/pending,
error and generation. UI mutations include session_generation so late requests cannot mutate a new session.
The new controller starts idle. Recordings, saved state and decisions remain in their existing output roots.
The host, other components and the browser URL stay running; component shutdown also joins a pending switch.

## Read-only library interface, revision 1

This documents the subset another tool can consume without owning downloader internals. Revision 1 is a
documentation contract, not a new field added to state.json. Additive fields are allowed; consumers ignore
unused fields. Breaking changes require an explicit interface revision and compatibility/migration notes.

- A download root contains `<reader id>/state.json`. Names may change; the configured library root and reader
  ID identify the source. Multiple libraries may contain the same reader ID.
- State exposes `reader_id`, display name `reader`, `status`, and `candidates[]`.
- A candidate exposes project `url`, `title`, `type`, `section.title`, `section.seconds`, `decision`, optional
  `source.gutenberg_id`, and `download` with `status`, `file`, `quality`.
- `download.status == "done"` records completion. Also verify the recording exists. `download.file` is relative
  to the reader directory; normalize legacy backslashes and require the resolved file to remain inside it.
- `decision == "reject"` marks a bad recording without deleting it. Consumers selecting usable recordings
  should exclude it. `keep` means positively reviewed; null/missing means unreviewed.
- Optional whole-book text is at `<root>/texts/gutenberg/<id>/source.txt`. A Gutenberg ID alone does not prove
  text was downloaded. Check availability; text may be missing or explicitly disabled.
- Quality `"128"` identifies the recorded bitrate choice. Premium classification also uses selection preferences
  and configured text requirements; neither bitrate nor source ID alone establishes it.

Read these files; do not modify downloader state, decisions, text caches or recordings from another tool.
Write derived projects into that tool's own data directory. Source books are not aligned sentence datasets.
Project-mode whole-book downloads use a separate catalog, outside this initial reader-library contract.

The synthetic workbench demonstration reads completed, present, non-rejected recordings and their
reader/title/quality metadata. It does not implement voice preparation or alignment.

## Installed use

Install librivox-download into the host environment, then import librivox_download.web directly.
No checkout path or sys.path edit is needed. Factories remain quiet; caller-owned settings directories
hold sessions, recordings and decisions. The package dashboard HTML and vendored runtime ship in the
wheel. Installing does not create user data or start a service.
