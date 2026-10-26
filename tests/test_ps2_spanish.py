"""Own-disc import verifies inputs and leaves active files outside its staging ZIP."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ps2_spanish as spanish
from test_ps2_disc import disc, record


class SpanishDiscTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.iso = self.root / "español.iso"
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.out = self.root / "staging.zip"
        cnf = b"BOOT2 = cdrom0:\\SLES_535.64;1\n"
        raw = disc([record(b"SYSTEM.CNF;1", 21, len(cnf)), record(b"AUDIO.PCK;1", 22, 5),
                    record(b"MOVIES.PCK;1", 23, 6), record(b"PACKFILE.PCK;1", 24, 4)])
        raw[21*2048:21*2048+len(cnf)] = cnf
        raw[22*2048:22*2048+5], raw[23*2048:23*2048+6] = b"audio", b"movies"
        raw[24*2048:24*2048+4] = b"text"
        self.iso.write_bytes(raw)
        self.ps2 = {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in
                    (("AUDIO.PCK", b"audio"), ("MOVIES.PCK", b"movies"), ("PACKFILE.PCK", b"text"))}
        self.xbox = {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in
                     (("audioDlg.pck", b"original dialogue"), ("Movies1.pck", b"original movie"))}
        (self.assets / "audioDlg.pck").write_bytes(b"original dialogue")
        (self.assets / "Movies1.pck").write_bytes(b"original movie")
        (self.assets / "packfile.pck").write_bytes(b"original Xbox text contexts")
        self.addCleanup(patch.stopall)
        patch.object(spanish, "PS2", self.ps2).start()
        patch.object(spanish, "XBOX", self.xbox).start()
        patch.object(spanish, "Pck", side_effect=lambda iso, name: name).start()
        self.dialogue = patch.object(spanish.ps2_dialogue, "convert", return_value=b"Spanish dialogue").start()
        self.movies = patch.object(spanish.ps2_movies, "convert", return_value=b"Spanish movie").start()
        self.text = patch.object(spanish.ps2_text, "convert", return_value=b"PS2 Spanish text").start()

    def run_import(self, cancel=lambda: None):
        spanish.prepare(self.iso, self.assets, self.out, cancel, lambda *a, **k: None)

    def test_output_contains_only_requested_resources_and_sources_unchanged(self):
        before = {p: p.read_bytes() for p in (self.iso, self.assets / "audioDlg.pck", self.assets / "Movies1.pck")}
        self.run_import()
        with zipfile.ZipFile(self.out) as bundle:
            self.assertEqual(set(bundle.namelist()), {"language_text.bin", "assets/audioDlg.pck", "assets/Movies1.pck"})
            self.assertEqual(bundle.read("assets/audioDlg.pck"), b"Spanish dialogue")
            self.assertEqual(bundle.read("language_text.bin"), b"PS2 Spanish text")
        self.text.assert_called_once_with("PACKFILE.PCK", b"original Xbox text contexts")
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_wrong_disc_and_damaged_source_never_convert(self):
        raw = bytearray(self.iso.read_bytes())
        raw[22*2048] ^= 1
        self.iso.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "damaged or unsupported"):
            self.run_import()
        self.assertFalse(self.out.exists())
        self.dialogue.assert_not_called()

    def test_changed_xbox_data_retains_sources_and_removes_stage(self):
        (self.assets / "audioDlg.pck").write_bytes(b"changed! dialogue")
        with self.assertRaisesRegex(ValueError, "needs repair"):
            self.run_import()
        self.assertFalse(self.out.exists())
        self.dialogue.assert_not_called()

    def test_converter_failure_and_cancellation_remove_stage(self):
        for error in (ValueError("decoder rejected input"), InterruptedError("cancelled")):
            with self.subTest(error=error):
                self.movies.side_effect = error
                with self.assertRaises(type(error)):
                    self.run_import()
                self.assertFalse(self.out.exists())

    def test_existing_stage_is_never_overwritten(self):
        self.out.write_bytes(b"preserved")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.run_import()
        self.assertEqual(self.out.read_bytes(), b"preserved")

    def test_stage_created_during_verification_is_not_deleted(self):
        def concurrent_output(iso, name):
            self.out.write_bytes(b"someone else's output")
            return name
        with patch.object(spanish, "Pck", side_effect=concurrent_output), self.assertRaises(FileExistsError):
            self.run_import()
        self.assertEqual(self.out.read_bytes(), b"someone else's output")

    def test_cancellation_during_disc_verification(self):
        def cancel():
            raise InterruptedError()
        with self.assertRaises(InterruptedError):
            self.run_import(cancel)
        self.assertFalse(self.out.exists())

    def test_bad_text_mapping_leaves_previous_resources_untouched(self):
        self.text.side_effect = ValueError("Incompatible English text contexts")
        with self.assertRaisesRegex(ValueError, "English text contexts"):
            self.run_import()
        self.assertFalse(self.out.exists())
        self.assertEqual((self.assets / "packfile.pck").read_bytes(), b"original Xbox text contexts")
        self.dialogue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
