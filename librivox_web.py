"""Compatibility component adapter for existing shared-console launchers."""
import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parent / "src")
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)
from librivox_download.web import create_app, create_component, dashboard_component
