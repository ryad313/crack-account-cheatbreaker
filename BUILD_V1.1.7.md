# Build v1.1.7 — 2026-09-28

Build and validation notes for `cia_patcher_1.1.7.exe`. The release uses a
versioned executable asset and the repository-root `latest.json` update manifest.

## Fixed launch crash

The v1.1.6 Java patch downgraded class-file version 52 to 48 while leaving
InvokeDynamic constants in those classes. Java then exited with
`ClassFormatError: Class file version does not support constant tag 18`.

PatchGeneric now preserves class versions and unrelated methods, replacing only
the selected getter's Code attribute. Selection requires a unique getter used
by at least four boolean setters plus a further check in a string-pool user.
This identifies one class in each tested client instead of the previous broad
set of candidates. Java assets were recompiled and embedded in the executable.

Vanilla clients with the standard main class and without CheatBreaker's Start
class are skipped without rewriting the jar. Unknown clients still fail.
Client jars receive a `.ORIGINAL` backup before rewriting.

The internal patcher version is now 1.1.7, preventing the v1.1.6 executable's
self-update loop caused by its stale internal 1.1.5 version. `--version` prints
the version without modifying the installation or checking for updates.

## Validation

- The repaired installed 1.8.9 client completed loading; the user confirmed play works.
- Isolated tests on backed-up 1.7.10 and 1.8.9 clients changed exactly one class
  per jar, preserved class versions, and matched the installed working repair.
- Original jar backups matched byte-for-byte.
- A minimal vanilla-shaped jar fixture remained byte-for-byte unchanged.
- A second patch pass produced identical jar hashes.
- The packaged executable returned `cia patcher 1.1.7` for `--version`.
- Packaged Java assets matched the tested assets; no account file was packaged.

A complete clean-machine launch, the no-premium-account scenario, and a real
vanilla bootstrap remain to be tested. This build does not automatically repair
jars previously corrupted by v1.1.6; restore pristine jars first in that case.
