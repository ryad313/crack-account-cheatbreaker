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
from pathlib import Path
import cia_client

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

LOG_FILE = None


def log(msg):
    """Persist every step next to the exe so failures stay readable."""
    global LOG_FILE
    if LOG_FILE is None:
        base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        LOG_FILE = os.path.join(base, "cia_patcher.log")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass

# self-update: pinned to the latest.json published in the patcher repository
PATCHER_VERSION = "1.1.8"
UPDATE_URL = ("https://raw.githubusercontent.com/ryad313/crack-account-cheatbreaker/main/latest.json")

# ---------------------------------------------------------------- JS patches (renderer bundle)
# Each patch: unique anchor -> replacement, marker proves it is already applied.
JS_PATCHES = [
    (
        # Vanilla metadata includes placeholders absent from CB's custom version
        # files. Passing ${user_properties} literally makes Gson fail at startup.
        "vanilla launch placeholders",
        '"${assets_root}":l},f=function(e,t){',
        '"${assets_root}":l,"${user_properties}":"{}",'
        '"${version_name}":r.id||n.id||t.version.number,'
        '"${assets_index_name}":(r.assetIndex&&r.assetIndex.id)||'
        '(n.assetIndex&&n.assetIndex.id)||r.assets||n.assets||t.version.number,'
        '"${version_type}":r.type||n.type||"release"},f=function(e,t){',
        '"${user_properties}":"{}"',
    ),
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
        # convert Mojang single-artifact natives classifiers to the CB files-map
        # format, otherwise getNatives crashes on Object.entries(undefined)
        '_vj.libraries.forEach(function(_l){'
        'var _c=_l.downloads&&_l.downloads.classifiers;'
        'if(!_c)return;'
        'Object.keys(_c).forEach(function(_k){'
        'var _e=_c[_k];'
        'if(_e&&!_e.files)_c[_k]={sha1:_e.sha1,size:_e.size,url:_e.url,'
        'files:{natives:{url:_e.url,sha1:_e.sha1,size:_e.size}}}})});'
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
        # universal bootstrap: with any offline account present, guarantee the
        # version json (natives classifiers converted to the CB files-map format)
        # and the client jar exist BEFORE launch, whatever the ContinueLaunch
        # source (real server response or synthesized fallback)
        "client bootstrap",
        'e.n=8,ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        'e.n=8,na.accounts.some(function(e){return"0"===e.accessToken})?'
        '(async function(){try{var _pj=(0,q.join)(i,"versions",t,"".concat(t,".json")),_pp=(0,q.join)(i,"versions",t,"".concat(t,".patch"));if(!(0,Z.existsSync)(_pp)||!(0,Z.existsSync)(_pj)){vr.log("CB Offline: bootstrapping "+t);var _mf=await(await fetch("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")).json(),_ent=_mf.versions.find(function(_v){return _v.id===(t)});if(!_ent)throw new Error("version not found in Mojang manifest");var _vj=await(await fetch(_ent.url)).json();_vj.libraries.forEach(function(_l){var _c=_l.downloads&&_l.downloads.classifiers;if(!_c)return;Object.keys(_c).forEach(function(_k){var _e=_c[_k];if(_e&&!_e.files)_c[_k]={sha1:_e.sha1,size:_e.size,url:_e.url,files:{natives:{url:_e.url,sha1:_e.sha1,size:_e.size}}}})});await H.mkdir((0,q.join)(i,"versions",t),{recursive:!0}),await H.writeFile(_pj,JSON.stringify(_vj),"utf-8");if(!(0,Z.existsSync)(_pp)){var _cl=await fetch(_vj.downloads.client.url);await H.writeFile(_pp,Buffer.from(await _cl.arrayBuffer()));return !0;}}else{var _ex=JSON.parse((0,Z.readFileSync)(_pj,"utf-8"));_ex.libraries.forEach(function(_l){var _c=_l.downloads&&_l.downloads.classifiers;if(!_c)return;Object.keys(_c).forEach(function(_k){var _e=_c[_k];if(_e&&!_e.files)_c[_k]={sha1:_e.sha1,size:_e.size,url:_e.url,files:{natives:{url:_e.url,sha1:_e.sha1,size:_e.size}}}})});await H.writeFile(_pj,JSON.stringify(_ex),"utf-8");return !0;}}catch(_e){vr.error("CB Offline: bootstrap failed: "+_e)}})():ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        'var _ex=JSON.parse((0,Z.readFileSync)(_pj,"utf-8"))',
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
        # v1.0.0/v1.1.0 installs skipped the md5 check without ensuring the files:
        # migrate their P7 to the universal bootstrap form
        "migrate jar ensure",
        'e.n=8,na.accounts.some(function(e){return"0"===e.accessToken})?'
        'Promise.resolve(!0):ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        'e.n=8,na.accounts.some(function(e){return"0"===e.accessToken})?'
        '(async function(){try{var _pj=(0,q.join)(i,"versions",t,"".concat(t,".json")),_pp=(0,q.join)(i,"versions",t,"".concat(t,".patch"));if(!(0,Z.existsSync)(_pp)||!(0,Z.existsSync)(_pj)){vr.log("CB Offline: bootstrapping "+t);var _mf=await(await fetch("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")).json(),_ent=_mf.versions.find(function(_v){return _v.id===(t)});if(!_ent)throw new Error("version not found in Mojang manifest");var _vj=await(await fetch(_ent.url)).json();_vj.libraries.forEach(function(_l){var _c=_l.downloads&&_l.downloads.classifiers;if(!_c)return;Object.keys(_c).forEach(function(_k){var _e=_c[_k];if(_e&&!_e.files)_c[_k]={sha1:_e.sha1,size:_e.size,url:_e.url,files:{natives:{url:_e.url,sha1:_e.sha1,size:_e.size}}}})});await H.mkdir((0,q.join)(i,"versions",t),{recursive:!0}),await H.writeFile(_pj,JSON.stringify(_vj),"utf-8");if(!(0,Z.existsSync)(_pp)){var _cl=await fetch(_vj.downloads.client.url);await H.writeFile(_pp,Buffer.from(await _cl.arrayBuffer()));return !0;}}else{var _ex=JSON.parse((0,Z.readFileSync)(_pj,"utf-8"));_ex.libraries.forEach(function(_l){var _c=_l.downloads&&_l.downloads.classifiers;if(!_c)return;Object.keys(_c).forEach(function(_k){var _e=_c[_k];if(_e&&!_e.files)_c[_k]={sha1:_e.sha1,size:_e.size,url:_e.url,files:{natives:{url:_e.url,sha1:_e.sha1,size:_e.size}}}})});await H.writeFile(_pj,JSON.stringify(_ex),"utf-8");return !0;}}catch(_e){vr.error("CB Offline: bootstrap failed: "+_e)}})():ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        'var _ex=JSON.parse((0,Z.readFileSync)(_pj,"utf-8"))',
    ),
    (
        # the CB server can force-close the launcher (update packet -> download
        # Setup -> app.exit(0)), wiping the patched install mid-launch. Blocked
        # while any offline account exists.
        "forced update block",
        "case 18:return P=n.data,e.n=19,zn(P.launcher,P.launcherVersion);case 19:_.app.exit(0);",
        'case 18:if(na.accounts.some(function(e){return"0"===e.accessToken})){'
        'vr.log("CB Offline: forced launcher update blocked");return e.a(3,21)}'
        "P=n.data,zn(P.launcher,P.launcherVersion);case 19:_.app.exit(0);",
        "forced launcher update blocked",
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


# Replace legacy vanilla fallbacks exactly before applying the current patches.
# Keeping exact previous replacements makes migration fail on unknown bundles.
LEGACY_BOOTSTRAP = [p for p in JS_PATCHES if p[0] in (
    "launch fallback", "client bootstrap", "migrate java version", "migrate jar ensure")]
JS_PATCHES = [p for p in JS_PATCHES if p not in LEGACY_BOOTSTRAP]
OFFLINE_ACTIVE = 'na.accounts.some(function(e){return e.localId===na.profileId&&"0"===e.accessToken})'
CLIENT_CHECK = (
    'function(_dd,_ver){'
    'if(!["1.7.10","1.8.9"].includes(_ver))throw new Error("Unsupported CheatBreaker version");'
    'var _dir=(0,q.join)(_dd,"versions",_ver),'
    '_receipt=JSON.parse((0,Z.readFileSync)((0,q.join)(_dir,".cia-client.json"),"utf-8")),'
    '_meta=(0,Z.readFileSync)((0,q.join)(_dir,_ver+".json")),'
    '_jar=(0,Z.readFileSync)((0,q.join)(_dir,_ver+".patch"));'
    'if(_receipt.revision!=="1.1.8"||_receipt.version!==_ver||'
    'JSON.parse(_meta.toString("utf-8")).mainClass!=="Start"||'
    'G.createHash("sha256").update(_jar).digest("hex")!==_receipt.jar||'
    'G.createHash("sha256").update(_meta).digest("hex")!==_receipt.metadata)'
    'throw new Error("CheatBreaker client changed; run cia patcher again.");'
    'return !0}'
)
JS_PATCHES.extend([
    (
        'prepared client fallback', LEGACY_BOOTSTRAP[0][1],
        'Hr.continueLaunchTimeoutId=setTimeout(function(){Hr.clearContinueLaunchTimeout(),'
        'Hr.continueLaunchResolver&&(function(){var _res=Hr.continueLaunchResolver;'
        'Hr.continueLaunchResolver=null;'
        'if(!(' + OFFLINE_ACTIVE + ')){_res(null);return}'
        '(async function(){try{var _ver=t,_dd=await Wt.get("downloads_dir");'
        '(' + CLIENT_CHECK + ')(_dd,_ver);'
        'vr.log("CB Offline: using prepared CheatBreaker client "+_ver);'
        '_res({branch:"offline",client:"",hash:"offline",version:_ver,javaVersion:"25"})'
        '}catch(_e){vr.error("CB Offline: genuine client unavailable: "+_e);'
        'Ce({title:"CheatBreaker client missing",message:"Run cia patcher again to repair the CheatBreaker client.",type:"error",duration:1e4});_res(null)}})()})()},1e4)',
        'CB Offline: using prepared CheatBreaker client ',
    ),
    (
        'prepared client check', LEGACY_BOOTSTRAP[1][1],
        'e.n=8,' + OFFLINE_ACTIVE + '?Promise.resolve().then(function(){'
        'vr.log("CB Offline: verifying prepared CheatBreaker client "+t);'
        'return (' + CLIENT_CHECK + ')(i,t)}):ke((0,q.join)(i,"versions",t,"".concat(t,".patch")),o.hash)',
        'CB Offline: verifying prepared CheatBreaker client ',
    ),
])

# ---------------------------------------------------------------- patched Java title-screen classes
# Embedded pre-compiled (Javassist): every isAuthed() call replaced with `true`.
# original_sha256 pins the supported client build; a mismatch means an unsupported
# CheatBreaker version and the jar is left untouched.
EMBEDDED_JSON = "embedded_classes.json"


def load_java_assets():
    """Extract the embedded javassist.jar + PatchGeneric classes to a temp dir."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in [os.path.join(here, "embedded_java.json"),
                 os.path.join(os.getcwd(), "embedded_java.json"),
                 os.path.join(os.path.dirname(sys.executable), "embedded_java.json")]:
        if os.path.exists(cand):
            assets = json.load(open(cand))
            break
    else:
        return None, None
    d = tempfile.mkdtemp(prefix="cia_java_")
    for name, b64 in assets.items():
        out = os.path.join(d, name)
        with open(out, "wb") as f:
            f.write(base64.b64decode(b64))
    jar = os.path.join(d, "javassist.jar")
    classes_dir = os.path.join(d, "pgclasses")
    os.makedirs(classes_dir, exist_ok=True)
    for name in list(assets):
        if name.endswith(".class"):
            shutil.move(os.path.join(d, name), os.path.join(classes_dir, name))
    return jar, classes_dir


# ---------------------------------------------------------------- output helpers
# All steps scroll on a single console line: each show() overwrites the previous text.
# When stdout is not a tty (piped/redirected), fall back to plain newline prints.
_line = {"len": 0}


def show(text):
    log(text)
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
    log("ERROR: " + msg)
    try:
        if sys.stdout.isatty():
            input("Press Enter to close...")
    except Exception:
        pass
    sys.exit(1)


# ---------------------------------------------------------------- step 1: kill running instances
def close_instances():
    from cia_unpatcher import close_instances as close_cb
    close_cb(Path(INSTALL_DIR), Path(configured_clients()).parent)


def configured_clients():
    settings = Path(os.environ["APPDATA"]) / "CheatBreaker/launcher/settings.json"
    if settings.exists():
        with settings.open(encoding="utf-8-sig") as stream:
            downloads = json.load(stream).get("downloads_dir")
        if downloads:
            return os.path.join(downloads, "versions")
    return CLIENTS_DIR


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
    "client bootstrap": (0, 1),          # 0 on installs already migrated
    "migrate java version": (0, 1),
    "migrate jar ensure": (0, 1),
}

# write-file-atomic (utilise par electron-settings): rename atomique sans retry
# -> EPERM recurrent sur Windows quand AV/indexer/2e instance tient le fichier.
WFA_PATCHES = [
    (
        "atomic rename retry (async)",
        "    await promisify(fs.rename)(tmpfile, truename)",
        "    { let _ra = 0; for (;;) { try { await promisify(fs.rename)(tmpfile, truename); break; }"
        " catch (_e) { if ((_e.code !== 'EPERM' && _e.code !== 'EACCES') || ++_ra > 4) throw _e;"
        " await new Promise(_r => setTimeout(_r, 150 * _ra)); } } }",
        "++_ra > 4",
    ),
    (
        "atomic rename retry (sync)",
        "    fs.renameSync(tmpfile, filename)",
        "    { let _rs = 0; for (;;) { try { fs.renameSync(tmpfile, filename); break; }"
        " catch (_e) { if ((_e.code !== 'EPERM' && _e.code !== 'EACCES') || ++_rs > 4) throw _e;"
        " const _d = Date.now(); while (Date.now() - _d < 150 * _rs); } } }",
        "++_rs > 4",
    ),
]


def patch_js_source(code):
    applied, skipped = [], []
    # Normalise v1.0-v1.1.7 paths back to their official anchors.
    code = code.replace(LEGACY_BOOTSTRAP[2][1], LEGACY_BOOTSTRAP[2][2])
    code = code.replace(LEGACY_BOOTSTRAP[3][1], LEGACY_BOOTSTRAP[1][1])
    for name, anchor, replacement, marker in LEGACY_BOOTSTRAP[:2]:
        code = code.replace(replacement, anchor)
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
        js_done = all(marker.encode() in js_blob for _, _, _, marker in JS_PATCHES)
        wfa_done = False
        try:
            w_entry = header["files"]["node_modules"]["files"]["write-file-atomic"]["files"]["index.js"]
            wfa_done = "++_ra > 4".encode() in blob[int(w_entry["offset"]): int(w_entry["offset"]) + w_entry["size"]]
        except KeyError:
            wfa_done = True  # pas de write-file-atomic dans ce bundle
        if js_done and wfa_done:
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

        orig_copy = js_path + ".orig.tmp"
        shutil.copy2(js_path, orig_copy)

        with open(js_path, "rb") as f:
            code = f.read().decode("utf-8", errors="ignore")
        code, applied, _ = patch_js_source(code)
        with open(js_path, "w", encoding="utf-8", newline="") as f:
            f.write(code)

        wfa = os.path.join(tmp, "node_modules", "write-file-atomic", "index.js")
        if os.path.exists(wfa):
            with open(wfa, encoding="utf-8") as f:
                wfa_code = f.read()
            wfa_ok = True
            for name, anchor, replacement, marker in WFA_PATCHES:
                if marker in wfa_code:
                    continue
                n = wfa_code.count(anchor)
                if n != 1:
                    wfa_ok = False
                    log(f"write-file-atomic anchor '{name}' found {n}x - skipping WFA patch")
                    break
                wfa_code = wfa_code.replace(anchor, replacement)
            if wfa_ok:
                with open(wfa, "w", encoding="utf-8", newline="") as f:
                    f.write(wfa_code)

        _node_syntax_gate(js_path, reference_path=orig_copy)
        if os.path.exists(wfa):
            if not _node_syntax_gate(wfa, fatal=False, label="write-file-atomic"):
                # restaure le wfa original: le launcher tourne sans le retry
                with zipfile.ZipFile(asar) as z:
                    with open(wfa, "wb") as f:
                        f.write(z.read("node_modules/write-file-atomic/index.js"))
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


def _node_syntax_check(node, path):
    """True when node --check (ESM copy) accepts the file."""
    mjs = path + ".check.mjs"
    shutil.copy2(path, mjs)
    r = subprocess.run([node, "--check", mjs], capture_output=True, text=True)
    os.remove(mjs)
    return r.returncode == 0


def _node_version(node):
    try:
        return subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    except Exception:
        return "?"


def _node_syntax_gate(js_path, reference_path=None, fatal=True, label="renderer"):
    """node --check the patched file. A reference (the unpatched original)
    makes the gate skip when node itself is too old for CB's syntax."""
    node = shutil.which("node")
    if not node:
        return True
    node_v = _node_version(node)
    log(f"syntax gate ({label}): node {node_v}")
    if reference_path and not _node_syntax_check(node, reference_path):
        log("syntax gate skipped: node cannot parse the original bundle either")
        return True
    if _node_syntax_check(node, js_path):
        return True
    # save the failing file next to the exe for diagnosis
    try:
        base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        saved = os.path.join(base, "patched_" + label + ".failed.mjs")
        shutil.copy2(js_path, saved)
    except OSError:
        saved = "(save failed)"
    mjs = js_path + ".check.mjs"
    shutil.copy2(js_path, mjs)
    r = subprocess.run([node, "--check", mjs], capture_output=True, text=True, errors="replace")
    err_first = ""
    for line in (r.stderr or "").splitlines():
        if "SyntaxError" in line:
            err_first = line.strip()
            break
    msg = f"node {node_v} rejected the patched {label}: {err_first or 'syntax error'} - saved: {saved}"
    if fatal:
        fail(msg)
    log("WARNING: " + msg)
    return False


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
def patch_client(java_exe, java_assets, clients_dir=None):
    clients_dir = clients_dir or CLIENTS_DIR
    show("Patching game client...")
    if not java_exe:
        raise ValueError("Java is unavailable for client preparation")
    if not os.path.isdir(clients_dir):
        raise ValueError("CheatBreaker clients are missing")

    javassist_jar, pg_dir = java_assets
    done, failed = [], []
    for ver in sorted(os.listdir(clients_dir)):
        jar = os.path.join(clients_dir, ver, ver + ".patch")
        if not os.path.isfile(jar):
            continue
        outdir = tempfile.mkdtemp(prefix="cia_pg_")
        cp = javassist_jar + os.pathsep + pg_dir
        r = subprocess.run([java_exe, "-cp", cp, "PatchGeneric", jar, outdir],
                           capture_output=True, text=True, errors="replace")
        log = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            tail = [l for l in log.splitlines() if l.strip()][-1:] or ["?"]
            failed.append(f"{ver}: {tail[0][:80]}")
            shutil.rmtree(outdir, ignore_errors=True)
            continue
        if "NO_CB_MOD:" in log:
            failed.append(f"{ver}: expected CheatBreaker, found vanilla")
            shutil.rmtree(outdir, ignore_errors=True)
            continue
        # injecter les classes patchees dans le jar
        patched = {}
        for root, dirs, files in os.walk(outdir):
            for f in files:
                if f.endswith(".class"):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, outdir).replace("\\", "/")
                    patched[rel] = open(full, "rb").read()
        if not os.path.exists(jar + ".ORIGINAL"):
            shutil.copy2(jar, jar + ".ORIGINAL")
        tmp = jar + ".tmp"
        with zipfile.ZipFile(jar) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            injected = 0
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename in patched:
                    data = patched[item.filename]
                    injected += 1
                zout.writestr(item, data)
            for rel, data in patched.items():
                if rel not in zin.namelist():
                    zout.writestr(rel, data)
                    injected += 1
        _replace_with_retry(tmp, jar)
        done.append(f"{ver} ({injected} classes)")
        shutil.rmtree(outdir, ignore_errors=True)
    if failed:
        fail("game client patch failed: " + " | ".join(failed))
    show("Patching game client OK (" + "; ".join(done) + ")")


def find_java_exe():
    candidates = [os.path.join(os.environ.get("APPDATA", ""), "CheatBreaker", "jre", "bin", "java.exe")]
    jres = os.path.join(os.environ.get("APPDATA", ""), "CheatBreaker", "jres")
    if os.path.isdir(jres):
        import glob as _g
        candidates += _g.glob(os.path.join(jres, "*", "bin", "java.exe"))
        candidates += _g.glob(os.path.join(jres, "*", "*", "bin", "java.exe"))
    w = shutil.which("java")
    if w:
        candidates.append(w)
    for c in candidates:
        if os.path.exists(c):
            return c
    return None




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
    if sys.argv[1:] == ["--version"]:
        print(f"cia patcher {PATCHER_VERSION}")
        return
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

        assets = load_java_assets()
        cia_client.prepare(configured_clients(), os.environ["APPDATA"],
                           lambda java, directory: patch_client(java, assets, directory), show)

        patch_launcher()

        add_account(name)

        start_game()
    except KeyboardInterrupt:
        fail("cancelled")
    except Exception as error:
        fail(str(error))

    print("\nDone. Have fun.")


if __name__ == "__main__":
    main()
