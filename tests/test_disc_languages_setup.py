"""Shared PS2 import, isolated language media and real launcher update transactions."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import test_portuguese_setup as portuguese
from test_launcher_setup import setup, sha, language_pack


class DiscLanguagesSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        portuguese.PortugueseSetupTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        portuguese.PortugueseSetupTests.tearDownClass()

    def setUp(self):
        self.base = portuguese.PortugueseSetupTests(methodName="runTest")
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.f = f = self.base.fixture
        self.resources = {"es": self.base.es}
        for code, label in (("fr", "french"), ("de", "german"), ("it", "italian")):
            resources = {"language_text.bin": (code + " text").encode(),
                         "assets/audioDlg.pck": (code + " dialogue").encode(),
                         "assets/Movies1.pck": (code + " movie").encode()}
            self.resources[code] = resources
            (f.payload / ("ps2-" + label + "-catalog.json")).write_text(json.dumps(dict(
                schema_version=1, language=code, files={path: dict(size=len(raw), sha256=sha(raw))
                                                     for path, raw in resources.items()})))
        (f.payload / "ps2_spanish.py").write_text("# Converter fixture boundary\n")
        f.repin()
        f.backend = setup.Setup(f.package, f.install, notify=lambda *a, **kw: None)
        f.backend.update()
        self.current = f.backend.active()
        self.disc = f.root / "PS2 Français 🦇.iso"
        self.disc.write_bytes(b"unchanged supported disc fixture")
        def prepare(source, assets, destination, cancel, notify, language="es"):
            self.assertEqual(source, self.disc)
            self.assertEqual(assets, self.current / "assets")
            cancel()
            f.voice_bundle(destination, self.resources[language])
        self.converter = patch.dict(sys.modules, {"ps2_spanish": SimpleNamespace(prepare=prepare)})
        self.converter.start()
        self.addCleanup(self.converter.stop)

    def install_all(self):
        self.f.backend.install_portuguese()
        for code in self.resources:
            self.f.backend.install_disc_language(self.disc, code)

    def test_import_select_and_repair_preserve_every_language_and_saves(self):
        f = self.f
        original = f.snapshot(self.current / "assets")
        self.install_all()
        for folder in ("hdd", "hdd2"):
            (self.current / folder).mkdir(exist_ok=True)
            (self.current / folder / "save.bin").write_bytes(folder.encode())
        for code, label in language_pack.DISC_LANGUAGES.items():
            result = f.backend.set_language(code)
            self.assertTrue(result[label.lower() + "_installed"])
            self.assertEqual(result["language"], code)
            self.assertTrue(f.backend.play()["ready"])
        f.backend.set_language("fr")
        before = f.snapshot(self.current)
        fresh = f.install_disc()
        self.assertEqual(f.snapshot(self.current), before)
        self.assertEqual(f.snapshot(fresh / "assets"), original)
        for code, resources in self.resources.items():
            self.assertEqual(f.snapshot(fresh / "language" / code), resources)
        self.assertTrue(f.backend.portuguese_valid(fresh))
        self.assertEqual(language_pack.selected(fresh), "fr")
        for folder in ("hdd", "hdd2"):
            self.assertEqual((fresh / folder / "save.bin").read_bytes(), folder.encode())
        self.assertEqual(self.disc.read_bytes(), b"unchanged supported disc fixture")

    def test_failed_import_corrupt_media_and_locale_selection_are_isolated(self):
        f = self.f
        self.install_all()
        f.backend.set_language("fr")
        before = f.snapshot(self.current)
        def bad_source(*args, **kw):
            raise ValueError("Unsupported PS2 disc revision")
        with patch.dict(sys.modules, {"ps2_spanish": SimpleNamespace(prepare=bad_source)}):
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                f.backend.install_disc_language(self.disc, "it")
        def wrong_language(source, assets, destination, cancel, notify, language="es"):
            f.voice_bundle(destination, self.resources["de"])
        with patch.dict(sys.modules, {"ps2_spanish": SimpleNamespace(prepare=wrong_language)}):
            with self.assertRaises(ValueError):
                f.backend.install_disc_language(self.disc, "fr")
        self.assertEqual(f.snapshot(self.current), before)
        movie = self.current / "language/fr/assets/Movies1.pck"
        movie.write_bytes(b"x" * movie.stat().st_size)
        with patch.object(setup.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(setup.SetupError, "French needs"):
                f.backend.play()
            spawn.assert_not_called()
        self.assertEqual(language_pack.selected(self.current), "fr")
        self.assertEqual(f.backend.set_language("de")["language"], "de")
        self.assertTrue(f.backend.play()["ready"])
        with self.assertRaisesRegex(setup.SetupError, "French needs"):
            f.backend.set_language("fr")
        self.assertEqual(language_pack.selected(self.current), "de")

    def test_catalogue_locale_mismatch_and_unknown_import_are_rejected(self):
        f = self.f
        with self.assertRaisesRegex(setup.SetupError, "supported PS2 disc language"):
            f.backend.install_disc_language(self.disc, "pt-BR")
        path = f.payload / "ps2-french-catalog.json"
        wrong = json.loads(path.read_text())
        wrong["language"] = "de"
        path.write_text(json.dumps(wrong))
        f.repin()
        with self.assertRaisesRegex(setup.SetupError, "Invalid French catalog"):
            setup.Setup(f.package, f.install)


if __name__ == "__main__":
    unittest.main()
