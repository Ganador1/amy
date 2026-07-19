# Filesystem Capability Probes

These R0 records establish structural compatibility for path-safety operators;
they are not performance measurements or scientific results.

The same standard-library probe tested regular files, symbolic links plus
non-following open, hard links, FIFOs, directory-relative open, and
`O_NOFOLLOW`.

## Retained environments

- `ENV-AUTHOR`: macOS/Darwin 25.5.0, arm64, Python 3.12.12.
- `ENV-LINUX-PINNED`: Linux/amd64, Python 3.12.12, image manifest
  `sha256:c8367d14e6e5f9311689792032852506d7188f487c6db2967c386a26ebeecff1`.

The Linux probe ran as UID/GID 65534, with a read-only container filesystem,
all Linux capabilities dropped, `no-new-privileges`, a bounded `/tmp` tmpfs,
the study mounted read-only, and `--network none`. Docker was version 29.6.1.

Both environments passed every required primitive. `O_NOFOLLOW` rejected a
symlink with `ELOOP` (`errno` numbers differ by operating system, as expected).

`protocol/PREREQUISITE_REGISTRY_DRAFT.json` binds the probe script and both
records by SHA-256. `scripts/validate_protocol.py` independently checks those
hashes, planned-environment coverage, image identity, no-network declaration,
and every required capability before accepting the three filesystem
prerequisites as true.

Probe source SHA-256:
`79b84619e5d896fa49208d22a2b69ba246f010c790761e06c561ea3d22e38895`.

The records establish capabilities of these observed environments. The final R0
still has to freeze the complete author environment identity and rerun the probe
if any relevant image, runtime, filesystem, or source bytes change.
