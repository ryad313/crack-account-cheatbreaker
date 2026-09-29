# Build v1.1.8 — 2026-09-29

## Changes

The old offline bootstrap downloaded vanilla Minecraft when no CheatBreaker client
was cached. Vanilla metadata also exposed unresolved launch placeholders, including
`${user_properties}`, causing a Gson startup exception.

The patcher now downloads the genuine CheatBreaker 1.7.10 and 1.8.9 packages from
the official CDN, verifies pinned SHA256 hashes, confirms `Start.class` and
`mainClass=Start`, then applies the Java patch before enabling offline launch.
Java 25 is provisioned when no suitable CheatBreaker runtime exists. Configured
download directories are respected. No prior game launch is required.

Both clients are prepared in staging. Existing clients, original backups and
receipts are saved before installation, with rollback if replacement fails.
Genuine originals are retained for unpatching. Receipts verify the installed jar
and metadata on subsequent offline launches. Missing or changed clients stop
with a repair message instead of silently launching vanilla. Earlier renderer
patches migrate to this flow. Legacy placeholders also receive valid values.

Process shutdown uses the automatic unpatcher's targeted selection, preserving
unrelated Java processes. The included `cia_unpatcher_1.1.7.exe` is the unchanged
automatic build; its original versioned filename is retained.

## Validation

- 13 automated launch-argument and unpatcher tests passed.
- Isolated preparation started with empty client and runtime directories,
  downloaded Java 25 and both genuine packages, and patched one class per client.
- Renderer migration from pristine and v1.1.7 bundles produced identical output;
  a repeat patch was unchanged and Node syntax validation passed.
- The original Gson exception was reproduced with unresolved vanilla arguments;
  argument resolution removed it. Vanilla startup is not the product acceptance test.
- On a second Windows machine, v1.1.8 prepared both clients, launched CheatBreaker
  1.8.9 and connected to an offline-mode server's registration screen.
- Complete 1.7.10 gameplay on the second machine remains unverified. The second
  machine test did not explicitly clear every existing cache or Java installation.
- Packaged Python code and embedded Java assets match the published sources.
  `--version` returns `cia patcher 1.1.8`.

## Executables

- `cia_patcher_1.1.8.exe` SHA256:
  `43edab1f5da156bf5f486736165faa8a5a643e671cbda79dc296ea3df67651bc`
- `cia_unpatcher_1.1.7.exe` SHA256:
  `e9e87953630139fd9639e65d89ec384fe17c44c8f98f795470b3507b974d32c8`

The release reuses the tested patcher executable without rebuilding it.
`latest.json` is updated only after the downloadable asset is verified.
