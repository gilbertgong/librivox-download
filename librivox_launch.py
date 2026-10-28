"""Compatibility entry point. New users can run python console.py."""
import sys
import console  # source-checkout bootstrap
from librivox_download.launch import main

if __name__ == "__main__":
    sys.exit(main())
