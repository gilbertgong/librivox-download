"""Source-checkout compatibility entry point for the namespaced vendored framework."""
import sys
from pathlib import Path

_source = str(Path(__file__).resolve().parent / "src")
if _source not in sys.path:
    sys.path.insert(0, _source)
from librivox_download.microweb import *  # noqa: F401,F403,E402
from librivox_download.microweb import _Server, __version__  # compatibility for existing hosts/tests

if __name__ == "__main__":
    from librivox_download.microweb import main
    main()
