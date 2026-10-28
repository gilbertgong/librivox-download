"""Compatibility entry point for the original single-reader command."""
import console  # source-checkout bootstrap
from librivox_download.fetch import main

if __name__ == "__main__":
    main()
