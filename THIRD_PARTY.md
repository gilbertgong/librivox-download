# Third-party code

`microweb.py` is vendored from [gilbertgong/microweb](https://github.com/gilbertgong/microweb), a standard-library
HTTP framework and optional local console shell. Its BSD 2-Clause notice is retained inside the file.

This is the development snapshot used for component integration on 2026-10-25, not a tagged release.
It includes Component, Shell.add, request draining and shared standalone/combined lifecycle support.
No pip dependency or automatic update is introduced. Update upstream first, copy its exact file and rerun
the downloader suite before adopting another snapshot. The embedded development version has no release
update URL; it is not an automatically updatable published release.

Snapshot SHA-256: `da6a21000995e4656d0fa4eb80ebf50e5a0bb6528e68224abb43039833317f15`.
