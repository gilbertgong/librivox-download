"""Run the standalone LibriVox console or expose its component to a shared host."""
import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parent / "src")
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)

from librivox_download.web import create_component


def main():
    from librivox_download.launch import main as launch
    return launch(choose_session=True)


if __name__ == "__main__":
    sys.exit(main())
