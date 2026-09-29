"""Prepare genuine, pinned CheatBreaker clients before enabling offline launch."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

PACKAGES = {
    '1.8.9': {
        'url': 'https://r2.cheatbreaker.net/Game/master/1078d1cbf325139d782cee29b28978db.zip',
        'sha256': '08a4420b49d1957b3aa378f8a77e5dd5d6df519b2ada51c42c537fc45ad2f462',
        'jar': '0624999e135464d65536fd424ad7003a2c8e1cfcbbf45cbd42729fbebe5b357d',
        'metadata': '6195113edb60bda0feee8b7d9f1a96085884e599243a3405177e00c3259a881c',
    },
    '1.7.10': {
        'url': 'https://r2.cheatbreaker.net/Game/master/d8d38d96f8c036a2da9a0bed7a2b56f7.zip',
        'sha256': '26316a1e5a6660a553a1007b001cc43d01e089f970001280ed74aa86bbd2c26c',
        'jar': '281a2f1c52cb508fd3bef678359e1587add87349366b43d049f25820cfbf97c2',
        'metadata': '07d67d1f9aceb56d61988069e3b872bed088d796e993398f9761496931e3c747',
    },
}
JRE_URL = 'https://r2.cheatbreaker.net/jre/Windows/25u36/amd64/jre.zip'
JRE_SHA256 = '72d757db849166c0f61dc250337fef556e655458cf2f3c04174eafb277575f22'
RECEIPT = '.cia-client.json'
REVISION = '1.1.8'


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def download(url, target, sha256):
    # The official CDN requires a product User-Agent.
    request = urllib.request.Request(url, headers={'User-Agent': 'CheatBreaker/2026.9.1'})
    with urllib.request.urlopen(request, timeout=60) as response, open(target, 'wb') as stream:
        shutil.copyfileobj(response, stream)
    if digest(target) != sha256:
        raise ValueError('Download checksum mismatch: ' + url)


def ready(directory, version):
    directory = Path(directory)
    try:
        state = json.loads((directory / RECEIPT).read_text(encoding='utf-8'))
        return (state['revision'] == REVISION and state['version'] == version
                and state['package'] == PACKAGES[version]['sha256']
                and state['jar'] == digest(directory / (version + '.patch'))
                and state['metadata'] == PACKAGES[version]['metadata']
                and state['metadata'] == digest(directory / (version + '.json')))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def ensure_java(roaming, show):
    roaming = Path(roaming)
    jres = roaming / 'CheatBreaker/jres'
    # Reuse the launcher's Java 25 when present, without depending on system Java.
    for candidate in sorted(jres.glob('*/bin/java.exe')):
        result = subprocess.run([str(candidate), '-version'], capture_output=True,
                                text=True, errors='replace', timeout=20)
        if result.returncode == 0 and 'version "25' in result.stderr:
            return str(candidate)
    show('Downloading CheatBreaker Java 25...')
    jres.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cia-runtime-', dir=jres) as temporary:
        temporary = Path(temporary)
        archive = temporary / 'jre.zip'
        download(JRE_URL, archive, JRE_SHA256)
        extracted = temporary / 'runtime'
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                relative = Path(entry.filename)
                if relative.is_absolute() or '..' in relative.parts or ':' in entry.filename:
                    raise ValueError('Unsafe runtime archive path')
            package.extractall(extracted)
        java = extracted / 'bin/java.exe'
        result = subprocess.run([str(java), '-version'], capture_output=True,
                                text=True, errors='replace', timeout=20)
        if result.returncode or 'version "25' not in result.stderr:
            raise ValueError('Downloaded Java runtime could not start')
        slot = hashlib.md5((extracted / 'bin/javaw.exe').read_bytes()).hexdigest()[:16]
        target = jres / slot
        if target.exists():
            # Keep an existing incomplete runtime intact for recovery.
            target = Path(tempfile.mkdtemp(prefix=slot + '-cia-', dir=jres))
            target.rmdir()  # empty directory created immediately above
        os.replace(extracted, target)
    settings = roaming / 'CheatBreaker/launcher/settings.json'
    state = json.loads(settings.read_text(encoding='utf-8-sig')) if settings.exists() else {}
    state.setdefault('jre_installs', {})[target.name] = {
        'hash': target.name, 'javaVersion': 25, 'jreType': '25u36',
        'path': str(target / 'bin/javaw.exe'),
    }
    atomic_write(settings, (json.dumps(state, indent=2) + '\n').encode())
    return str(target / 'bin/java.exe')


def install_transaction(writes, backup_root):
    """Snapshot all destinations before the first write; restore on failure."""
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix='clients-', dir=backup_root))
    previous = []
    for index, (destination, data) in enumerate(writes):
        destination = Path(destination)
        old = destination.read_bytes() if destination.exists() else None
        previous.append((destination, old))
        if old is not None:
            (session / str(index)).write_bytes(old)
    (session / 'manifest.json').write_text(json.dumps([
        {'path': str(path), 'backup': str(index) if old is not None else None}
        for index, (path, old) in enumerate(previous)], indent=2), encoding='utf-8')
    try:
        for destination, data in writes:
            atomic_write(destination, data)
    except Exception:
        for destination, old in reversed(previous):
            if old is None:
                destination.unlink(missing_ok=True)
            else:
                atomic_write(destination, old)
        raise


def prepare(clients, roaming, patch, show):
    """Download and patch in staging; publish both clients only after success."""
    clients = Path(clients)
    needed = [version for version in PACKAGES if not ready(clients / version, version)]
    if not needed:
        show('CheatBreaker clients OK (verified 1.7.10 and 1.8.9)')
        return
    java = ensure_java(roaming, show)
    with tempfile.TemporaryDirectory(prefix='cia-clients-') as temporary:
        stage = Path(temporary)
        originals = {}
        for version in needed:
            spec = PACKAGES[version]
            show('Downloading genuine CheatBreaker ' + version + '...')
            archive = stage / (version + '.zip')
            download(spec['url'], archive, spec['sha256'])
            directory = stage / 'versions' / version
            directory.mkdir(parents=True)
            with zipfile.ZipFile(archive) as package:
                for suffix, key in [('.patch', 'jar'), ('.json', 'metadata')]:
                    name = version + suffix
                    data = package.read('versions/' + version + '/' + name)
                    if hashlib.sha256(data).hexdigest() != spec[key]:
                        raise ValueError('Unexpected CheatBreaker package contents: ' + version)
                    (directory / name).write_bytes(data)
                    originals[(version, suffix)] = data
            metadata = json.loads((directory / (version + '.json')).read_text())
            with zipfile.ZipFile(directory / (version + '.patch')) as jar:
                if metadata['mainClass'] != 'Start' or 'Start.class' not in jar.namelist():
                    raise ValueError('Package is not a CheatBreaker client: ' + version)
        patch(java, str(stage / 'versions'))
        writes = []
        for version in needed:
            directory = stage / 'versions' / version
            destination = clients / version
            for suffix in ('.patch', '.json'):
                name = version + suffix
                writes.append((destination / (name + '.ORIGINAL'), originals[(version, suffix)]))
                writes.append((destination / name, (directory / name).read_bytes()))
            receipt = {'revision': REVISION, 'version': version,
                       'package': PACKAGES[version]['sha256'],
                       'jar': digest(directory / (version + '.patch')),
                       'metadata': digest(directory / (version + '.json'))}
            writes.append((destination / RECEIPT, (json.dumps(receipt, indent=2) + '\n').encode()))
        install_transaction(writes, Path(roaming) / 'CheatBreaker/patch-backups')
    for version in PACKAGES:
        if not ready(clients / version, version):
            raise ValueError('CheatBreaker client validation failed: ' + version)
    show('CheatBreaker clients OK (1.7.10 and 1.8.9)')
