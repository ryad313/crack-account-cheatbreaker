#!/usr/bin/env python3
# cia patcher - one-shot CheatBreaker offline-account enabler.
# Usage: python cia_patcher.py   (interactive, prompts for a nickname)

import base64
import hashlib
import json
import os
import random
import re
import shutil
import string
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

APP_NAME = "CheatBreaker"
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "cheatbreaker")
RESOURCES = os.path.join(INSTALL_DIR, "resources")
ACCOUNTS = os.path.join(os.environ.get("APPDATA", ""), ".minecraft", "cheatbreaker_accounts.json")
CLIENTS_DIR = os.path.join(os.environ.get("APPDATA", ""), "CheatBreaker", "downloads", "versions")
UNPACK_PREFIX = "node_modules/@parcel"

VERSION = "2026.9.1"

# build stamp (frozen at build time by the build step, falls back to source values)
try:
    from cia_build_info import BUILD_DATE, BUILD_TIME
except ImportError:
    BUILD_DATE, BUILD_TIME = "", ""
HEADER = f"cia patcher {BUILD_DATE} at {BUILD_TIME} on cheatbreaker {VERSION}"

# self-update: pinned to the latest.json published in the patcher repository
PATCHER_VERSION = "1.1.0"
UPDATE_URL = ("https://raw.githubusercontent.com/ryad313/crack-account-cheatbreaker/main/latest.json")

# ---------------------------------------------------------------- JS patches (renderer bundle)
# Each patch: unique anchor -> replacement, marker proves it is already applied.
JS_PATCHES = [
    (
        "offline login",
        '{key:"runDeviceCodeLogin",value:function(e){var t=this;Jr.log("Running Device Code Auth Protocol");',
        '{key:"runDeviceCodeLogin",value:function(e){var t=this;'
        'var _off="";try{_off=(0,Z.readFileSync)((0,q.join)(ge().minecraft,"offline_username.txt"),"utf-8").trim()}catch(_e){}'
        'if(_off){'
        'Jr.log("CB Offline: offline login for "+_off);'
        'var _b=G.createHash("md5").update("OfflinePlayer:"+_off).digest();'
        '_b[6]=_b[6]&15|48;_b[8]=_b[8]&63|128;'
        'var _hex=Array.from(_b,function(_x){return _x.toString(16).padStart(2,"0")}).join(""),'
        '_id=_hex.slice(0,8)+"-"+_hex.slice(8,12)+"-"+_hex.slice(12,16)+"-"+_hex.slice(16,20)+"-"+_hex.slice(20);'
        'var _loc="offline"+_id.replace(/-/g,"");'
        'var _pr=new Promise(function(_res){'
        't.readAccountsFile().then(function(_f){'
        '_f.accounts[_loc]={accessToken:"0",accessTokenExpiresAt:new Date(8640000000000000).toISOString(),'
        'refreshToken:"",localId:_loc,minecraftProfile:{id:_id.replace(/-/g,""),name:_off},type:"Xbox"};'
        '_f.activeAccountLocalId=_loc;'
        't.writeAccountsFile(_f).then(function(){'
        't.loginAsAccount(_id.replace(/-/g,""),_f),'
        'Hr.isOpen&&Hr.login(!0),'
        'Jr.log("CB Offline: logged in as "+_off+" ("+_id+")"),_res(t.user)'
        '})["catch"](function(){return _res(null)})'
        '})["catch"](function(){return _res(null)})});'
        'return{promise:_pr,cancel:function(){}}}'
        'Jr.log("Running Device Code Auth Protocol");',
        "CB Offline: offline login for",
    ),
    (
        "launch fallback",
        'Hr.continueLaunchTimeoutId=setTimeout(function(){Hr.clearContinueLaunchTimeout(),'
        'Hr.continueLaunchResolver&&(Hr.continueLaunchResolver(null),Hr.continueLaunchResolver=null)},1e4)',
        'Hr.continueLaunchTimeoutId=setTimeout(function(){Hr.clearContinueLaunchTimeout(),'
        'Hr.continueLaunchResolver&&(function(){'
        'var _res=Hr.continueLaunchResolver;Hr.continueLaunchResolver=null;'
        '(async function(){'
        'try{'
        'var _ver=t,'
        '_dd=await Wt.get("downloads_dir"),'
        '_dir=(0,q.join)(_dd,"versions",_ver),'
        '_pj=(0,q.join)(_dir,_ver+".json"),'
        '_pp=(0,q.join)(_dir,_ver+".patch");'
        'if(!(0,Z.existsSync)(_pp)||!(0,Z.existsSync)(_pj)){'
        'vr.log("CB Offline: bootstrapping vanilla "+_ver);'
        'var _mf=await(await fetch("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")).json(),'
        '_ent=_mf.versions.find(function(_v){return _v.id===_ver});'
        'if(!_ent)throw new Error("version "+_ver+" not found in Mojang manifest");'
        'var _vj=await(await fetch(_ent.url)).json();'
        'await H.mkdir(_dir,{recursive:!0}),'
        'await H.writeFile(_pj,JSON.stringify(_vj),"utf-8");'
        'var _cl=await fetch(_vj.downloads.client.url);'
        'await H.writeFile(_pp,Buffer.from(await _cl.arrayBuffer()))'
        '}'
        'vr.log("CB Offline: launch response synthesized for "+_ver),'
        # javaVersion "25": only JRE 25u36 is still hosted on r2.cheatbreaker.net
        # (java8 returns 404) and CB itself runs 1.7.10/1.8.9 on Java 25
        '_res({branch:"offline",client:"",hash:"offline",version:_ver,javaVersion:"25"})'
        '}catch(_e){vr.error("CB Offline: bootstrap failed: "+_e),_res(null)}'
        # fermetures : async IIFE ( )  + wrapper IIFE ( )  + brace du callback setTimeout
        '})()})()},1e4)',
        "CB Offline: bootstrapping vanilla",
    ),
    (
        "visual marker",
        '(0,x.createElementVNode)("p",null,"Not affiliated with Mojang Studios or CheatBreaker, LLC.",-1)',
        '(0,x.createElementVNode)("p",null,"Not affiliated with Mojang Studios or CheatBreaker, LLC. \\u2022 patched by cia",-1)',
        "patched by cia",
    ),
    (
        "socket account filter",
        '{accounts:na.accounts.map(function(e){return{username:e.minecraftProfile.name,uuid:e.minecraftProfile.id}})}',
        '{accounts:na.accounts.filter(function(e){return"0"!==e.accessToken}).map(function(e){return{username:e.minecraftProfile.name,uuid:e.minecraftProfile.id}})}',
        'return"0"!==e.accessToken}).map',
    ),
    (
        "connecting gate (ui)",
        'e.isConnected=Hr.completedConnection},500',
        'e.isConnected=Hr.completedConnection||(na.profileId&&na.accounts.some('
        'function(e){return e.localId===na.profileId&&"0"===e.accessToken}))},500',
        "e.isConnected=Hr.completedConnection||(",
    ),
    (
        "connecting gate (launch)",
        "na.isLoggedIn&&Hr.completedConnection",
        "(na.isLoggedIn&&(Hr.completedConnection||na.accounts.some("
        'function(e){return e.localId===na.profileId&&"0"===e.accessToken})))',
        "(Hr.completedConnection||na.accounts.some(",
    ),
    (
        "asset server toast",
        ')),Ce({title:"Disconnected from Asset Server",message:"',
        ')),na.accounts.some(function(e){return e.localId===na.profileId&&"0"===e.accessToken})'
        '||Ce({title:"Disconnected from Asset Server",message:"',
        '||Ce({title:"Disconnected from Asset Server"',
    ),
    (
        "client jar keep",
        'e.n=8,ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        'e.n=8,na.accounts.some(function(e){return"0"===e.accessToken})?'
        'Promise.resolve(!0):ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        "na.accounts.some(function(e){return\"0\"===e.accessToken})?Promise.resolve(!0)",
    ),
    (
        # v1.0.0 installs carry the old javaVersion:"8" (JRE 8 URL is 404 on r2);
        # migrate them to 25u36. Optional: pristine bundles do not contain it.
        "migrate java version",
        '_res({branch:"offline",client:"",hash:"offline",version:_ver,javaVersion:"8"})',
        '_res({branch:"offline",client:"",hash:"offline",version:_ver,javaVersion:"25"})',
        'javaVersion:"25"})',
    ),
    (
        "token refresh guard",
        'if(e.p=0,!(new Date(t.accessTokenExpiresAt).getTime()>Date.now())||n){',
        # a forced refresh (server close "account session was not valid") must never
        # touch an offline account: its empty refreshToken would clear the session
        'if(e.p=0,(!(new Date(t.accessTokenExpiresAt).getTime()>Date.now())||n)'
        '&&"0"!==t.accessToken){',
        '&&"0"!==t.accessToken){',
    ),
]

# ---------------------------------------------------------------- patched Java title-screen classes
# Embedded pre-compiled (Javassist): every isAuthed() call replaced with `true`.
# original_sha256 pins the supported client build; a mismatch means an unsupported
# CheatBreaker version and the jar is left untouched.
EMBEDDED_JSON = "embedded_classes.json"


def load_embedded():
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), EMBEDDED_JSON),
        os.path.join(os.getcwd(), EMBEDDED_JSON),
        os.path.join(os.path.dirname(sys.executable), EMBEDDED_JSON),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    return None


# ---------------------------------------------------------------- output helpers
# All steps scroll on a single console line: each show() overwrites the previous text.
# When stdout is not a tty (piped/redirected), fall back to plain newline prints.
_line = {"len": 0}


def show(text):
    if sys.stdout.isatty():
        sys.stdout.write("\r" + text + " " * max(_line["len"] - len(text), 0))
        sys.stdout.flush()
        _line["len"] = len(text)
    else:
        print(text)


def newline():
    sys.stdout.write("\n")
    _line["len"] = 0


def fail(msg):
    newline()
    print(f"Error: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------- step 1: kill running instances
def close_instances():
    status = []
    for image in ("CheatBreaker.exe", "javaw.exe"):
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}"],
                           capture_output=True, text=True, errors="replace")
        if image not in r.stdout:
            status.append(f"{image}: not running")
            continue
        subprocess.run(["taskkill", "/IM", image, "/F"],
                       capture_output=True, text=True, errors="replace")
        r2 = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}"],
                            capture_output=True, text=True, errors="replace")
        if image in r2.stdout:
            if image == "javaw.exe":
                # may belong to an unrelated Java app; jar writes will retry and
                # fail with a clear message only if it actually holds our files
                status.append(f"{image}: still running (unrelated Java app?)")
                continue
            fail(f"could not close {image} - close it manually and rerun")
        status.append(f"{image}: closed")
    return "; ".join(status)


# ---------------------------------------------------------------- step 3: nickname
def offline_uuid(name):
    h = hashlib.md5(("OfflinePlayer:" + name).encode()).digest()
    b = bytearray(h)
    b[6] = (b[6] & 0x0F) | 0x30
    b[8] = (b[8] & 0x3F) | 0x80
    hexs = b.hex()
    return hexs, f"{hexs[0:8]}-{hexs[8:12]}-{hexs[12:16]}-{hexs[16:20]}-{hexs[20:]}"


def is_premium_name(name):
    """True when the nickname belongs to an existing premium Mojang account."""
    try:
        req = urllib.request.Request(
            f"https://api.mojang.com/users/profiles/minecraft/{name}",
            headers={"User-Agent": "cia-patcher"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200, ""
    except urllib.error.HTTPError as e:
        if e.code in (204, 404):
            return False, ""
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e.__class__.__name__)


def random_name():
    letters = "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 6)))
    digits = "".join(random.choices(string.digits, k=random.randint(3, 4)))
    return letters + digits


def ask_nickname():
    accounts_names = set()
    if os.path.exists(ACCOUNTS):
        try:
            with open(ACCOUNTS, encoding="utf-8-sig") as f:
                data = json.load(f)
            for a in data.get("accounts", {}).values():
                accounts_names.add(a.get("minecraftProfile", {}).get("name", "").lower())
        except Exception:
            pass

    def free_name(name):
        """(usable, warning) - checks local list then Mojang premium registry."""
        if name.lower() in accounts_names:
            return False, "name already in your CheatBreaker accounts"
        premium, err = is_premium_name(name)
        if premium:
            return False, "name belongs to an existing premium Minecraft account, pick another"
        if err:
            return True, f"could not verify against Mojang ({err}), using it anyway"
        return True, ""

    while True:
        show("add user: ")
        raw = input().strip()

        if raw.lower() in ("r", "rdm", "random"):
            while True:
                name = random_name()
                usable, _ = free_name(name)
                if usable:
                    newline()
                    return name
            continue

        name = raw
        if not (3 <= len(name) <= 16) or not re.fullmatch(r"[A-Za-z0-9_]+", name):
            newline()
            print("   invalid: use 3-16 letters/digits/underscore")
            continue
        usable, reason = free_name(name)
        if not usable:
            newline()
            print(f"   {reason}")
            continue
        if reason:
            newline()
            print(f"   warning: {reason}")
        newline()
        return name


# ---------------------------------------------------------------- asar format
def align4(n):
    return n + ((4 - n % 4) % 4)


def read_asar(path):
    with open(path, "rb") as f:
        u32 = struct.unpack("<IIII", f.read(16))
        json_len = u32[3]
        f.seek(16)
        header = json.loads(f.read(json_len).decode("utf-8"))
        base = 8 + u32[1]
        f.seek(base)
        return header, base, f.read()  # blob starts at content base, offsets are relative


def extract_asar(header, base, blob, dest):
    """Write all in-archive files to dest; return list of unpacked relative paths."""
    unpacked = []

    def walk(node, rel):
        if "files" in node:
            for name, child in node["files"].items():
                walk(child, os.path.join(rel, name) if rel else name)
            return
        if node.get("unpacked"):
            unpacked.append(rel)
            return
        off = int(node["offset"])
        out = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(blob[off: off + node["size"]])

    walk(header, "")
    return unpacked


def restore_unpacked(src_dir, dest, rels):
    for rel in rels:
        s = os.path.join(src_dir, rel)
        d = os.path.join(dest, rel)
        if os.path.exists(s):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)


def pack_asar(src_dir, out_path, unpack_prefix):
    """Pack a directory into an asar (framing: u32[2] must equal u32[1]-4)."""
    files = sorted(
        (os.path.join(root, f) for root, _, fs in os.walk(src_dir) for f in fs)
    )
    header = {"files": {}}
    order = []

    def node_for(rel):
        parts = rel.split("/")
        d = header["files"]
        for part in parts[:-1]:
            d = d.setdefault(part, {}).setdefault("files", {})
        return d, parts[-1]

    for p in files:
        rel = os.path.relpath(p, src_dir).replace("\\", "/")
        parent, name = node_for(rel)
        size = os.path.getsize(p)
        is_unpacked = rel.startswith(unpack_prefix + "/")
        entry = {"size": size}
        if is_unpacked:
            entry["unpacked"] = True
        parent[name] = entry
        order.append((rel, p, is_unpacked, size))

    cursor = 0
    for rel, p, is_unpacked, size in order:
        if is_unpacked:
            continue
        parts = rel.split("/")
        d = header["files"]
        for part in parts[:-1]:
            d = d[part]["files"]
        d[parts[-1]]["offset"] = str(cursor)
        cursor += size

    header_json = json.dumps(header, separators=(",", ":")).encode()
    json_len = len(header_json)
    pad = (-json_len) % 4
    pickle_total = 8 + json_len + pad
    base = 8 + pickle_total

    out_unpacked = out_path + ".unpacked"
    if os.path.exists(out_unpacked):
        shutil.rmtree(out_unpacked)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<IIII", 4, pickle_total, 4 + json_len + pad, json_len))
        f.write(header_json)
        f.write(b"\0" * pad)
        for rel, p, is_unpacked, size in order:
            if is_unpacked:
                d = os.path.join(out_unpacked, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(p, d)
                continue
            with open(p, "rb") as sf:
                f.write(sf.read())


PATCH_COUNTS = {
    "connecting gate (launch)": (2,),
    "migrate java version": (0, 1),   # absent on pristine and on fresh patches
}


def patch_js_source(code):
    applied, skipped = [], []
    for name, anchor, replacement, marker in JS_PATCHES:
        if marker in code:
            skipped.append(name)
            continue
        n = code.count(anchor)
        expected = PATCH_COUNTS.get(name, (1,))
        if n not in expected:
            fail(f"launcher bundle anchor '{name}' found {n}x (expected {'/'.join(map(str, expected))}). "
                 f"Unsupported CheatBreaker version.")
        code = code.replace(anchor, replacement)
        applied.append(name)
    return code, applied, skipped


# ---------------------------------------------------------------- step: launcher
def patch_launcher():
    show("Patching launcher...")
    asar = os.path.join(RESOURCES, "app.asar")
    unpacked_dir = asar + ".unpacked"
    if not os.path.exists(asar):
        fail(f"CheatBreaker launcher not found at {INSTALL_DIR}")

    # already patched: skip all I/O (the asar and app.asar.unpacked are in place)
    try:
        header, base, blob = read_asar(asar)
    except Exception as e:
        fail(f"app.asar is unreadable/corrupted ({e.__class__.__name__}) - reinstall CheatBreaker")
    js_entry = _find_renderer_entry(header)
    if js_entry is not None:
        off, size = js_entry
        js_blob = blob[off:off + size]
        # skip only when EVERY patch marker is present (a partially patched
        # install must still receive the missing patches)
        if all(marker.encode() in js_blob for _, _, _, marker in JS_PATCHES):
            show("Patching launcher OK (already patched)")
            return

    backup = asar + ".ORIGINAL"
    if not os.path.exists(backup):
        shutil.copy2(asar, backup)

    tmp = tempfile.mkdtemp(prefix="cia_patcher_")
    try:
        unpacked = extract_asar(header, base, blob, tmp)
        missing = [rel for rel in unpacked
                   if not os.path.exists(os.path.join(unpacked_dir, rel))]
        if missing:
            fail(f"app.asar.unpacked is incomplete ({len(missing)} files missing) - reinstall CheatBreaker")
        if unpacked:
            restore_unpacked(unpacked_dir, tmp, unpacked)

        js_path = _find_renderer_file(tmp)
        if not js_path:
            fail("renderer bundle not found - expected CheatBreaker 2026.9.1.")

        with open(js_path, "rb") as f:
            code = f.read().decode("utf-8", errors="ignore")
        code, applied, _ = patch_js_source(code)
        with open(js_path, "w", encoding="utf-8", newline="") as f:
            f.write(code)
        _node_syntax_gate(js_path)
        show(f"Patching launcher... {len(applied)} patches")

        tmp_asar = asar + ".tmp"
        pack_asar(tmp, tmp_asar, UNPACK_PREFIX)
        _replace_with_retry(tmp_asar, asar)
        # app.asar.unpacked was rebuilt next to the tmp asar by pack_asar's unpacked copy
        new_unpacked = tmp_asar + ".unpacked"
        if os.path.isdir(new_unpacked):
            for attempt in range(5):
                try:
                    if os.path.isdir(unpacked_dir):
                        shutil.rmtree(unpacked_dir)
                    os.replace(new_unpacked, unpacked_dir)
                    break
                except PermissionError:
                    if attempt == 4:
                        fail("app.asar.unpacked is locked - close CheatBreaker and rerun")
                    time.sleep(1)
        show("Patching launcher OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_renderer_entry(header):
    """(offset, size) of js/app.<hash>.js in the asar header, or None."""
    js = header.get("files", {}).get("js", {}).get("files", {})
    for name, entry in js.items():
        if re.fullmatch(r"app\.[0-9a-f]+\.js", name) and not entry.get("unpacked"):
            return int(entry["offset"]), entry["size"]
    return None


def _find_renderer_file(tmp):
    js_dir = os.path.join(tmp, "js")
    for root, _, files in os.walk(js_dir if os.path.isdir(js_dir) else tmp):
        for f in files:
            if re.fullmatch(r"app\.[0-9a-f]+\.js", f):
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    if b"Running Device Code Auth Protocol" in fh.read():
                        return p
    return None


def _node_syntax_gate(js_path):
    """Rule: node --check (ESM) the patched bundle when node is available."""
    node = shutil.which("node")
    if not node:
        return
    mjs = js_path + ".check.mjs"
    shutil.copy2(js_path, mjs)
    r = subprocess.run([node, "--check", mjs], capture_output=True, text=True)
    os.remove(mjs)
    if r.returncode != 0:
        fail("patched renderer bundle failed the syntax gate - aborting (no changes kept)")


def _replace_with_retry(src, dst):
    for attempt in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 4:
                fail(f"{dst} is locked (antivirus?) - close CheatBreaker and rerun")
            time.sleep(1)


# ---------------------------------------------------------------- step: game client
def patch_client(embedded):
    show("Patching game client...")
    if not embedded:
        fail("internal error: embedded class data missing from this build")
    if not os.path.isdir(CLIENTS_DIR):
        show("Patching game client... SKIPPED (launch the game once, then run cia patcher again)")
        return
    done, skipped = [], []
    for ver, spec in sorted(embedded.items()):
        jar = os.path.join(CLIENTS_DIR, ver, ver + ".patch")
        if not os.path.exists(jar):
            continue
        cls = spec["class"]
        try:
            with zipfile.ZipFile(jar) as z:
                current = z.read(cls)
        except KeyError:
            skipped.append(f"{ver} (no CB client class - vanilla jar, fine)")
            continue
        if hashlib.sha256(current).hexdigest() != spec["original_sha256"]:
            skipped.append(f"{ver} (unsupported client build)")
            continue
            backup = jar + ".ORIGINAL"
            if not os.path.exists(backup):
                shutil.copy2(jar, backup)
            patched = base64.b64decode(spec["patched_b64"])
            tmp = jar + ".tmp"
            with zipfile.ZipFile(jar) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = patched if item.filename == cls else zin.read(item.filename)
                    zout.writestr(item, data)
            for attempt in range(5):
                try:
                    os.replace(tmp, jar)
                    break
                except PermissionError:
                    if attempt == 4:
                        fail(f"{ver}.patch is locked by another process")
                    time.sleep(1)
            done.append(ver)
    if skipped:
        show(f"Patching game client... skipped: {'; '.join(skipped)}")
    if done:
        show(f"Patching game client OK ({', '.join(done)})")
    elif not skipped:
        show("Patching game client OK (already patched)")


# ---------------------------------------------------------------- step: account
def add_account(name):
    show(f'Adding account "{name}"...')
    hexs, uuid = offline_uuid(name)
    local_id = "offline" + hexs
    store = {"activeAccountLocalId": "", "accounts": {}}
    if os.path.exists(ACCOUNTS):
        try:
            with open(ACCOUNTS, encoding="utf-8-sig") as f:
                store = json.load(f)
        except Exception as e:
            fail(f"account file unreadable ({e.__class__.__name__}) - fix or rename "
                 f"{ACCOUNTS} manually, your premium accounts would be lost otherwise")
    if not isinstance(store, dict):
        fail(f"account file has an unexpected format - fix or rename {ACCOUNTS} manually")
    store.setdefault("accounts", {})
    store["accounts"][local_id] = {
        "accessToken": "0",
        "accessTokenExpiresAt": "2099-01-01T00:00:00.000Z",
        "refreshToken": "",
        "localId": local_id,
        "minecraftProfile": {"id": hexs, "name": name},
        "type": "Xbox",
    }
    store["activeAccountLocalId"] = local_id
    os.makedirs(os.path.dirname(ACCOUNTS), exist_ok=True)
    tmp = ACCOUNTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    _replace_with_retry(tmp, ACCOUNTS)
    show(f'Adding account "{name}" OK')


# ---------------------------------------------------------------- self-update
def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def check_update():
    """Abort on a newer published release: download it, swap this exe, relaunch."""
    show("Checking for updates...")
    if not getattr(sys, "frozen", False):
        show("Checking for updates OK (source run)")
        return
    # a running exe can be renamed but not deleted: the .old backup left by the
    # previous self-update is removed here, once nothing executes from it
    try:
        if os.path.exists(sys.executable + ".old"):
            os.remove(sys.executable + ".old")
    except PermissionError:
        pass
    try:
        req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "cia-patcher"})
        with urllib.request.urlopen(req, timeout=5) as r:
            info = json.load(r)
        remote = str(info.get("version", "")).strip()
        url = str(info.get("url", "")).strip()
        if not remote or not url or _version_tuple(remote) <= _version_tuple(PATCHER_VERSION):
            show("Checking for updates OK")
            return
        exe = os.path.abspath(sys.executable)
        new = exe + ".new"
        show(f"Updating to v{remote}...")
        req = urllib.request.Request(url, headers={"User-Agent": "cia-patcher"})
        with urllib.request.urlopen(req, timeout=30) as r, open(new, "wb") as f:
            shutil.copyfileobj(r, f)
        bak = exe + ".old"
        if os.path.exists(bak):
            os.remove(bak)
        os.rename(exe, bak)
        try:
            os.replace(new, exe)
        except Exception:
            os.rename(bak, exe)   # rollback: keep the current version working
            raise
        # the .old backup is deleted on the next startup (a running exe
        # cannot be deleted on Windows)
        show(f"Updating to v{remote} OK")
        # strip PyInstaller parent markers: the relaunched exe must behave like a
        # fresh external launch, not validate a parent that is about to exit
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI")}
        subprocess.Popen([exe], env=env,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        time.sleep(1)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        newline()
        show(f"Checking for updates... update failed ({e.__class__.__name__}), continuing with v{PATCHER_VERSION}")


# ---------------------------------------------------------------- step: start the game
def start_game():
    show("Starting CheatBreaker...")
    exe = os.path.join(INSTALL_DIR, "CheatBreaker.exe")
    if not os.path.exists(exe):
        fail(f"CheatBreaker not found at {INSTALL_DIR}")
    subprocess.Popen([exe], cwd=INSTALL_DIR,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    show("Starting CheatBreaker OK")


# ---------------------------------------------------------------- main
def main():
    if os.name != "nt":
        fail("Windows only - CheatBreaker is a Windows application")
    if not os.environ.get("LOCALAPPDATA") or not os.environ.get("APPDATA"):
        fail("LOCALAPPDATA/APPDATA environment variables are missing - run from a normal user session")
    print(HEADER)

    try:
        check_update()

        show("Closing CheatBreaker...")
        close_instances()
        show("Closing CheatBreaker OK")

        show("Checking installation...")
        if not os.path.exists(os.path.join(INSTALL_DIR, "CheatBreaker.exe")):
            fail(f"CheatBreaker not found at {INSTALL_DIR}")
        show("Checking installation OK")

        name = ask_nickname()

        patch_launcher()

        patch_client(load_embedded())

        add_account(name)

        start_game()
    except KeyboardInterrupt:
        fail("cancelled")

    print("\nDone. Have fun.")


if __name__ == "__main__":
    main()
