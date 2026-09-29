# crack-account-cheatbreaker

![preview](preview.png)

Offline-account patcher for the CheatBreaker launcher (Windows, v2026.9.1).

Adds username-only accounts so you can play on servers that accept offline sessions. Premium accounts are left untouched and the server-side online-mode filter still decides who can join.

## Download

Grab `cia_patcher_1.1.8.exe` from [Releases](https://github.com/ryad313/crack-account-cheatbreaker/releases/latest). Copy the EXE alone; the Java patching tools are embedded.

On startup the patcher checks `latest.json` in this repository and updates itself automatically when a newer build is published.

## Usage

1. Run `cia_patcher_1.1.8.exe`
2. Type a nickname (3-16 letters/digits/underscore, must not be an existing premium name) - or `r` for a random one
3. CheatBreaker starts automatically, the account is already selected

## What it patches

Launcher (Electron, `app.asar`):

- Offline login (UUID v3 `OfflinePlayer:<name>`, no Microsoft account involved)
- Offline launch using verified, prepared CheatBreaker clients
- Offline accounts filtered out of the packets sent to CheatBreaker's backend
- UI gates unlocked so the launch button works without backend authentication
- Genuine CheatBreaker 1.7.10 and 1.8.9 packages downloaded and patched before launch
- Client receipts checked before offline launch; missing or changed clients require rerunning the patcher

Game client (Java, 1.7.10 and 1.8.9):

- Title screen unlocked: SINGLEPLAYER / MULTIPLAYER usable with an offline account

## Requirements

- Windows x64 with CheatBreaker 2026.9.1 installed
- Internet access for the initial runtime, client, library and asset downloads
- No prior game launch or separate Java installation required; Java 25 is downloaded when needed

## Restore the official launcher

Download `cia_unpatcher_1.1.7.exe` from the same release and run it. The automatic
build closes CheatBreaker and its game processes, restores the files, then exits
without keyboard input. Other Java applications are left running. The EXE is standalone and does not contain any user
accounts or game files.

It restores available `.ORIGINAL` backups, validates the native files, removes
only offline accounts identified as created by this patcher, and preserves all
other account entries. It saves the previous state under
`%APPDATA%\CheatBreaker\unpatch-backups`; keep those backups private because
they can contain account credentials. Original backups are retained.

When no usable client-jar backup exists, the client jar and its version metadata
are backed up and removed from the download cache so the official launcher can
download them again. Worlds, servers and gameplay settings are left untouched.
If the patched launcher's `app.asar.ORIGINAL` is missing or invalid, the tool
stops before changing files and asks you to reinstall official CheatBreaker.

Use `cia_unpatcher_1.1.7.exe --dry-run` to inspect the restoration plan without
changing anything, or `--version` to check the build.
The automatic build reports `cia unpatcher 1.1.7 (automatic)`. Its log is saved
to `%LOCALAPPDATA%\cia_unpatcher\cia_unpatcher.log`.

## Notes

- v1.1.8 replaces the old vanilla fallback with genuine CheatBreaker clients, verifies downloads, and repairs the supported clients from pinned originals. Previous client files are saved under `%APPDATA%\CheatBreaker\patch-backups`.
- 1.8.9 launch and connection to an offline-mode server reached the registration screen on a second Windows machine. A complete 1.7.10 launch on that machine remains unverified. See [build and validation notes](BUILD_V1.1.8.md).
- **[how_to_update.md](how_to_update.md)** — full engineering bible: architecture, patch inventory, rules, traps catalog, and step-by-step procedures to patch a new CheatBreaker version or ship a new patcher release.
- Premium Minecraft servers will still reject offline sessions; only servers running `online-mode=false` accept them.
- Modifying the launcher may violate CheatBreaker's terms of service, and playing multiplayer without owning the game violates the Minecraft EULA.
- Not affiliated with CheatBreaker LLC or Mojang Studios. Use at your own risk.
