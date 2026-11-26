"""Run the installed LibriVox dashboard or headless batch CLI."""
import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
