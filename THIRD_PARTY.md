# Third-party code

`src/librivox_download/microweb.py` is vendored from [gilbertgong/microweb](https://github.com/gilbertgong/microweb),
release [v0.1.2](https://github.com/gilbertgong/microweb/tree/v0.1.2). Its BSD 2-Clause notice is retained
inside the file. The vendored file matches that tagged release byte-for-byte.

SHA-256: `ae72f0eb51cacd5b6a4be2c3f176962be5ba321bf7bcf71537c174c3c4b93b45`.

The user adopted this release using its explicit updater. Normal import/startup never checks or updates.
There is no root microweb.py wrapper or globally installed microweb module. Use
`python -m librivox_download.microweb --check-update` for an installed package, or
`python src/librivox_download/microweb.py --check-update` from an uninstalled checkout.
The updater targets the package-owned vendored file and preserves a backup beside it; backups are not
package contents. Installed applications should normally update through pip. After adopting another release, rerun the downloader suite and refresh this provenance.
