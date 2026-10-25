"""Optional artwork uses tiny real ZIPs; game launches are never needed."""
import io
import json
import os
import shutil
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from test_launcher_setup import LauncherSetupTests as Fixtures, setup, sha


class GameplayHdSetupTests(unittest.TestCase):
    setUpClass = classmethod(Fixtures.setUpClass.__func__)
    tearDownClass = classmethod(Fixtures.tearDownClass.__func__)
    setUp = Fixtures.setUp
    repin = Fixtures.repin
    install_disc = Fixtures.install_disc
    snapshot = Fixtures.snapshot

    def archive(self, entries=None):
        path = self.root / "textures.zip"
        if entries is None:
            entries = [("pack.json", (self.payload / "gameplay-hd-catalog.json").read_bytes()),
                       ("gameplay-hd/example.dwt", self.texture)]
        with warnings.catch_warnings(), zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            warnings.simplefilter("ignore", UserWarning)
            for name, data in entries:
                if isinstance(name, str):
                    # ZipInfo normally sanitizes Windows slashes/NULs while writing.
                    raw = zipfile.ZipInfo()
                    raw.filename = raw.orig_filename = name
                    raw.compress_type = zipfile.ZIP_DEFLATED
                    name = raw
                target.writestr(name, data)
        return path

    def install_pack(self, archive=None):
        with setup.exclusive(self.install):
            return self.backend.install_hd_textures(archive or self.archive())

    def split_archive(self, source=None, size=128):
        original = (source or self.archive()).read_bytes()
        for existing in self.root.glob("textures.zip.[0-9][0-9][0-9]"):
            existing.unlink()
        parts = []
        for start in range(0, len(original), size):
            part = self.root / ("textures.zip.%03d" % (start // size + 1))
            part.write_bytes(original[start:start + size])
            parts.append(part)
        return parts

    def assert_clean(self, current):
        self.assertFalse(list(current.glob(".gameplay-hd-*")))

    def test_install_status_and_optional_verify_do_not_change_user_data(self):
        self.assertFalse(self.backend.status()["hd_textures_installed"])
        with self.assertRaisesRegex(setup.SetupError, "Import or repair"):
            self.install_pack()
        current = self.install_disc()
        (current / setup.SETTINGS).write_bytes(b"settings stay unchanged")
        (current / "hdd/E").mkdir(parents=True)
        (current / "hdd/E/save.dat").write_bytes(b"progress")
        before = self.snapshot(current)
        self.assertFalse(self.backend.status()["hd_textures_installed"])
        self.assertTrue(self.install_pack()["hd_textures_installed"])
        for name, content in before.items():
            self.assertEqual((current / name).read_bytes(), content)
        self.assertEqual((current / "gameplay-hd/example.dwt").read_bytes(), self.texture)
        self.assertTrue(self.backend.status()["hd_textures_installed"])
        self.assertEqual(self.backend.verify(), current)
        self.assertTrue(self.backend.hd_verified)
        # Quick status reads headers, not every pixel; explicit Verify hashes pixels.
        file = current / "gameplay-hd/example.dwt"
        changed = bytearray(self.texture); changed[33] ^= 1
        file.write_bytes(changed)
        self.assertTrue(self.backend.status()["ready"])
        self.assertEqual(self.backend.verify(), current)
        self.assertFalse(self.backend.hd_verified)
        self.assertIn("base game is still ready", self.backend.hd_warning)
        with patch.object(self.backend.hd_catalog, "validate", side_effect=AssertionError("Do not hash optional data on Play")):
            self.assertEqual(self.backend.verify(optional=False), current)
        file.unlink()
        self.assertTrue(self.backend.status()["ready"])
        self.assertFalse(self.backend.status()["hd_textures_installed"])
        self.assert_clean(current)

    def test_wrong_corrupt_missing_and_extra_zip_entries_keep_installed_pack(self):
        current = self.install_disc(); self.install_pack()
        before = self.snapshot(current)
        catalog = (self.payload / "gameplay-hd-catalog.json").read_bytes()
        for entries in (
                [("pack.json", catalog)],
                [("pack.json", catalog.replace(b'"1"', b'"2"')), ("gameplay-hd/example.dwt", self.texture)],
                [("pack.json", catalog), ("gameplay-hd/example.dwt", self.texture[:-1])],
                [("pack.json", catalog), ("gameplay-hd/example.dwt", self.texture[:-1] + b"X")],
                [("pack.json", catalog), ("unrelated.txt", b"wrong")],
                [("pack.json", catalog), ("gameplay-hd/example.dwt", self.texture), ("extra.dwt", b"x")]):
            with self.subTest(names=[str(x[0]) for x in entries]), self.assertRaises(ValueError):
                self.install_pack(self.archive(entries))
            self.assertEqual(self.snapshot(current), before)
            self.assert_clean(current)
        path = self.root / "broken.zip"; path.write_bytes(b"not a ZIP")
        with self.assertRaisesRegex(ValueError, "valid complete ZIP"):
            self.install_pack(path)

    def test_exact_previous_pack_installs_verifies_and_survives_update(self):
        current = self.install_disc()
        old_content = (self.payload / "gameplay-hd-catalog.json").read_bytes()
        new_data = dict(self.catalog, previous_catalog=old_content.decode(),
                        files=self.catalog["files"] + [dict(self.catalog["files"][0], path="gameplay-hd/extension.dwt")])
        new_content = (json.dumps(new_data) + "\n").encode()
        catalog = setup.gameplay_hd.Catalog(new_content)
        quiet, cancel = lambda *a, **k: None, lambda: None
        catalog.install(self.archive(), current, cancel, quiet, cancel)
        self.assertTrue(catalog.validate(current, cancel, quiet, full=True))
        self.assertIs(catalog.matching(old_content), catalog.previous)
        before = self.snapshot(current / "gameplay-hd")
        stage = self.root / "new-build"
        stage.mkdir()
        self.assertTrue(catalog.preserve(current, stage, cancel, quiet, shutil.copyfile))
        self.assertEqual(self.snapshot(stage / "gameplay-hd"), before)
        catalog.install(self.archive([("pack.json", new_content),
                        ("gameplay-hd/example.dwt", self.texture),
                        ("gameplay-hd/extension.dwt", self.texture)]), current, cancel, quiet, cancel)
        self.assertTrue(catalog.validate(current, cancel, quiet, full=True))
        self.assertIs(catalog.matching(new_content), catalog)
        # Neither an incomplete extension nor a made-up receipt can claim compatibility.
        (current / "gameplay-hd/extension.dwt").unlink()
        with self.assertRaises(ValueError):
            catalog.validate(current, cancel, quiet)
        with self.assertRaises(ValueError):
            catalog.matching(old_content + b" ")
        for previous in (42, new_content.decode(), old_content.decode().replace('example.dwt', 'different.dwt')):
            with self.assertRaises(ValueError):
                setup.gameplay_hd.Catalog(json.dumps(dict(new_data, previous_catalog=previous)).encode())
        # A previous-format download still receives full checksums on installation.
        with self.assertRaises(ValueError):
            catalog.install(self.archive([("pack.json", old_content),
                            ("gameplay-hd/example.dwt", self.texture[:-1] + b"X")]), current, cancel, quiet, cancel)

    def test_two_exact_published_generations_and_current_keep_strict_validation(self):
        current = self.install_disc()
        old = (self.payload / 'gameplay-hd-catalog.json').read_bytes()
        receipts = [old]
        files = list(self.catalog['files'])
        for revision in (2, 3):
            files += [dict(files[0], path=f'gameplay-hd/rev{revision}-{i}.dwt') for i in range(2)]
            receipts.append((json.dumps(dict(self.catalog, files=files,
                                            previous_catalog=receipts[-1].decode())) + '\n').encode())
        catalog = setup.gameplay_hd.Catalog(receipts[-1])
        self.assertEqual([c.content for c in catalog.generations()], list(reversed(receipts)))
        quiet, cancel = lambda *a, **k: None, lambda: None
        for generation, receipt in enumerate(receipts):
            selected = catalog.matching(receipt)
            entries = [('pack.json', receipt)] + [(name, self.texture) for name in selected.files]
            catalog.install(self.archive(entries), current, cancel, quiet, cancel)
            self.assertTrue(catalog.validate(current, cancel, quiet, full=True))
            stage = self.root / f'preserved-generation-{generation}'
            stage.mkdir()
            self.assertTrue(catalog.preserve(current, stage, cancel, quiet, shutil.copyfile))
            self.assertEqual(self.snapshot(stage / 'gameplay-hd'), self.snapshot(current / 'gameplay-hd'))
            # Same-size tampering still fails SHA validation for every generation.
            name = next(iter(selected.files))
            path = current / name
            path.write_bytes(self.texture[:-1] + bytes([self.texture[-1] ^ 1]))
            with self.assertRaises(ValueError):
                catalog.validate(current, cancel, quiet, full=True)
            path.unlink()
            with self.assertRaises(ValueError):
                catalog.validate(current, cancel, quiet)
            path.write_bytes(self.texture)
            (current / 'gameplay-hd/unexpected.dwt').write_bytes(self.texture)
            with self.assertRaises(ValueError):
                catalog.validate(current, cancel, quiet)
            (current / 'gameplay-hd/unexpected.dwt').unlink()
            # A forged subset receipt and altered whitespace are never trusted.
            made_up = json.loads(receipt)
            made_up['files'] = made_up['files'][:-1]
            with self.assertRaises(ValueError):
                catalog.matching(json.dumps(made_up).encode())
            with self.assertRaises(ValueError):
                catalog.matching(receipt + b' ')
            bad_entries = [('pack.json', receipt)] + [(n, self.texture[:-1] + b'X') for n in selected.files]
            before = self.snapshot(current / 'gameplay-hd')
            with self.assertRaises(ValueError):
                catalog.install(self.archive(bad_entries), current, cancel, quiet, cancel)
            self.assertEqual(before, self.snapshot(current / 'gameplay-hd'))
        fourth = dict(json.loads(receipts[-1]), previous_catalog=receipts[-1].decode(),
                      files=files + [dict(files[0], path='gameplay-hd/fourth.dwt')])
        with self.assertRaisesRegex(ValueError, 'Unsupported previous'):
            setup.gameplay_hd.Catalog(json.dumps(fourth).encode())
        altered = json.loads(receipts[1])
        changed_old = json.loads(receipts[0])
        changed_old['files'][0]['sha256'] = '0' * 64
        altered['previous_catalog'] = json.dumps(changed_old)
        invalid = dict(json.loads(receipts[2]), previous_catalog=json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'Previous HD textures differ'):
            setup.gameplay_hd.Catalog(json.dumps(invalid).encode())

    def test_zip_paths_duplicates_links_and_expansion_are_rejected(self):
        current = self.install_disc()
        catalog = (self.payload / "gameplay-hd-catalog.json").read_bytes()
        for name in ("../escape.dwt", "/root.dwt", "gameplay-hd/../escape.dwt", "C:/escape.dwt",
                     "gameplay-hd\\example.dwt", "GAMEPLAY-HD/EXAMPLE.DWT", "gameplay-hd/example.dwt\0other"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.install_pack(self.archive([("pack.json", catalog), (name, self.texture)]))
        for special in (stat.S_IFLNK | 0o777, stat.S_IFDIR | 0o777):
            item = zipfile.ZipInfo("gameplay-hd/example.dwt"); item.create_system = 3
            item.external_attr = special << 16
            with self.assertRaises(ValueError):
                self.install_pack(self.archive([("pack.json", catalog), (item, self.texture)]))
        for entries in ([("pack.json", catalog), ("pack.json", catalog)],
                        [("pack.json", catalog), ("gameplay-hd/example.dwt", b"0" * 1000000)]):
            with self.assertRaises(ValueError):
                self.install_pack(self.archive(entries))
        self.assertFalse((self.root / "escape.dwt").exists())
        self.assertFalse((current / "gameplay-hd").exists())
        self.assert_clean(current)

    def test_cancellation_at_last_progress_and_replace_failure_roll_back(self):
        current = self.install_disc(); self.install_pack()
        before = self.snapshot(current)
        cancel = self.root / "cancel"; self.backend.cancel_file = cancel
        old_notify = self.backend.notify
        def cancel_when_extracted(event, message, **fields):
            old_notify(event, message, **fields)
            if message == "Installing optional HD textures":
                cancel.touch()
        self.backend.notify = cancel_when_extracted
        with self.assertRaises(setup.Cancelled):
            self.install_pack()
        cancel.unlink(); self.backend.notify = old_notify
        self.assertEqual(self.snapshot(current), before)
        real_replace = os.replace
        def fail_commit(source, target):
            if Path(source).name.startswith(".gameplay-hd-stage-"):
                raise OSError("synthetic commit failure")
            return real_replace(source, target)
        with patch.object(os, "replace", side_effect=fail_commit), self.assertRaisesRegex(OSError, "synthetic commit"):
            self.install_pack()
        self.assertEqual(self.snapshot(current), before)
        self.assert_clean(current)

    def test_game_and_launcher_locks_block_install(self):
        self.install_disc()
        with patch.object(setup, "game_running", return_value=True), self.assertRaisesRegex(setup.SetupError, "Close Darkwatch"):
            self.install_pack()
        with setup.exclusive(self.install), self.assertRaisesRegex(setup.SetupError, "already in progress"):
            self.install_pack()

    def test_reimport_preserves_independent_verified_pack_and_cancel_keeps_old(self):
        first = self.install_disc(); self.install_pack()
        receipt = json.loads((first / 'install.json').read_text())
        receipt['content_revision'] = 'wartrain-splitter-v1'
        (first / 'install.json').write_text(json.dumps(receipt))
        before = self.snapshot(first)
        second = self.install_disc()
        self.assertEqual((first / "gameplay-hd/example.dwt").read_bytes(), self.texture)
        self.assertEqual((second / "gameplay-hd/example.dwt").read_bytes(), self.texture)
        self.assertFalse(os.path.samefile(first / "gameplay-hd/example.dwt", second / "gameplay-hd/example.dwt"))
        self.assertEqual(self.snapshot(first), before)
        notify = self.backend.notify
        def cancel_on_verify(event, message, **fields):
            if message == "Verifying optional HD textures":
                raise setup.Cancelled("cancelled copying textures")
            notify(event, message, **fields)
        self.backend.notify = cancel_on_verify
        with self.assertRaises(setup.Cancelled):
            self.install_disc()
        self.assertEqual(self.backend.active(), second)
        self.assertEqual(set((self.install / "versions").iterdir()), {first, second})
        self.assertEqual((second / "gameplay-hd/example.dwt").read_bytes(), self.texture)

    def test_damaged_optional_pack_does_not_block_iso_repair(self):
        first = self.install_disc(); self.install_pack()
        file = first / "gameplay-hd/example.dwt"
        file.write_bytes(b"bad")
        second = self.install_disc()
        self.assertTrue(self.backend.status()["ready"])
        self.assertFalse(self.backend.status()["hd_textures_installed"])
        self.assertFalse((second / "gameplay-hd").exists())
        self.assertEqual(file.read_bytes(), b"bad")

    def test_unreadable_or_linked_optional_source_does_not_block_iso_repair(self):
        for error in (OSError("unreadable old artwork"), setup.intake.IntakeError("optional junction")):
            first = self.install_disc(); self.install_pack()
            before = self.snapshot(first)
            validate = self.backend.hd_catalog.validate
            def fail_old(current, *args, **kwargs):
                if current == first:
                    raise error
                return validate(current, *args, **kwargs)
            with self.subTest(error=type(error)), patch.object(self.backend.hd_catalog, "validate", side_effect=fail_old):
                second = self.install_disc()
            self.assertTrue(self.backend.status()["ready"])
            self.assertFalse((second / "gameplay-hd").exists())
            self.assertEqual(self.snapshot(first), before)

    def test_cli_install_and_failure_preserve_ready_state(self):
        self.install_disc()
        archive = self.archive()
        prefix = ["--package", str(self.package), "--install-root", str(self.install), "--install-hd-textures"]
        for path, code in ((archive, 0), (self.root / "missing.zip", 1)):
            output = io.StringIO()
            with patch("sys.stdout", output):
                result = setup.main(prefix + [str(path)])
            self.assertEqual(result, code)
            final = json.loads(output.getvalue().splitlines()[-1])
            self.assertTrue(final["ready"])
            self.assertTrue(final["hd_textures_installed"])
            self.assertEqual(final["event"], "result" if code == 0 else "error")

    def test_catalog_and_destination_links_are_rejected(self):
        current = self.install_disc()
        for path in ("gameplay-hd/../escape.dwt", "gameplay-hd/CON.dwt", "gameplay-hd/example.dwt:other"):
            value = dict(self.catalog, files=[dict(self.catalog["files"][0], path=path)])
            with self.assertRaises(ValueError):
                setup.gameplay_hd.Catalog(json.dumps(value).encode())
        value = dict(self.catalog, files=self.catalog["files"] * 2)
        with self.assertRaises(ValueError):
            setup.gameplay_hd.Catalog(json.dumps(value).encode())
        destination = current / "gameplay-hd"
        destination.mkdir()
        outside = self.root / "outside.dwt"; outside.write_bytes(self.texture)
        os.link(outside, destination / "example.dwt")
        with self.assertRaises(ValueError):
            self.install_pack()
        self.assertEqual(outside.read_bytes(), self.texture)

    def test_multipart_seek_read_and_real_zip_install_without_joined_copy(self):
        current = self.install_disc()
        parts = self.split_archive()
        original = (self.root / "textures.zip").read_bytes()
        before = set(self.root.iterdir())
        with patch.object(setup.gameplay_hd, "PART_SIZE", 128):
            with setup.gameplay_hd.Archive(parts[0], len(original)) as archive:
                for start, count in ((0, 1), (127, 3), (128, 130), (len(original) - 3, 100)):
                    archive.seek(start)
                    self.assertEqual(archive.read(count), original[start:start + count])
                archive.seek(-16, 2)
                self.assertEqual(archive.read(), original[-16:])
                archive.seek(10); archive.seek(-5, 1)
                self.assertEqual(archive.tell(), 5)
                self.assertEqual(archive.read(0), b"")
                with self.assertRaises(OSError):
                    archive.seek(-1)
            self.assertTrue(self.install_pack(parts[0])["hd_textures_installed"])
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual((current / "gameplay-hd/example.dwt").read_bytes(), self.texture)
        self.assert_clean(current)

    def test_user_renamed_unicode_download_and_folder_are_supported(self):
        current = self.install_disc()
        folder = self.root / "下載 🦇"; folder.mkdir()
        archive = folder / "Darkwatch HD 🦇.zip"
        archive.write_bytes(self.archive().read_bytes())
        self.assertTrue(self.install_pack(archive)["hd_textures_installed"])
        with patch.object(setup.gameplay_hd, "PART_SIZE", 128):
            parts = self.split_archive()
            renamed = []
            for part in parts:
                target = folder / (archive.name + part.suffix)
                part.rename(target); renamed.append(target)
            self.assertTrue(self.install_pack(renamed[0])["hd_textures_installed"])
        self.assertEqual((current / "gameplay-hd/example.dwt").read_bytes(), self.texture)

    def test_multipart_missing_truncated_corrupt_and_linked_parts_keep_install(self):
        current = self.install_disc(); self.install_pack()
        before = self.snapshot(current)
        with patch.object(setup.gameplay_hd, "PART_SIZE", 128):
            parts = self.split_archive()
            with self.assertRaisesRegex(ValueError, "first.*001"):
                self.install_pack(parts[1])
            parts[1].unlink()
            with self.assertRaisesRegex(ValueError, "parts are missing"):
                self.install_pack(parts[0])
            parts = self.split_archive(); parts[-1].unlink()
            with self.assertRaisesRegex(ValueError, "all parts"):
                self.install_pack(parts[0])
            parts = self.split_archive(); parts[0].write_bytes(parts[0].read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "parts are incomplete"):
                self.install_pack(parts[0])
            parts = self.split_archive()
            changed = bytearray(parts[1].read_bytes()); changed[40] ^= 255; parts[1].write_bytes(changed)
            with self.assertRaises(ValueError):
                self.install_pack(parts[0])
            parts = self.split_archive()
            outside = self.root / "outside-part"; os.link(parts[0], outside)
            with self.assertRaisesRegex(ValueError, "must not use links"):
                self.install_pack(parts[0])
            outside.unlink()
            (self.root / "textures.zip.033").write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "unsupported parts"):
                self.install_pack(parts[0])
        self.assertEqual(self.snapshot(current), before)
        self.assert_clean(current)


del Fixtures  # unittest must not discover the imported fixture's existing tests twice.

if __name__ == "__main__":
    unittest.main()
