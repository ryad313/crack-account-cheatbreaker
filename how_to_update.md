# how_to_update.md — cia patcher engineering bible

This document is the single source of context for the `cia patcher` project. It is written
for a human engineer or an AI agent taking over the project: it explains what the system is,
how it was reverse engineered, which rules must never be broken, every trap hit so far, and
the exact procedures to produce a patch for a new CheatBreaker version and ship it.

Read it fully once before touching anything.

---

## 0. What you are working on

`cia patcher` is a CLI that turns a stock CheatBreaker launcher (Windows, Electron) into a
launcher that supports username-only (offline) Minecraft accounts:

- offline login (UUID v3 over `OfflinePlayer:<name>`, no Microsoft account involved)
- game launch independent from CheatBreaker's backend
- in-game title screen unlocked so offline accounts can open SINGLEPLAYER / MULTIPLAYER
- premium accounts in the same install are never modified
- CheatBreaker starts automatically when the patcher finishes

Supported target: **CheatBreaker 2026.9.1** (Electron 44.2.0, client jars 1.7.10 / 1.8.9).
Everything is version-pinned. A new CheatBreaker release requires re-deriving the anchors
(section 5) — never assume old offsets still apply.

Non-goals (do not add them, ever):

- no stealth, no anti-detection, no hiding of the patch (a visible footer marker is part of the deal)
- no bypass of server-side premium checks — those are the server operator's decision and stay untouched
- no modification of premium accounts' behavior

---

## 1. System map

### 1.1 Install layout (Windows)

| Path | Content |
|---|---|
| `%LOCALAPPDATA%\Programs\cheatbreaker\CheatBreaker.exe` | Electron host (~190 MB) |
| `%LOCALAPPDATA%\Programs\cheatbreaker\resources\app.asar` | all application code (JS) |
| `%LOCALAPPDATA%\Programs\cheatbreaker\resources\app.asar.unpacked\` | 45 native/build files under `node_modules/@parcel/` (incl. `watcher-win32-x64/watcher.node`) |
| `%APPDATA%\CheatBreaker\launcher\settings.json` | launcher settings (electron-settings, free-form schema) |
| `%APPDATA%\CheatBreaker\downloads\versions\{1.7.10,1.8.9}\{v}.patch` | **the game client jar** (CB-modified, classpath entry) |
| `%APPDATA%\CheatBreaker\downloads\versions\{v}\{v}.json` | version JSON (vanilla-format works) |
| `%APPDATA%\CheatBreaker\logs\renderer.log` | renderer log (boot proof, socket trace, game stdout) |
| `%APPDATA%\.minecraft\cheatbreaker_accounts.json` | account store |

### 1.2 CheatBreaker architecture (verified by decompilation)

- The **main process** (`index.js`, ~1 MB) only owns the WebSocket to
  `wss://playerassets.cheatbreaker.net/launcher` and relays it over IPC (`socket:*`).
  It never touches auth, accounts, or game launch. No `uncaughtException` handler:
  any unhandled throw in main = silent exit code 1.
- The **renderer** (`js/app.<hash>.js`, ~350 KB, Vue 3, `nodeIntegration:true,
  contextIsolation:false`) contains *everything that matters*: full Node access
  (`fs`, `crypto`, `child_process`), Microsoft device-code/PKCE auth, the
  AccountManager, and the Java launch pipeline (`spawn`).
- Both BrowserWindows run with `show:false` until `did-finish-load`: a broken renderer
  = invisible/blank window while the process stays alive. **A live process does not
  prove a working UI — check `renderer.log`.**

### 1.3 Account store schema

`%APPDATA%\.minecraft\cheatbreaker_accounts.json`:

```json
{
  "activeAccountLocalId": "offline<32 hex>",
  "accounts": {
    "offline<32 hex>": {
      "accessToken": "0",
      "accessTokenExpiresAt": "2099-01-01T00:00:00.000Z",
      "refreshToken": "",
      "localId": "offline<32 hex>",
      "minecraftProfile": { "id": "<32 hex, NO dashes>", "name": "Player" },
      "type": "Xbox"
    }
  }
}
```

Invariants (all verified in code):

- `minecraftProfile.id` is stored **without dashes**; `loginAsAccount(id)` matches by
  `minecraftProfile.id == id.replace(/-/g,"")`. Wrong format = silently not found.
- `type` stays `"Xbox"`: it is injected verbatim as `${user_type}` in the game args.
- The token refresh short-circuits when `accessTokenExpiresAt` is in the future.
  `2099-01-01` makes an offline account maintenance-free.
- The file must be UTF-8 **without BOM** (launcher `JSON.parse` dies on a BOM and
  would then rewrite a default empty store).

Offline UUID (Minecraft standard): `md5("OfflinePlayer:<name>")`, byte 6 high nibble = 3,
byte 8 top two bits = `10`, hex formatted with dashes for display, without dashes for storage.

### 1.4 Backend protocol (wss://playerassets.cheatbreaker.net/launcher)

Outgoing, in order: `LauncherInfo {version, branch, os, arch, installationID}`,
then `LoggedInAccounts {accounts: [{username, uuid}]}` (all local accounts).

Server answers `AccountsVerify {publicKey, accounts:[uuid]}`; the client performs a
Mojang `sessionserver.mojang.com/session/minecraft/join` per claimed uuid with its real
accessToken, then replies `AccountsVerified {secretKey: RSA(random16, publicKey)}`.
Server replies `Authenticated {token}` (the CB token, keepalive 30 s, passed to the game
as `--websocketToken`). Any unknown uuid in `LoggedInAccounts` → server closes
**code 4001, reason `"Failed to Login: Failed to find account information"`** →
the client retries forever with 10 s × failures backoff. This is why offline accounts
must never appear in that packet (patch P4).

Launch: client sends `PreLaunch {version, branch}` and waits (10 s) for
`ContinueLaunch {branch, client(URL), hash(md5), version, javaVersion}`. No answer →
`null` → stock error toast and no launch (patch P2 fixes this). The client URL serves
the CB client package; the launcher checks md5 against the local `.patch` file and
re-downloads on mismatch (patch P7 skips this for offline installs).

`https://client-api.cheatbreaker.net/mappings/*` and `news.cheatbreaker.net` are public
GETs, used without auth. `api.cheatbreaker.net/profile/{uuid}` is non-blocking at launch
(only an explicit `banned` hard-stops).

### 1.5 Electron fuses (why repacking works)

Fuse sentinel `dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX` at file offset `0xBE2E6F8` in
`CheatBreaker.exe`; wire = `[sentinel 32B][version=1][length=9][9 × ASCII '0'/'1']`.
`EnableEmbeddedAsarIntegrityValidation` (offset `0xBE2E71E`) and `OnlyLoadAppFromAsar`
(`0xBE2E71F`) are both `'0'` (disabled) → **a repacked app.asar loads as-is, and per-file
`integrity` fields may be omitted**. If a future build flips them, repacking requires
patching those bytes or recomputing the embedded header hash — out of scope for now.

---

## 2. Patch inventory (what the patcher does, and where)

Single source of truth for the JS anchors: `cia_patcher.py`, list `JS_PATCHES`.
Each entry is `(name, anchor, replacement, marker)` and is applied only if `marker` is
absent, with an occurrence-count check on `anchor` (see rules §3). Summary:

| # | Name | Target (renderer bundle) | Effect |
|---|------|--------------------------|--------|
| P1 | offline login | `runDeviceCodeLogin` method head | if `%APPDATA%\.minecraft\offline_username.txt` exists: build the offline account (schema §1.3), write it, `loginAsAccount`, resolve the same `{promise, cancel}` contract the device-code flow fulfills; else fall through to stock Microsoft flow |
| P2 | launch fallback | `validateClient`'s 10 s `ContinueLaunch` timeout (`},1e4)` anchor) | synthesize `{branch:"offline", client:"", hash:"offline", version:t, javaVersion:"25"}` — **"25", not "8": the CDN only hosts `25u36` (`/jre/Windows/java8/...` returns 404), and CB itself runs 1.7.10/1.8.9 on Java 25**; bootstrap vanilla (Mojang manifest → version JSON + client.jar saved as `{v}.patch`) when the jar is missing; **resolve with the final object, never a nested Promise** |
| P3 | visual marker | footer vnode string | appends `" • patched by cia"` to the home-screen footer |
| P4 | socket filter | `LoggedInAccounts` builder | `.filter(function(e){return"0"!==e.accessToken})` — offline uuids never reach the backend |
| P5a | connecting gate (ui) | 500 ms poll setting `isConnected` | active offline account counts as connected |
| P5b | connecting gate (launch) | `na.isLoggedIn&&Hr.completedConnection` (exactly 2 occurrences) | launch allowed for the active offline account without backend auth |
| P6 | toast | `handleClose` toast | suppressed while the *active* account is offline (diagnostics preserved otherwise) |
| P7 | client jar keep | md5 check of `versions/{v}/{v}.patch` | skipped when any offline account exists — the patched jar is never re-downloaded/reverted |
| P8b | forced update block | `case 18:return P=n.data,...zn(P.launcher,...)` | the CB backend can force-close the launcher (update packet -> download Setup -> app.exit(0)) — blocked while any offline account exists |
| P8c | token refresh guard | `refreshAccountToken` condition | a forced refresh (server close "account session was not valid") skips offline accounts — their empty refreshToken would clear the session ("You must be signed in" death loop) |
| P8c | java version migration | injected P2 response | migrates v1.0.0-patched installs from `javaVersion:"8"` to `"25"` (optional anchor, 0 or 1 occurrences) |

Java side (P8), per version:

| Version | Title-screen class | isAuthed getter | Manager |
|---|---|---|---|
| 1.7.10 | `IlllIIIIIIIllIIIllllIllII` | `IlllIllllllIIIlIlIllllIlI()` | `IllIIllIIIIIlIlIIlIlIIlII` |
| 1.8.9 | `IllllIIlIIIIIIlIIlIlIllII` | `IllllIlIIIlllllllIlIlllIl()` | `IlIllIIIIlIllIlIlIIIIllll` |

Patch: with Javassist `ExprEditor`, replace every call to the isAuthed getter inside the
title-screen class with `{ $_ = true; }` (5 call sites: 4 × `button.setEnabled(isAuthed())`
+ `if (!isAuthed())`). That is the **whole** Java change — the server-join code itself is
not gated by CB auth, and offline-mode servers never issue an encryption request, so the
vanilla login handshake carries only username/UUID and succeeds.

Beware: the obfuscator **reuses names across classes** (in 1.8.9 the string-pool field of
class `IlIIIlIIllllIllIIlllIlllI` is literally named `IlIllIIIIlIllIlIlIIIIllll`, which is
also the *manager class* name). Always resolve names from the decompiled target file, not
from another class.

---

## 3. Hard rules (never break these)

1. **Anchors over offsets.** Never hardcode byte offsets for the JS patches. Match exact,
   unique strings (assert occurrence count) so the patcher survives refloats of the bundle.
   The only acceptable offsets are the fuse table and binary-format constants.
2. **Idempotence by marker.** Every patch carries a string that only exists after it is
   applied. Re-running on a patched install must be a no-op ("already patched").
3. **Syntax gate before any repack.** `node --check` the patched bundle **as ESM**
   (copy to `.mjs`): the CommonJS check false-fails with `Unexpected token 'case'` on
   these webpack bundles. A single unbalanced paren in a regenerator state machine
   produced a fully booted process with a dead renderer and no log lines — caught only
   by this gate (and later by a byte-diff against the last known-good bundle).
4. **Backups before first write.** `app.asar.ORIGINAL`, `{v}.patch.ORIGINAL`,
   plus the original bundle copy in `patch_backup/`. Restoring them must always be a
   viable rollback.
5. **Premium accounts are untouchable.** The accounts-file merge only ever adds keys and
   switches `activeAccountLocalId`; it never edits existing entries.
6. **The backend handshake stays honest.** Filter offline accounts out of packets (P4);
   never forge Mojang tokens, never fake the `AccountsVerified` RSA proof.
7. **Byte-diff against a known-good artifact when in doubt.** If behavior differs and the
   logs do not explain it, dump the suspect file from the asar and compare with the last
   working build. It found in seconds what log-diving had missed.
8. **Prove the UI, not the process.** "Process alive after 25 s" is not success. Success
   = `renderer.log` reaching `[Socket] Authenticated!` and, for the game,
   `[Game] Setting user: <name>`.

---

## 4. Traps catalog (every one of these was hit for real)

Binary / asar:

- **Header framing**: `u32[0]=4`, `u32[1]=8+align4(json_len)`, `u32[2]=u32[1]-4`
  (mandatory — `base::Pickle` rejects the archive otherwise), `u32[3]=json_len`;
  content base = `8 + u32[1]`; files written back-to-back with **no inter-file padding**;
  offsets are decimal **strings relative to the content base**; unpacked entries carry
  `size` + `unpacked:true` and no `offset`.
- **Unpacked files are not in the archive content.** After extraction they exist only in
  `app.asar.unpacked/`; when repacking you must re-mark them (45 files under
  `node_modules/@parcel`) or the native module load dies. Both `asar@3.2.0` and modern
  `@electron/asar` CLI silently drop or ignore `--unpack-dir` → the repo ships its own
  packer (`pack_asar` in `cia_patcher.py`).
- **Omitting per-file `integrity` is fine** only because the fuse is off (see §1.5).

Launcher JS:

- Regenerator (async/await) code: closing nested IIFEs inside a `setTimeout` body needs
  `})()})()` — one missing `})()` pair = dead renderer, see rule 3.
- The 10 s-timeout and the 100 ms-cancel callbacks share their inner text; disambiguate
  anchors with the `},1e4)` suffix.
- `loginAsAccount` takes the **uuid without dashes** (matched against
  `minecraftProfile.id`), not the `localId`.
- Reading a file inside a webpack module only sees that module's scope: patched code in
  the renderer must only reference identifiers already used in the same module
  (`Z`, `H`, `q`, `G`, `ge()`, `Qr`, `Hr`, `Jr`, `Wt`, `na`, `vr`, `Ce`...).

Java client:

- **String pools**: all literals live in 1024-item `public static String[]` tables;
  code references them by index, and Vineflower constant-folds the index
  (`IlIIlIlIlIIIlIlIlIlIllllI.IllIIllIIIIIlIlIIlIlIIlII[3779 & -31801]` = `[707]`).
  To find which class uses a given message: extract the pool, compute the index, then
  eval-fold every pool access in candidate files.
- **Javassist refuses `ClassPool.get` on a jar whose extension is `.patch`** (treated as
  a directory/unknown): copy it to `*.jar` first, then `pool.appendClassPath(...)`.
- Javassist writes the patched class via `cc.writeFile(dir)`; re-inject it into the jar
  with `zipfile` (replace the single entry, keep the rest byte-identical).
- The 1.8.9 jar's class names differ from 1.7.10's (independent obfuscation runs) — never
  reuse 1.7.10 names for 1.8.9; re-derive both.

Client jar:

- **The client jar gets reverted silently**: any launch where the socket authenticates
  (premium accounts present) receives a real `ContinueLaunch` whose md5 differs from the
  patched jar → re-download of the pristine package. P7 stops this only while at least
  one offline account exists in the accounts file. After any revert, just re-run the
  patcher: `patch_client` detects the original class by sha256 and re-injects.
- **JRE URLs**: `https://r2.cheatbreaker.net/jre/{os}/{javaType}/{arch}/jre.zip` with
  `javaType` = `25u36` or `25u36-patched` (GPU-dependent). Only 25u36 is hosted —
  any synthesized `javaVersion` other than "25" fails with 404 after 10 retries.

Environment:

- `node --check` must run on a `.mjs` copy (ESM), see rule 3.
- Windows file locks: kill `CheatBreaker.exe` **and** `javaw.exe` before touching files;
  retry `os.replace` up to 5 × 1 s.
- Single-instance lock is keyed on userData: original and patched copies lock each other;
  always `taskkill` before boot tests. A 4-process `CheatBreaker.exe` listing is normal
  Electron, not a failure.
- PowerShell 5.1: `ConvertFrom-Json -AsHashtable` does not exist; `Set-Content -Encoding
  UTF8` writes a BOM (the launcher's `JSON.parse` then nukes the account file). Use
  `[IO.File]::WriteAllText(path, json, UTF8Encoding($false))`.
- PyInstaller: `--add-data` needs an absolute path when `--specpath` differs; `--icon NONE`
  for the plain Windows icon. A onefile exe relaunching a downloaded exe **must strip
  `_PYI*` variables from the child env**, otherwise the child's parent-validation fails
  with `Security validation failure: failed to obtain executable path for parent proces!`.
- In Git Bash, heredocs mangle backslash regexes — write Python scripts to files, do not
  inline them.

---

## 5. Procedure: patch a new CheatBreaker version

Run this end to end after any CB release. Nothing in the list is optional.

1. **Collect**: download the new `CheatBreaker_Setup.exe` into a working folder.
2. **Identify**: `pefile_analysis.py info` (expect NSIS-3 Unicode) → `7z x` → inner
   `app-64.7z` → `7z x` → Electron app → `electron_unpack.py asar` on `resources/app.asar`.
3. **Confirm nothing structural changed**:
   - fuses still disabled (scan the sentinel, dump the wire — §1.5);
   - `main: index.js`, renderer still `js/app.<hash>.js`, `nodeIntegration` still on;
   - account file path/logic unchanged (grep `cheatbreaker_accounts.json`);
   - socket/login flow anchors still recognizable.
4. **Re-derive the JS anchors** on the new renderer bundle (grep + python `re` windows):
   - `runDeviceCodeLogin` head;
   - `validateClient` timeout (`},1e4)`) vs the 100 ms cancel twin;
   - footer vnode string;
   - `LoggedInAccounts` builder;
   - `e.isConnected=Hr.completedConnection},500`;
   - `na.isLoggedIn&&Hr.completedConnection` (count them);
   - the `Disconnected from Asset Server` toast;
   - the client-jar md5 check `ke((0,q.join)(i,...`.
   Update `JS_PATCHES` in `cia_patcher.py` (anchor + marker stay paired).
5. **Re-derive the Java targets**: extract each `{v}.patch`, find the string pool holding
   `Authenticating with the server.`, compute its index, fold-eval pool accesses across
   referencing classes to locate the title-screen class, read its 4 `setEnabled` calls,
   note the isAuthed getter name and the manager class. Update the Javassist patcher.
6. **Re-embed**: hash the *original* title-screen classes (sha256) into
   `embedded_classes.json`, and replace `patched_b64` with freshly patched classes
   (procedure §6). If a version's class hash does not match at patch time, the patcher
   skips that jar with a warning — this is by design.
7. **Test** (procedure §7).
8. **Release** (procedure §8).

---

## 6. Procedure: rebuild the Java client patch

```
# 0) tools: JDK 21, vineflower.jar, javassist.jar (Maven Central)
# 1) extract the pristine client jar
7z x <v>.patch -o/tmp/cb<v>
# 2) locate the string pool (class containing "Authenticating with the server.")
#    decompile it, compute the index of the literals you care about
# 3) find the title-screen class: python-scan every class referencing the pool
#    class name, decompile them, eval-fold pool[index] expressions, keep the file
#    using SINGLEPLAYER/MULTIPLAYER/Authenticating indices
# 4) patch
cat > PatchCB.java   # ClassPool + appendClassPath(<copy of jar as .jar>)
                     # cc.instrument(new ExprEditor(){ editMethodCall ->
                     #   if (name.equals("<isAuthed>")) m.replace("{ $_ = true; }") })
javac -cp javassist.jar PatchCB.java
java -cp "javassist.jar;." PatchCB <jar-as-.jar> out/
# 5) verify by decompiling out/<class>.class: expect setEnabled(true) x4 and if(!true)
# 6) inject: python zipfile - replace <class>.class entry, everything else untouched
```

---

## 7. Test protocol (all steps mandatory)

1. `node --check` the patched renderer bundle as `.mjs` — must pass.
2. Parse the repacked asar: framing ints sane, file count unchanged, extracted renderer
   bundle byte-compared against the last known-good when available.
3. Kill `CheatBreaker.exe` + `javaw.exe`, launch the exe (`Start-Process -PassThru`),
   assert still running at 20-25 s.
4. Assert `renderer.log` contains, in order: `Fetching API Profiles...`, `Socket Connected!`,
   `Current Launcher Version`, and — only after a real login/launch — `[Socket]
   Authenticated!`. Zero occurrences of `4001` / `Failed to Login`.
5. Offline identity in-game: trigger a launch and assert
   `[Game] Setting user: <nickname>` and `[Game] Setting UUID: <offline uuid>` in the log
   (OptiFine lines prove the CB client package was delivered through `ContinueLaunch`).
6. In-game: title screen buttons enabled, no status text, MULTIPLAYER opens the server
   list, joining an offline-mode server lands on its `/register` prompt.
7. Patch flow itself: run the patcher twice in a row — second run must report
   "already patched" everywhere and still add the account.

---

## 8. Release runbook (version bump → published update)

1. Bump `PATCHER_VERSION` in `cia_patcher.py` (semver-ish, integers only).
2. Regenerate `cia_build_info.py` (build date/time is stamped at build, not run time):
   `BUILD_DATE = "M/D/YYYY"`, `BUILD_TIME = "H:MMam|pm"` (12 h, no leading zero).
3. Build: `pyinstaller --onefile --icon NONE --name cia_patcher_<version>
   --add-data <abs>/embedded_classes.json;.
   --add-data <abs>/embedded_java.json;. cia_patcher.py` (Python 3.11; the release
   asset is named `cia_patcher_<version>.exe` to avoid download duplicates).
4. Sanity-run the new exe: header shows the new stamp; update check hits
   `raw.githubusercontent.com/ryad313/crack-account-cheatbreaker/main/latest.json`.
5. Commit source changes; push to `main`.
6. Create the GitHub release `v<x.y.z>` with `cia_patcher.exe` as asset.
7. Update **repo-root** `latest.json`: `version` = new semver, `url` =
   `https://github.com/ryad313/crack-account-cheatbreaker/releases/download/v<x.y.z>/cia_patcher.exe`.
   This file is the self-update source of truth; the copy attached to each release is a
   frozen snapshot only.
8. Verify: `curl` the raw `latest.json`, confirm the asset URL returns 200, and run an
   old-version exe once to watch it self-update (build a witness with a lower
   `PATCHER_VERSION` if needed).
9. Housekeeping: remove test accounts from the accounts file; keep the user's accounts.

Update-swap design (already implemented, do not "simplify"): download to `<exe>.new`,
rename running exe to `<exe>.old`, `os.replace(.new → exe)`, strip `_PYI*` from the child
env, `Popen` detached, sleep 1 s, exit. The old exe remains as `.old` for manual rollback.

---

## 9. Tooling requirements

- Windows 10/11, Python 3.11+ (stdlib only for the patcher itself), Node.js (syntax gate)
- 7-Zip CLI, JDK 21 + `javac`/`java`, Vineflower (decompiler), Javassist 3.30
- For the exe: PyInstaller (built with Python 3.11; the 3.14 interpreter had no wheel)
- GitHub: a fine-grained/classic token with repo + release scope (revoke it after use —
  never commit it; push via one-shot URL, then `git remote remove origin`)

## 10. File map (repository)

| File | Role |
|---|---|
| `cia_patcher.py` | the whole patcher: JS anchors, asar extract/pack, Java class injection, account store, self-update, auto-start |
| `embedded_classes.json` | pre-patched title-screen classes (base64) + original sha256 pins per version |
| `cia_build_info.py` | build stamp consumed by the header |
| `latest.json` | self-update manifest read from the raw repo URL |
| `README.md` | user-facing overview |
| `how_to_update.md` | this document |

Working-directory companions (not in the repo): `cb_offline_patcher.py` (dev-time patcher,
same anchors), `cb_asar_pack.py` (standalone asar packer used during development),
`patch_backup/`, `extracted_asar/`, `extracted_app/`, `CheatBreaker_Offline/`.

---

*Maintained 2026-09-26 against CheatBreaker 2026.9.1. Every statement above was verified
against the shipped binaries during the original engineering session; if reality and this
document disagree, re-verify against the binaries and update this file.*
