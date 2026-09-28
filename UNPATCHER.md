# Unpatcher v1.1.7

Standalone companion to the v1.1.7 release. `latest.json` continues to select
the patcher; the unpatcher is a separate, manually downloaded executable.

## Build and checks

```
py -3.11 -m unittest discover -s tests -v
py -3.11 -m PyInstaller --onefile --icon NONE --name cia_unpatcher_1.1.7 cia_unpatcher.py
dist\cia_unpatcher_1.1.7.exe --version
dist\cia_unpatcher_1.1.7.exe --dry-run
```

Only standard-library modules are required. Do not include user backups,
client jars, launcher archives or credentials as package data.

The tool checks the launcher backup and native-file integrity before applying
any changes. It hashes and snapshots every affected file first. Replacements
are staged beside the target and applied with retry; an error triggers rollback
and reports the backup location. The automatic build closes the installed
CheatBreaker launcher and Java processes belonging to its game, escalating to
forced shutdown if needed. It leaves unrelated Java applications running.
No keyboard input is required, including on errors. Diagnostics are saved to
`%LOCALAPPDATA%\cia_unpatcher\cia_unpatcher.log`.

Client backups containing the old class-version-48 corruption are rejected.
Clients without a usable backup are set aside for official re-download.
`.ORIGINAL` backups are retained. Offline account removal requires both the
patcher's exact local ID format and token sentinel; other accounts and unknown
metadata are preserved.

Tests cover restoration, account preservation and selection, repeated runs,
missing launcher backups, invalid client backups, native-file validation and
rollback after a simulated write failure. The packaged executable is also
checked with `--version` and `--dry-run` against the local installation. No
destructive test is performed on the active installation.
