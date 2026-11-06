"""Portuguese uses the real launcher transaction and never replaces disc data."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_launcher_setup as fixture

setup = fixture.setup
language_pack = fixture.language_pack


class PortugueseSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.LauncherSetupTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.LauncherSetupTests.tearDownClass()

    def setUp(self):
        self.fixture = fixture.LauncherSetupTests(methodName="runTest")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        self.pt = {"language_text.bin": b"DWES0003 Portuguese context fixture"}
        self.es = {"language_text.bin": b"DWES0003 Spanish context fixture",
                   "assets/audioDlg.pck": b"verified Spanish dialogue fixture",
                   "assets/Movies1.pck": b"verified Spanish movie fixture"}
        for locale, name, resources in (("pt-BR", "portuguese", self.pt), ("es", "ps2-spanish", self.es)):
            catalog = dict(schema_version=1, language=locale, files={
                path: dict(size=len(data), sha256=fixture.sha(data)) for path, data in resources.items()})
            (f.payload / (name + "-catalog.json")).write_text(json.dumps(catalog), encoding="utf-8")
        f.voice_bundle(f.payload / "portuguese-text.zip", self.pt)
        f.repin()
        f.backend = setup.Setup(f.package, f.install, notify=lambda *args, **kw: None)
        self.current = f.install_disc()

    def install(self, spanish=False):
        f = self.fixture
        if spanish:
            f.install_old_spanish(self.current, self.es)
        f.backend.install_portuguese()
        return f.backend.set_language("pt-BR")

    def test_text_only_install_and_launch_without_ps2_or_retained_iso(self):
        f = self.fixture
        f.iso.unlink()
        settings = self.current / setup.SETTINGS
        settings.write_text('[controls]\nsensitivity = 1.7\n', encoding="utf-8")
        before = f.snapshot(self.current / "assets")
        result = self.install()
        self.assertEqual(result["language"], "pt-BR")
        self.assertTrue(result["portuguese_installed"])
        self.assertFalse(result["spanish_installed"])
        self.assertFalse((self.current / "language/pt-BR/assets").exists())
        self.assertEqual(f.snapshot(self.current / "assets"), before)
        self.assertEqual(setup.tomllib.loads(settings.read_text())['controls']['sensitivity'], 1.7)
        self.assertTrue(f.backend.play()["ready"])
        self.assertTrue((self.current / "worker-ran.txt").is_file())
        self.assertEqual(f.backend.set_language("en")["language"], "en")
        with self.assertRaisesRegex(setup.SetupError, "PS2 ISO import"):
            f.backend.set_language("es")
        self.assertEqual(language_pack.selected(self.current), "en")

    def test_repair_preserves_both_locales_settings_and_separate_saves(self):
        f = self.fixture
        self.install(spanish=True)
        for folder, contents in (("hdd", b"single player progress"), ("hdd2", b"cooperative progress")):
            target = self.current / folder / "save.bin"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(contents)
        old = f.snapshot(self.current)
        fresh = f.install_disc()
        self.assertNotEqual(fresh, self.current)
        self.assertEqual(f.snapshot(self.current), old)
        self.assertTrue(f.backend.portuguese_valid(fresh))
        self.assertTrue(f.backend.spanish_valid(fresh))
        self.assertEqual(language_pack.selected(fresh), "pt-BR")
        self.assertFalse((fresh / "language/pt-BR/assets").exists())
        for folder in ("hdd", "hdd2"):
            self.assertEqual((fresh / folder / "save.bin").read_bytes(), old[folder + "/save.bin"])
        self.assertEqual(f.backend.set_language("es")["language"], "es")
        self.assertEqual(f.backend.set_language("pt-BR")["language"], "pt-BR")

    def test_corrupt_portuguese_stops_play_and_selection_without_spanish_fallback(self):
        f = self.fixture
        self.install(spanish=True)
        target = self.current / "language/pt-BR/language_text.bin"
        target.write_bytes(b"x" * target.stat().st_size)
        before = f.snapshot(self.current)
        with patch.object(setup.subprocess, "Popen") as process:
            with self.assertRaisesRegex(setup.SetupError, "Portuguese translation needs repair"):
                f.backend.play()
            process.assert_not_called()
        with self.assertRaisesRegex(setup.SetupError, "Install the Portuguese translation"):
            f.backend.set_language("pt-BR")
        self.assertEqual(f.snapshot(self.current), before)
        self.assertEqual(language_pack.selected(self.current), "pt-BR")
        self.assertTrue(f.backend.spanish_valid(self.current))
        f.backend.install_portuguese()
        self.assertTrue(f.backend.portuguese_valid(self.current))

    def test_optional_spanish_media_must_validate_before_portuguese_launch(self):
        f = self.fixture
        self.install(spanish=True)
        self.assertTrue(f.backend.play()["ready"])
        movie = self.current / "language/es/assets/Movies1.pck"
        movie.write_bytes(b"x" * movie.stat().st_size)
        before = f.snapshot(self.current)
        with patch.object(setup.subprocess, "Popen") as process:
            with self.assertRaisesRegex(setup.SetupError, "optional Spanish voices need repair"):
                f.backend.play()
            process.assert_not_called()
        self.assertEqual(f.snapshot(self.current), before)
        self.assertTrue(f.backend.portuguese_valid(self.current))

    def test_failed_package_install_and_running_game_keep_existing_translation(self):
        f = self.fixture
        self.install(spanish=True)
        before = f.snapshot(self.current)
        with patch.object(setup, "game_running", return_value=True):
            with self.assertRaisesRegex(setup.SetupError, "Close Darkwatch"):
                f.backend.install_portuguese()
            with self.assertRaisesRegex(setup.SetupError, "Close Darkwatch"):
                f.backend.set_language("en")
        archive = f.payload / "portuguese-text.zip"
        archive.write_bytes(b"damaged download")
        with self.assertRaises(setup.SetupError):
            f.backend.install_portuguese()
        self.assertEqual(f.snapshot(self.current), before)

    def test_broken_optional_copy_during_repair_keeps_old_data_and_blocks_selected_language(self):
        f = self.fixture
        self.install(spanish=True)
        before = f.snapshot(self.current)
        real_copy = f.backend.copy_file
        def fail_portuguese(source, destination):
            if str(destination).replace("\\", "/").endswith("language/pt-BR/language_text.bin"):
                Path(destination).write_bytes(b"partial")
                raise OSError("fixture Portuguese copy failure")
            return real_copy(source, destination)
        with patch.object(f.backend, "copy_file", side_effect=fail_portuguese):
            fresh = f.install_disc()
        self.assertEqual(f.snapshot(self.current), before)
        self.assertFalse((fresh / "language/pt-BR").exists())
        self.assertTrue(f.backend.spanish_valid(fresh))
        self.assertEqual(language_pack.selected(fresh), "pt-BR")
        with patch.object(setup.subprocess, "Popen") as process:
            with self.assertRaisesRegex(setup.SetupError, "Portuguese translation needs repair"):
                f.backend.play()
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
