"""Exercise in-place updates and interruption recovery with tiny owned files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
sys.path.insert(0, str(ROOT / 'tools'))
import release_download
import release_update as update


def package(root, version, changed=b'old', platform='windows'):
    base = root / 'windows' if platform == 'linux' else root
    blobs = {'Darkwatch Darker Edition.exe': changed, 'Play Darkwatch.exe': b'play',
             'payload/runtime/darkwatch_xbe.exe': changed,
             'payload/setup_backend.py': changed, 'payload/python/python.exe': b'python',
             'payload/python/python312._pth': b'python312.zip\n.\n..\n',
             'payload/release_update.py': (ROOT / 'launcher/release_update.py').read_bytes(),
             'payload/release_download.py': b'# fixture download', 'payload/release_check.py': b'# fixture check'}
    if changed != b'old':
        blobs['payload/new-file.txt'] = changed
    else:
        blobs['payload/obsolete.txt'] = b'obsolete'
    files = {}
    for name, value in blobs.items():
        file = base / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
        files[name] = hashlib.sha256(value).hexdigest()
    (base / 'package-manifest.json').write_text(json.dumps(dict(version=version, complete=True, files=files)))
    if platform == 'linux':
        for name in update.WRAPPERS:
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(changed)
        (root / 'Darkwatch.sh').chmod(0o755)


class ReleaseUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'game'
        self.root.mkdir()
        for name in ('GameData/versions/save.bin', 'GameData/installation-location.json',
                     'GameData/hd.pack', 'GameData/spanish.bin', '.proton/user.reg', 'personal-note.txt',
                     'assets/My Xbox Disc.iso', 'assets/second.XISO', 'windows/assets/private.iso'):
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'preserve exactly')

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and update.STAGE not in p.parts}

    def prepare(self, platform='windows'):
        package(self.root, '0.6.1', platform=platform)
        before = self.snapshot()
        def download(current, selected, scratch, notify, cancel):
            cancel()
            package(scratch / 'new', '0.6.2', b'new', platform)
            return dict(version='0.6.2', directory=str(scratch / 'new'))
        with patch.object(release_download, 'prepare', side_effect=download):
            value = update.prepare(self.root, '0.6.1', platform)
        self.assertEqual(self.snapshot(), before)
        return value, before

    def test_apply_overwrites_owned_files_and_preserves_every_user_file(self):
        value, before = self.prepare()
        self.assertTrue(update.pending(self.root))
        self.assertEqual(update.apply(self.root), '0.6.2')
        self.assertFalse(update.pending(self.root))
        self.assertFalse(update.recover(self.root))
        self.assertEqual((self.root / 'payload/setup_backend.py').read_bytes(), b'new')
        self.assertFalse((self.root / 'payload/obsolete.txt').exists())
        for name, data in before.items():
            if name not in value['files']:
                self.assertEqual((self.root / name).read_bytes(), data)
        self.assertEqual(update.transaction(self.root)['phase'], 'committed')

    def test_every_interrupted_replacement_restores_original_package(self):
        value, before = self.prepare()
        total = sum(row['new'] is not None for row in value['files'].values())
        for stop in range(1, total + 1):
            with self.subTest(replacement=stop):
                update.write(self.root / update.STAGE / 'transaction.json', dict(value, phase='prepared'))
                copies = 0
                original = update.copy_atomic
                def interrupted(source, destination):
                    nonlocal copies
                    original(source, destination)
                    copies += 1
                    if copies == stop:
                        raise KeyboardInterrupt('simulated power interruption')
                with patch.object(update, 'copy_atomic', side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        update.apply(self.root)
                self.assertTrue(update.recover(self.root))
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(update.recover(self.root))

    def test_ordinary_failure_rolls_back_automatically(self):
        _, before = self.prepare()
        original = update.copy_atomic
        fired = False
        def failed(source, destination):
            nonlocal fired
            original(source, destination)
            if not fired:
                fired = True
                raise OSError('destination became unavailable')
        with patch.object(update, 'copy_atomic', side_effect=failed):
            with self.assertRaises(OSError):
                update.apply(self.root)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(update.transaction(self.root)['phase'], 'rolled_back')

    def test_interrupted_rollback_can_be_retried(self):
        _, before = self.prepare()
        original = update.write
        def stop_commit(path, value):
            if value.get('phase') == 'committed':
                raise KeyboardInterrupt()
            original(path, value)
        with patch.object(update, 'write', side_effect=stop_commit):
            with self.assertRaises(KeyboardInterrupt):
                update.apply(self.root)
        original_copy = update.copy_atomic
        def stop_restore(source, destination):
            original_copy(source, destination)
            raise KeyboardInterrupt()
        with patch.object(update, 'copy_atomic', side_effect=stop_restore):
            with self.assertRaises(KeyboardInterrupt):
                update.recover(self.root)
        self.assertTrue(update.recover(self.root))
        self.assertEqual(self.snapshot(), before)

    def test_tampered_stage_or_backup_is_rejected_before_writing(self):
        _, before = self.prepare()
        stage = self.root / update.STAGE
        path = stage / 'new/payload/setup_backend.py'
        original = path.read_bytes()
        path.write_bytes(b'wrong')
        with self.assertRaises(ValueError):
            update.apply(self.root)
        self.assertEqual(self.snapshot(), before)
        path.write_bytes(original)
        (stage / 'backup/payload/setup_backend.py').write_bytes(b'bad backup')
        with self.assertRaises(ValueError):
            update.apply(self.root)
        with self.assertRaises(ValueError):
            update.recover(self.root)
        self.assertEqual(self.snapshot(), before)

    def test_unmanaged_or_malformed_journal_cannot_delete_user_files(self):
        self.prepare()
        stage = self.root / update.STAGE / 'transaction.json'
        good = json.loads(stage.read_text())
        for name in ('GameData/hd.pack', '../victim', '.proton/user.reg', 'payload/../../victim', 'payload/CON', 'payload/a:b',
                     'assets/My Xbox Disc.iso', 'assets/second.XISO', 'windows/assets/private.iso'):
            with self.subTest(name=name):
                value = dict(good, files={name: dict(old=None, new='0' * 64)}, phase='applying')
                update.write(stage, value)
                with self.assertRaises(ValueError):
                    update.recover(self.root)
        self.assertEqual((self.root / 'GameData/hd.pack').read_bytes(), b'preserve exactly')

    def test_cancel_and_download_failure_leave_existing_package_untouched(self):
        package(self.root, '0.6.1')
        before = self.snapshot()
        with patch.object(release_download, 'prepare', side_effect=ValueError('offline')):
            with self.assertRaises(ValueError):
                update.prepare(self.root, '0.6.1', 'windows')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / update.STAGE).exists())

    def test_linux_keeps_prefix_and_embedded_interpreter_and_preserves_shell_mode(self):
        _, before = self.prepare('linux')
        update.apply(self.root)
        self.assertEqual((self.root / '.proton/user.reg').read_bytes(), before['.proton/user.reg'])
        self.assertEqual((self.root / 'windows/payload/python/python.exe').read_bytes(), b'python')
        for name in ('assets/My Xbox Disc.iso', 'assets/second.XISO', 'windows/assets/private.iso'):
            self.assertEqual((self.root / name).read_bytes(), before[name])
            self.assertFalse(update.owned(name, 'linux'))
            self.assertFalse(update.owned(name, 'windows'))
        if os.name != 'nt':
            self.assertTrue((self.root / 'Darkwatch.sh').stat().st_mode & 0o111)

    def test_prepare_rejects_user_file_collision(self):
        package(self.root, '0.6.1')
        (self.root / 'payload/new-file.txt').write_bytes(b'user data')
        before = self.snapshot()
        def download(current, selected, scratch, notify, cancel):
            package(scratch / 'new', '0.6.2', b'new')
            return dict(version='0.6.2')
        with patch.object(release_download, 'prepare', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'user file'):
                update.prepare(self.root, '0.6.1', 'windows')
        self.assertEqual(self.snapshot(), before)

    def test_update_temporary_cannot_clobber_unowned_file_or_hardlink(self):
        self.prepare()
        victim = self.root / 'personal-important.txt'
        victim.write_bytes(b'keep unrelated content')
        collision = self.root / 'payload/setup_backend.py.update-tmp'
        os.link(victim, collision)
        update.apply(self.root)
        self.assertEqual(victim.read_bytes(), b'keep unrelated content')
        self.assertEqual(collision.read_bytes(), b'keep unrelated content')

    def test_full_disk_is_rejected_before_any_replacement(self):
        _, before = self.prepare()
        with patch.object(update.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, 'disk space'):
                update.apply(self.root)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(update.transaction(self.root)['phase'], 'prepared')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction check')
    def test_windows_junction_ancestor_is_rejected(self):
        import _winapi
        outside = self.root.parent / 'outside'
        outside.mkdir()
        (outside / 'sentinel').write_bytes(b'untouched')
        junction = self.root / 'linked'
        _winapi.CreateJunction(str(outside), str(junction))
        try:
            with self.assertRaisesRegex(ValueError, 'Linked'):
                update.safe(self.root, 'linked/sentinel')
            self.assertEqual((outside / 'sentinel').read_bytes(), b'untouched')
        finally:
            os.rmdir(junction)


if __name__ == '__main__':
    unittest.main()
