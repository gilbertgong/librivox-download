# Standalone and combined consoles

The normal `librivox_launch.py` dashboard uses the same mountable application and component lifecycle
as a combined console. Collection, saved state, review decisions and project downloads retain their existing
controller. Headless collection and dry runs remain independent of the web host.

## Component factory

```python
from pathlib import Path
from librivox_web import create_component
from microweb import Shell

downloads = create_component({"session_file": Path("my-session.json").resolve(), "collect": False})
shell = Shell(title="Tools")
shell.add(downloads, prefix="/downloads")
shell.run("127.0.0.1", 8765)
```

Alternatively call `downloads.run("127.0.0.1", 8765)` for standalone hosting. A host importing several
tools imports a common compatible microweb runtime first. The bundled copy supports independent use,
without installation. Other tools should use their own package namespaces.

| Setting | Meaning |
|---|---|
| `session_file` | JSON session, created as `{}` at startup if missing; its parent must already exist |
| `review_root` | Existing library, reader directory or state.json to review; alternative to session_file |
| `settings_dir` | Absolute directory for resolving a relative session_file/review_root |
| `collect` | Startup collection; false disables it; omitted follows the session's existing auto_collect setting |

Supply exactly one of session_file or review_root. Review defaults to no automatic collection. Factories
do not create files, initialize the controller, bind sockets or start workers. Initialization happens after
binding. A missing/invalid configuration fails startup and the host cleans up components already started.

Routes are relative to the application root. The host supplies `/downloads` once; frontend URLs are relative,
and responses qualify local media/text URLs for the mount. Standalone paths and data formats are unchanged.

On shutdown the host drains accepted requests, then the component requests pause and waits for owned
collection services to finish their current operation. Saved intent and files remain. It does not stop other
consoles, external workers or training processes. An occupied port fails before component workers start.
The compatibility `make_handler(dashboard)` remains available, delegating to these same routes.

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
