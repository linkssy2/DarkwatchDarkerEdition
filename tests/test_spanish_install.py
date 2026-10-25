"""Optional language installation is transactional and never replaces disc files."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import language_pack as pack


class SpanishInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / "game"
        (self.current / "assets").mkdir(parents=True)
        (self.current / "assets/audioDlg.pck").write_bytes(b"English disc audio")
        self.files = {"language_text.bin": b"synthetic text", "assets/audioDlg.pck": b"Spanish fixture audio"}
        self.catalog = pack.Catalog(json.dumps(dict(schema_version=1, language="es", files={
            name: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in self.files.items()})).encode())
        self.zip = self.root / "Spanish.zip"
        self.bundle()

    def bundle(self, files=None):
        with zipfile.ZipFile(self.zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in (self.files if files is None else files).items():
                archive.writestr(name, data)

    def install(self, cancel=lambda: None, closed=lambda: None):
        self.catalog.install(self.zip, self.current, cancel, lambda *a, **k: None, closed)

    def test_install_switch_and_repair_preserve(self):
        self.assertFalse(self.catalog.validate(self.current))
        self.install()
        self.assertTrue(self.catalog.validate(self.current))
        settings = self.current / pack.SETTINGS
        settings.write_text('# preserve\n[controls]\nsensitivity = 1.4\n[graphics]\nfullscreen = true\n', encoding="utf-8")
        before = tomllib.loads(settings.read_text())
        pack.select(self.current, "es")
        self.assertEqual(pack.selected(self.current), "es")
        self.assertEqual(tomllib.loads(settings.read_text()), dict(before, language=dict(text="es")))
        pack.select(self.current, "en")
        self.assertEqual(pack.selected(self.current), "en")
        self.assertIn("# preserve", settings.read_text())
        target = self.root / "repair"
        target.mkdir()
        self.assertTrue(self.catalog.preserve(self.current, target, lambda: None, shutil.copyfile))
        self.assertTrue(self.catalog.validate(target))
        self.assertEqual((self.current / "assets/audioDlg.pck").read_bytes(), b"English disc audio")

    def test_media_validation_rejects_empty_catalog_and_unlisted_overlays(self):
        self.install()
        text = pack.Catalog(json.dumps(dict(schema_version=1, language="es", files={
            "language_text.bin": self.catalog.files["language_text.bin"]})).encode())
        self.assertTrue(text.validate(self.current))
        self.assertFalse(text.validate(self.current, media_only=True))
        extra = self.current / pack.DIRECTORY / "assets/Movies1.pck"
        extra.write_bytes(b"unverified movie")
        self.assertFalse(self.catalog.validate(self.current, media_only=True))
        self.assertFalse(self.catalog.validate(self.current))
        self.assertEqual(extra.read_bytes(), b"unverified movie")

    def test_bad_hash_cancel_and_running_game_keep_previous(self):
        self.install()
        original = (self.current / pack.DIRECTORY / "language_text.bin").read_bytes()
        self.bundle(dict(self.files, **{"language_text.bin": b"corrupted text"}))
        with self.assertRaises(ValueError):
            self.install()
        self.bundle()
        def stop():
            raise RuntimeError("cancelled or game running")
        for kwargs in (dict(cancel=stop), dict(closed=stop)):
            with self.assertRaises(RuntimeError):
                self.install(**kwargs)
        self.assertEqual((self.current / pack.DIRECTORY / "language_text.bin").read_bytes(), original)
        self.assertTrue(self.catalog.validate(self.current))
        self.assertFalse(list((self.current / "language").glob(".spanish-stage-*")))

    def test_rename_failure_rolls_back(self):
        self.install()
        original = pack.os.replace
        def failing(source, destination):
            if Path(source).name.startswith(".spanish-stage-") and not Path(source).name.endswith("-previous"):
                raise OSError("locked")
            return original(source, destination)
        with patch.object(pack.os, "replace", side_effect=failing), self.assertRaises(OSError):
            self.install()
        self.assertTrue(self.catalog.validate(self.current))

    def test_bad_archives_and_catalogs(self):
        for extra in ("../escape", "assets/default.xbe", "assets/../../escape"):
            self.bundle(dict(self.files, **{extra: b"bad"}))
            with self.assertRaises(ValueError):
                self.install()
        self.zip.write_bytes(b"not a zip")
        with self.assertRaises(ValueError):
            self.install()
        for raw in (b"[]", b"null", b'{}', b'{"schema_version":1,"language":"es","files":{"language_text.bin":{"size":true,"sha256":1}}}'):
            with self.assertRaises(ValueError):
                pack.Catalog(raw)
        self.assertFalse((self.root / "escape").exists())

    def test_tampered_installed_pack_detected_without_touching_settings(self):
        self.install()
        pack.select(self.current, "es")
        path = self.current / pack.DIRECTORY / "language_text.bin"
        path.write_bytes(bytes(len(path.read_bytes())))
        self.assertTrue(self.catalog.validate(self.current, full=False))
        self.assertFalse(self.catalog.validate(self.current))
        settings = self.current / pack.SETTINGS
        settings.write_text('language = {text = "en"}\n[graphics]\nfov=80\n')
        before = settings.read_bytes()
        with self.assertRaises(ValueError):
            pack.select(self.current, "es")
        self.assertEqual(settings.read_bytes(), before)

    def test_bundled_text_refresh_keeps_optional_voices_and_original_assets(self):
        self.install()
        source = self.root / "bundled.bin"
        data = b"DWES0003 translated fixture"
        source.write_bytes(data)
        catalog = pack.Catalog(json.dumps(dict(schema_version=1, language="es", files={
            "language_text.bin": dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())})).encode())
        catalog.install_text(source, self.current, lambda: None, lambda: None)
        self.assertTrue(catalog.validate(self.current))
        self.assertTrue(self.catalog.validate(self.current, media_only=True))
        self.assertFalse(self.catalog.validate(self.current))  # Old pack's text identity changed.
        target = self.root / "repair"
        target.mkdir()
        self.assertTrue(self.catalog.preserve(self.current, target, lambda: None, shutil.copyfile, media_only=True))
        self.assertFalse((target / pack.DIRECTORY / "language_text.bin").exists())
        self.assertEqual((target / pack.DIRECTORY / "assets/audioDlg.pck").read_bytes(), self.files["assets/audioDlg.pck"])
        self.assertEqual((self.current / "assets/audioDlg.pck").read_bytes(), b"English disc audio")

    def test_bad_or_interrupted_bundled_text_keeps_old_file(self):
        self.install()
        target = self.current / pack.DIRECTORY / "language_text.bin"
        old = target.read_bytes()
        source = self.root / "bundled.bin"
        data = b"new text"
        catalog = pack.Catalog(json.dumps(dict(schema_version=1, language="es", files={
            "language_text.bin": dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())})).encode())
        source.write_bytes(b"bad text")
        with self.assertRaises(ValueError):
            catalog.install_text(source, self.current, lambda: None, lambda: None)
        source.write_bytes(data)
        def stop():
            raise RuntimeError("cancelled or running")
        for cancel, closed in ((stop, lambda: None), (lambda: None, stop)):
            with self.assertRaises(RuntimeError):
                catalog.install_text(source, self.current, cancel, closed)
        with patch.object(pack.os, "replace", side_effect=OSError("locked")), self.assertRaises(OSError):
            catalog.install_text(source, self.current, lambda: None, lambda: None)
        self.assertEqual(target.read_bytes(), old)
        self.assertFalse(list(target.parent.glob(".language-text-*.tmp")))


if __name__ == "__main__":
    unittest.main()
