import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cia_unpatcher as u


def asar(path, patched=False):
    content = b'"CB Offline: test"' if patched else b'"official renderer"'
    native = b"native-original"
    header = {"files": {
        "js": {"files": {"app.test.js": {"size": len(content), "offset": "0"}}},
        "native.node": {"size": len(native), "unpacked": True,
                        "integrity": {"algorithm": "SHA256", "hash": hashlib.sha256(native).hexdigest()}}
    }}
    data = json.dumps(header).encode()
    total = 8 + ((len(data) + 3) & ~3)
    path.write_bytes(struct.pack("<IIII", 4, total, total - 4, len(data))
                     + data + b"\0" * (-len(data) % 4) + content)


def jar(path, major=52, payload=b"original"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("IlIlIlIlIlIl.class", b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, major) + payload)


class UnpatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cia_unpatch_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.res = self.root / "resources"
        self.res.mkdir()
        asar(self.res / "app.asar", True)
        asar(self.res / "app.asar.ORIGINAL")
        native = self.res / "app.asar.unpacked/native.node"
        native.parent.mkdir()
        native.write_bytes(b"native-original")
        self.versions = self.root / "versions"
        version = self.versions / "1.8.9"
        version.mkdir(parents=True)
        self.client = version / "1.8.9.patch"
        jar(self.client, payload=b"modified")
        jar(Path(str(self.client) + ".ORIGINAL"))
        self.metadata = version / "1.8.9.json"
        self.metadata.write_text('{"mainClass":"Start"}')
        self.account = self.root / "accounts.json"
        self.offline_id = "offline" + "a" * 32
        self.premium = {"accessToken": "test-only", "refreshToken": "test-only", "extra": [1, 2]}
        self.store = {"extraRoot": True, "activeAccountLocalId": "premium", "accounts": {
            "premium": self.premium,
            "unknown": {"accessToken": "", "keepMe": True},
            self.offline_id: {"localId": self.offline_id, "accessToken": "0", "refreshToken": ""}}}
        self.account.write_text(json.dumps(self.store))
        self.marker = self.root / "offline_username.txt"
        self.marker.write_text("test")

    def plan(self):
        return u.build_plan(self.res, self.versions, self.account, self.marker)

    def test_restore_preserves_accounts_backups_and_second_run(self):
        actions, _ = self.plan()
        snapshot = u.apply_plan(actions, self.root / "backups")
        self.assertIsNotNone(snapshot)
        self.assertFalse(u.launcher_patched(self.res / "app.asar"))
        self.assertEqual(self.client.read_bytes(), Path(str(self.client) + ".ORIGINAL").read_bytes())
        result = json.loads(self.account.read_text())
        self.assertEqual(result["accounts"]["premium"], self.premium)
        self.assertEqual(result["accounts"]["unknown"], self.store["accounts"]["unknown"])
        self.assertEqual(result["activeAccountLocalId"], "premium")
        self.assertTrue(result["extraRoot"])
        self.assertNotIn(self.offline_id, result["accounts"])
        self.assertFalse(self.marker.exists())
        self.assertTrue((self.res / "app.asar.ORIGINAL").exists())
        self.assertEqual(self.plan()[0], [])

    def test_missing_client_backup_sets_aside_jar_and_metadata(self):
        Path(str(self.client) + ".ORIGINAL").unlink()
        actions, notices = self.plan()
        self.assertTrue(any("re-download" in n for n in notices))
        snapshot = u.apply_plan(actions, self.root / "backups")
        self.assertFalse(self.client.exists())
        self.assertFalse(self.metadata.exists())
        self.assertTrue(list(snapshot.glob("*_1.8.9.patch")))

    def test_damaged_old_backup_is_not_restored(self):
        jar(Path(str(self.client) + ".ORIGINAL"), major=48)
        actions, notices = self.plan()
        action = next(a for a in actions if a["target"] == self.client)
        self.assertNotIn("source", action)
        self.assertTrue(notices)

    def test_missing_launcher_backup_fails_without_changes(self):
        (self.res / "app.asar.ORIGINAL").unlink()
        before = self.account.read_bytes()
        with self.assertRaisesRegex(ValueError, "ORIGINAL is missing"):
            self.plan()
        self.assertEqual(self.account.read_bytes(), before)
        self.assertTrue(u.launcher_patched(self.res / "app.asar"))

    def test_native_integrity_failure_stops_preflight(self):
        (self.res / "app.asar.unpacked/native.node").write_bytes(b"native-modified")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.plan()

    def test_active_offline_account_selects_existing_premium(self):
        self.store["activeAccountLocalId"] = self.offline_id
        self.account.write_text(json.dumps(self.store))
        action = next(a for a in self.plan()[0] if a["target"] == self.account)
        self.assertEqual(json.loads(action["data"])["activeAccountLocalId"], "premium")

    def test_failure_rolls_back_all_applied_changes(self):
        actions, _ = self.plan()
        before = {a["target"]: a["target"].read_bytes() for a in actions}
        original_replace = u.replace_file
        failed = False

        def fail_once(source, target):
            nonlocal failed
            if target == self.account and not failed:
                failed = True
                raise PermissionError("simulated locked account file")
            return original_replace(source, target)

        with patch.object(u, "replace_file", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                u.apply_plan(actions, self.root / "backups")
        for target, data in before.items():
            self.assertEqual(target.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
