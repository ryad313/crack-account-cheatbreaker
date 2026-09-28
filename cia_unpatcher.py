"""Restore local CheatBreaker backups without shipping user data or game files."""
import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

VERSION = "1.1.7"
BUILD = "automatic"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_asar(path):
    with path.open("rb") as stream:
        framing = stream.read(16)
        if len(framing) != 16:
            raise ValueError("Invalid ASAR header")
        magic, total, pickle_size, length = struct.unpack("<IIII", framing)
        if magic != 4 or pickle_size != total - 4 or not 0 < length <= 32 * 1024 * 1024:
            raise ValueError("Invalid ASAR framing")
        if total != 8 + ((length + 3) & ~3) or 8 + total > path.stat().st_size:
            raise ValueError("Invalid ASAR size")
        return json.loads(stream.read(length)), 8 + total


def entries(node, prefix=""):
    if "files" in node:
        for name, child in node["files"].items():
            if name in (".", "..") or "/" in name or "\\" in name:
                raise ValueError("Unsafe ASAR entry")
            yield from entries(child, prefix + name + "/")
    else:
        yield prefix.rstrip("/"), node


def launcher_patched(path):
    header, base = read_asar(path)
    found = False
    with path.open("rb") as stream:
        for name, entry in entries(header):
            if re.fullmatch(r"js/app\.[^/]+\.js", name):
                found = True
                stream.seek(base + int(entry["offset"]))
                content = stream.read(entry["size"])
                if len(content) != entry["size"]:
                    raise ValueError("Truncated renderer bundle")
                if b"CB Offline:" in content or b"patched by cia" in content:
                    return True
    if not found:
        raise ValueError("Cannot identify the launcher renderer")
    return False


def valid_client(path):
    try:
        with zipfile.ZipFile(path) as jar:
            if jar.testzip() is not None:
                return False
            for name in jar.namelist():
                if name.endswith(".class"):
                    data = jar.read(name)
                    # v1.1.6 downgraded obfuscated Java 8 classes to version 48.
                    if re.fullmatch(r"[Il]{8,}\.class", name) and data[:4] == b"\xca\xfe\xba\xbe":
                        if struct.unpack(">H", data[6:8])[0] == 48:
                            return False
        return True
    except (OSError, ValueError, zipfile.BadZipFile, struct.error):
        return False


def build_plan(resources, versions, accounts, offline_marker):
    actions, notices = [], []

    def restore(target, source):
        if not target.exists() or digest(target) != digest(source):
            actions.append({"target": target, "source": source, "label": "Restore " + target.name})

    def remove(target, label):
        if target.is_file():
            actions.append({"target": target, "label": label})

    asar = resources / "app.asar"
    original = resources / "app.asar.ORIGINAL"
    if not asar.is_file() and not original.is_file():
        raise ValueError("CheatBreaker installation not found")
    patched = asar.is_file() and launcher_patched(asar)
    if original.is_file():
        if launcher_patched(original):
            raise ValueError("The launcher backup is already patched. Reinstall official CheatBreaker first.")
        reference = original
        restore(asar, original)
    elif patched:
        raise ValueError("app.asar.ORIGINAL is missing. Reinstall official CheatBreaker; no changes made.")
    else:
        reference = asar
        notices.append("Launcher is already unpatched.")

    # Patcher versions did not always back up unpacked files. Validate them
    # against the original ASAR integrity metadata before restoring its header.
    header, _ = read_asar(reference)
    for name, entry in entries(header):
        if not entry.get("unpacked"):
            continue
        target = resources / "app.asar.unpacked" / name
        source = resources / "app.asar.unpacked.ORIGINAL" / name
        candidate = source if source.is_file() else target
        if not candidate.is_file() or candidate.stat().st_size != entry["size"]:
            raise ValueError("Missing or damaged native file: " + name + ". Reinstall official CheatBreaker.")
        integrity = entry.get("integrity", {})
        if integrity.get("algorithm") == "SHA256" and digest(candidate) != integrity["hash"]:
            raise ValueError("Native file integrity check failed: " + name)
        if source.is_file():
            restore(target, source)

    if versions.is_dir():
        for directory in sorted(versions.iterdir()):
            if not directory.is_dir():
                continue
            jar = directory / (directory.name + ".patch")
            backup = Path(str(jar) + ".ORIGINAL")
            if backup.is_file() and valid_client(backup):
                restore(jar, backup)
            elif jar.is_file() and (patched or original.is_file()):
                remove(jar, "Set aside " + jar.name + " for official re-download")
                remove(directory / (directory.name + ".json"), "Set aside matching version metadata")
                notices.append(directory.name + ": no usable client backup; the official launcher will re-download it.")

    if accounts.is_file():
        store = json.loads(accounts.read_text(encoding="utf-8-sig"))
        if not isinstance(store, dict) or not isinstance(store.get("accounts"), dict):
            raise ValueError("Unexpected account file format; no changes made")
        records = store["accounts"]
        offline = [key for key, value in records.items()
                   if isinstance(value, dict) and re.fullmatch(r"offline[0-9a-f]{32}", key)
                   and value.get("localId") == key and value.get("accessToken") == "0"
                   and value.get("refreshToken", "") == ""]
        if offline:
            for key in offline:
                del records[key]
            if store.get("activeAccountLocalId") in offline:
                store["activeAccountLocalId"] = next(iter(records), "")
            actions.append({"target": accounts,
                            "data": (json.dumps(store, indent=2) + "\n").encode("utf-8"),
                            "label": "Remove %d patcher-created offline account(s); preserve all other entries" % len(offline)})
    remove(offline_marker, "Disable the offline login marker")
    return actions, notices


def replace_file(source, target):
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5)


def atomic_write(target, source=None, data=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".cia-restore-", dir=target.parent)
    os.close(handle)
    temporary = Path(temporary)
    try:
        if source is not None:
            shutil.copy2(source, temporary)
            if digest(source) != digest(temporary):
                raise OSError("Restore copy verification failed")
        else:
            temporary.write_bytes(data)
        replace_file(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def apply_plan(actions, backup_root):
    if not actions:
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d_%H%M%S_"), dir=backup_root))
    snapshots = []
    # Back up and verify every affected file before changing any of them.
    for index, action in enumerate(actions):
        target = action["target"]
        saved = session / ("%03d_" % index + target.name)
        existed = target.is_file()
        if existed:
            shutil.copy2(target, saved)
            if digest(target) != digest(saved):
                raise OSError("Pre-restore backup verification failed")
        snapshots.append((target, saved, existed))
    manifest = [{"target": str(target), "backup": saved.name if existed else None}
                for target, saved, existed in snapshots]
    (session / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    changed = []
    try:
        for action, snapshot in zip(actions, snapshots):
            changed.append(snapshot)
            if "source" in action or "data" in action:
                atomic_write(action["target"], action.get("source"), action.get("data"))
            else:
                action["target"].unlink(missing_ok=True)
            print("OK: " + action["label"])
    except Exception as error:
        failures = []
        for target, saved, existed in reversed(changed):
            try:
                if existed:
                    atomic_write(target, source=saved)
                else:
                    target.unlink(missing_ok=True)
            except Exception as rollback_error:
                failures.append(str(target) + ": " + str(rollback_error))
        if failures:
            raise RuntimeError("Restore failed; manual recovery needed from " + str(session)
                               + ": " + "; ".join(failures)) from error
        raise RuntimeError("Restore failed; changes rolled back. Backup: " + str(session)) from error
    return session


def process_inventory():
    command = ("Get-CimInstance Win32_Process -Filter \"Name='CheatBreaker.exe' OR "
               "Name='javaw.exe' OR Name='java.exe'\" | "
               "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | "
               "ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, errors="replace", check=True)
    data = json.loads(result.stdout or "[]")
    return data if isinstance(data, list) else [data]


def target_processes(processes, install, downloads):
    executable = ntpath.normcase(ntpath.normpath(str(install / "CheatBreaker.exe")))
    launcher_ids = {p["ProcessId"] for p in processes
                    if ntpath.normcase(ntpath.normpath(p.get("ExecutablePath") or "")) == executable}
    targets = set(launcher_ids)
    prefix = ntpath.normcase(ntpath.normpath(str(downloads))).rstrip("\\") + "\\"
    for process in processes:
        if (process.get("Name") or "").lower() not in ("java.exe", "javaw.exe"):
            continue
        command = (process.get("CommandLine") or "").replace("/", "\\").lower()
        if process.get("ParentProcessId") in launcher_ids or (prefix in command and ".patch" in command):
            targets.add(process["ProcessId"])
    return sorted(targets)


def close_instances(install, downloads):
    for attempt in range(3):
        targets = target_processes(process_inventory(), install, downloads)
        if not targets:
            return
        print("Closing CheatBreaker and its game processes...")
        for pid in targets:
            # PID-targeted tree shutdown also covers launcher child processes.
            # Java applications unrelated to CheatBreaker are never selected.
            command = ["taskkill", "/PID", str(pid), "/T"]
            if attempt:
                command.append("/F")
            subprocess.run(command, capture_output=True, text=True, errors="replace")
        time.sleep(1)
    if target_processes(process_inventory(), install, downloads):
        raise RuntimeError("Could not close CheatBreaker or its game. No files were restored.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="cia unpatcher " + VERSION + " (" + BUILD + ")")
    parser.add_argument("--dry-run", action="store_true", help="Show the restoration plan without changing files")
    options = parser.parse_args()
    if os.name != "nt" or not os.environ.get("APPDATA") or not os.environ.get("LOCALAPPDATA"):
        raise RuntimeError("Run this program in a normal Windows user session")
    roaming = Path(os.environ["APPDATA"])
    resources = Path(os.environ["LOCALAPPDATA"]) / "Programs/cheatbreaker/resources"
    print("cia unpatcher " + VERSION + " (" + BUILD + ")")
    downloads = roaming / "CheatBreaker/downloads"
    settings = roaming / "CheatBreaker/launcher/settings.json"
    if settings.is_file():
        configured = json.loads(settings.read_text(encoding="utf-8-sig")).get("downloads_dir")
        if configured:
            downloads = Path(configured)
    def plan():
        return build_plan(resources, downloads / "versions",
                          roaming / ".minecraft/cheatbreaker_accounts.json",
                          roaming / ".minecraft/offline_username.txt")
    actions, notices = plan()
    if not options.dry_run:
        close_instances(resources.parent, downloads)
        actions, notices = plan()
    for notice in notices:
        print(notice)
    for action in actions:
        print("- " + action["label"])
    if options.dry_run:
        print("Dry run: no files changed.")
        return
    session = apply_plan(actions, roaming / "CheatBreaker/unpatch-backups")
    if session:
        print("Backup: " + str(session))
        print("Keep this backup private: it can contain account credentials.")
    print("Done. Open CheatBreaker normally. Missing clients will download on launch.")


if __name__ == "__main__":
    result = 0
    log_stream = None
    if len(sys.argv) == 1 and os.environ.get("LOCALAPPDATA"):
        log_path = Path(os.environ["LOCALAPPDATA"]) / "cia_unpatcher/cia_unpatcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_path.open("a", encoding="utf-8")
        class Output:
            def __init__(self, console, log):
                self.console, self.log = console, log
            def write(self, text):
                self.log.write(text)
                self.log.flush()
                if self.console:
                    self.console.write(text)
            def flush(self):
                self.log.flush()
                if self.console:
                    self.console.flush()
        sys.stdout = Output(sys.stdout, log_stream)
        print("\n" + time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print("Error: " + (str(error) or "Cancelled"))
        result = 1
    if log_stream:
        sys.stdout.flush()
        sys.stdout = sys.__stdout__
        log_stream.close()
    sys.exit(result)
