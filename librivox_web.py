"""Run the LibriVox dashboard or expose its factories to a shared console."""
import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parent / "src")
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)

from librivox_download.web import create_app, create_component, dashboard_component


def main():
    from librivox_download.launch import main as launch
    return launch()


if __name__ == "__main__":
    sys.exit(main())
