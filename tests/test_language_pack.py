"""Locale-specific installs retain the other language and existing user settings."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import language_pack as pack


class LanguagePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / "game"
        self.current.mkdir()
        self.files = {
            "es": {"language_text.bin": b"Spanish text", "assets/audioDlg.pck": b"Spanish voices"},
            "pt-BR": {"language_text.bin": b"Portuguese text"},
        }
        self.catalogs = {}
        self.archives = {}
        for language, files in self.files.items():
            self.catalogs[language] = pack.Catalog(json.dumps(dict(
                schema_version=1, language=language, files={
                    name: dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                    for name, raw in files.items()})).encode())
            self.archives[language] = self.root / (language + ".zip")
            self.bundle(language, files)

    def bundle(self, language, files):
        with zipfile.ZipFile(self.archives[language], "w") as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)

    def install(self, language, cancel=lambda: None, closed=lambda: None):
        self.catalogs[language].install(
            self.archives[language], self.current, cancel, lambda *a, **k: None, closed)

    def test_selection_preserves_settings_and_unknown_values_default_without_rewrite(self):
        path = self.current / pack.SETTINGS
        path.write_text('# keep\n[language]\ntext="es"\ncustom=true\n[graphics]\nfov=90\n')
        before = tomllib.loads(path.read_text())
        for language in ("pt-BR", "en", "es"):
            pack.select(self.current, language)
            self.assertEqual(pack.selected(self.current), language)
            self.assertEqual(tomllib.loads(path.read_text()), dict(
                before, language=dict(before["language"], text=language)))
            self.assertIn("# keep", path.read_text())
        for value in ('"pt-br"', '[]', '{}', 'false', '2'):
            raw = '[language]\ntext=' + value + '\n'
            path.write_text(raw)
            self.assertEqual(pack.selected(self.current), "en")
            self.assertEqual(path.read_text(), raw)
        for value in ("pt-br", "../es", [], None):
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                pack.select(self.current, value)
            self.assertEqual(path.read_bytes(), before)

    def test_text_only_portuguese_install_and_validation_are_isolated(self):
        self.install("es")
        self.assertFalse(self.catalogs["pt-BR"].validate(self.current))
        self.install("pt-BR")
        for language, catalog in self.catalogs.items():
            self.assertEqual(catalog.language, language)
            self.assertEqual(catalog.directory, "language/" + language)
            self.assertTrue(catalog.validate(self.current))
            for name, raw in self.files[language].items():
                self.assertEqual((self.current / catalog.directory / name).read_bytes(), raw)
        self.assertEqual(self.catalogs["es"].directory, pack.DIRECTORY)
        self.assertFalse((self.current / "language/pt-BR/assets").exists())
        path = self.current / "language/pt-BR/language_text.bin"
        path.write_bytes(b"X" * path.stat().st_size)
        self.assertFalse(self.catalogs["pt-BR"].validate(self.current))
        self.assertTrue(self.catalogs["es"].validate(self.current))

    def test_failed_portuguese_update_rolls_back_without_touching_spanish(self):
        self.install("es")
        self.install("pt-BR")
        replace = pack.os.replace

        def fail_commit(source, destination):
            name = Path(source).name
            if name.startswith(".portuguese-stage-") and not name.endswith("-previous"):
                raise OSError("locked")
            return replace(source, destination)

        with patch.object(pack.os, "replace", side_effect=fail_commit), self.assertRaises(OSError):
            self.install("pt-BR")

        def stop():
            raise RuntimeError("cancelled or game running")

        for kwargs in (dict(cancel=stop), dict(closed=stop)):
            with self.assertRaises(RuntimeError):
                self.install("pt-BR", **kwargs)
        self.bundle("pt-BR", {"language_text.bin": b"corrupted text"})
        with self.assertRaises(ValueError):
            self.install("pt-BR")
        self.assertTrue(all(catalog.validate(self.current) for catalog in self.catalogs.values()))
        self.assertFalse(list((self.current / "language").glob(".portuguese-stage-*")))

    def test_repair_preserves_requested_locale_without_copying_other_media(self):
        self.install("es")
        self.install("pt-BR")
        target = self.root / "repair"
        target.mkdir()
        portuguese = self.catalogs["pt-BR"]
        self.assertTrue(portuguese.preserve(self.current, target, lambda: None, shutil.copyfile))
        self.assertTrue(portuguese.validate(target))
        self.assertFalse(self.catalogs["es"].validate(target))
        self.assertFalse((target / pack.DIRECTORY).exists())

    def test_catalog_rejects_unsupported_or_path_language_identifiers(self):
        for language in ("en", "pt-br", "zz", "../es", "pt-BR/../es", [], None):
            with self.subTest(language=language), self.assertRaises(ValueError):
                pack.Catalog(json.dumps(dict(schema_version=1, language=language,
                                             files=self.catalogs["pt-BR"].files)).encode())


if __name__ == "__main__":
    unittest.main()
