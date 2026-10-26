"""Proton release layout checks use synthetic payloads only."""
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_linux', ROOT / 'tools/package_linux.py')
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


class LinuxPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.windows, self.wrapper = self.root / 'windows', self.root / 'wrapper'
        self.windows.mkdir()
        self.wrapper.mkdir()
        (self.windows / 'package-manifest.json').write_bytes(b'fixture manifest')
        (self.windows / 'payload.bin').write_bytes(b'synthetic payload')
        # A non-allowlisted local file must never enter a release archive.
        (self.windows / 'save.dat').write_bytes(b'private fixture')
        self.files = {'payload.bin': pack.windows_package.sha(self.windows / 'payload.bin')}
        for name in pack.WRAPPER_FILES:
            (self.wrapper / name).write_bytes(b'fixture\n')
        self.output = self.root / 'release.tar.gz'
        self.verify = patch.object(pack.windows_package, 'verify', return_value=self.files)
        self.verify.start()
        self.addCleanup(self.verify.stop)

    def test_exact_members_hashes_and_executable_mode(self):
        result = pack.package(self.windows, self.wrapper, self.output)
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['linux_gameplay_verified'])
        with tarfile.open(self.output) as archive:
            entries = archive.getmembers()
            self.assertEqual(len(entries), 6)
            self.assertTrue(all(entry.isfile() for entry in entries))
            self.assertFalse(any(entry.name.endswith('save.dat') for entry in entries))
            self.assertEqual(next(e.mode for e in entries if e.name.endswith('/Darkwatch.sh')), 0o755)
            self.assertEqual(next(e.mode for e in entries if e.name.endswith('/linux/launcher.py')), 0o644)

    def test_refuses_overwrite_and_changed_payload(self):
        self.output.write_bytes(b'existing release')
        with self.assertRaises(FileExistsError):
            pack.package(self.windows, self.wrapper, self.output)
        self.assertEqual(self.output.read_bytes(), b'existing release')
        self.output.unlink()
        (self.windows / 'payload.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            pack.package(self.windows, self.wrapper, self.output)
        self.assertFalse(self.output.exists())

    def test_refuses_crlf_or_missing_entrypoint(self):
        (self.wrapper / 'Darkwatch.sh').write_bytes(b'#!/bin/sh\r\n')
        with self.assertRaisesRegex(ValueError, 'LF'):
            pack.package(self.windows, self.wrapper, self.output)
        (self.wrapper / 'Darkwatch.sh').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            pack.package(self.windows, self.wrapper, self.output)

    def test_shipped_wrapper_files_pass_actual_package_checks(self):
        result = pack.package(self.windows, ROOT / 'launcher/linux', self.output)
        self.assertEqual(result['status'], 'pass')


if __name__ == '__main__':
    unittest.main()
