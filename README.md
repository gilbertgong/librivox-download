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
recordings to keep or avoid. The dashboard opens `session.local.json` in the current folder, creating it the first
time, and can switch to other sessions. Sessions and review decisions are saved locally.

## Batch collection

Copy [batch.example.json](batch.example.json) and edit its readers and settings, then run:

```sh
python librivox_web.py batch.local.json
```

Add `--dry-run` to inspect the configuration, or `--headless` to collect without a dashboard.
Reopen downloaded recordings with `python librivox_web.py --review downloads`.

See the [usage guide](docs/usage.md) for session controls, batch settings, source texts and resuming downloads.
The dashboard can also be [mounted in a shared console](docs/components.md).
For assistant-guided use, start with [AI/USAGE.md](AI/USAGE.md).

## License

[BSD 2-Clause](LICENSE). The bundled [microweb](https://github.com/gilbertgong/microweb)
framework retains its embedded license. This software license does not cover downloaded recordings or texts.
