"""Pinned bonus selector preparation and own-disc import; no game or native helper runs."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "launcher"), str(ROOT / "tools")]
import bonus_content as bonus
import setup_backend as setup
from test_launcher_setup import make_iso

ORIGINAL = b"AA original BB fixture CC archive"
PATCHES = ((0, b"AA", b"aa"), (12, b"BB", b"bb"), (23, b"CC", b"cc"))
EXPECTED = b"aa original bb fixture cc archive"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class BonusContentTests(unittest.TestCase):
    def setUp(self):
        pins = patch.multiple(bonus, ORIGINAL_SHA256=sha(ORIGINAL),
                              INSTALLED_SHA256=sha(EXPECTED), PATCHES=PATCHES)
        pins.start()
        self.addCleanup(pins.stop)

    def test_exact_copy_and_refusal_of_wrong_partial_or_reapplied_input(self):
        source = bytearray(ORIGINAL)
        self.assertEqual(bonus.patch_pack(source), EXPECTED)
        self.assertEqual(source, ORIGINAL)
        partial = bytearray(ORIGINAL)
        partial[:2] = b"aa"
        for invalid in (b"another revision", ORIGINAL[:-1], EXPECTED, partial):
            with self.subTest(input=invalid), self.assertRaisesRegex(ValueError, "unchanged supported"):
                bonus.patch_pack(invalid)

    def test_selector_and_result_guards_fail_closed(self):
        for patches in (((0, b"XX", b"aa"),), ((0, b"AA", b"a"),), ((100, b"AA", b"aa"),)):
            with patch.object(bonus, "PATCHES", patches), self.assertRaisesRegex(ValueError, "selectors"):
                bonus.patch_pack(ORIGINAL)
        with patch.object(bonus, "INSTALLED_SHA256", "0" * 64), self.assertRaisesRegex(ValueError, "expected packfile"):
            bonus.patch_pack(ORIGINAL)


class BonusImportTests(unittest.TestCase):
    def setUp(self):
        BonusContentTests.setUp(self)
        temporary = tempfile.TemporaryDirectory(prefix="darkwatch-bonus-import-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, LOCALAPPDATA=str(self.root / "LocalAppData"))
        environment.start()
        self.addCleanup(environment.stop)
        self.package = self.root / "package"
        payload = self.package / "payload"
        (payload / "runtime").mkdir(parents=True)
        (payload / "hd_ui").mkdir()
        (payload / "character-art").mkdir()
        for name in ('character_content.py', 'character_animation.py', 'character_assets.py',
                     'character_archive.py', 'character_repaint.py', 'character-catalog.json',
                     'character_boss.py', 'character_boss_effects.py', 'character_spectral_hands.py',
                     'character_hand_seams.py', 'character_secondary.py', 'character_preview.py', 'character_roster.py', 'character_tala.py',
                     'revolver_content.py', 'revolver_scripts.py', 'installed_source.py',
                     'character-art/cassidy-hands-1024.dds', 'character-art/cassidy-hands-256.dds',
                     'character-art/tala-hands-1024.dds', 'character-art/tala-hands-256.dds'):
            (payload/name).write_bytes(b'synthetic character fixture')
        catalog = dict(schema_version=1, kind="darkwatch-gameplay-hd", version="1", texture_catalog_sha256="1" * 64,
                       files=[dict(path="gameplay-hd/example.dwt", size=44, sha256="2" * 64)])
        for name, data in {"intake.py": b"fixture", "bonus_content.py": b"fixture", "gameplay_hd.py": b"fixture",
                           "gameplay-hd-catalog.json": json.dumps(catalog).encode(),
                           "hd_ui/overrides.toml": b"# fixture\n",
                           "runtime/" + setup.EXE: b"fixture executable, never run",
                           "runtime/darkwatch_hd_ui_builder.exe": b"fixture builder, never run"}.items():
            (payload / name).write_bytes(data)
        self.data = {"default.xbe": b"XBEH supported fixture", "packfile.pck": ORIGINAL, "audio.pck": b"untouched sound"}
        disc = dict(xbe_sha256=sha(self.data["default.xbe"]),
                    files=[dict(path=name, size=len(data), sha256=sha(data)) for name, data in self.data.items()])
        (payload / "supported-disc.json").write_text(json.dumps(disc))
        pins = {p.relative_to(self.package).as_posix(): sha(p.read_bytes()) for p in payload.rglob("*") if p.is_file()}
        (self.package / "package-manifest.json").write_text(json.dumps(dict(
            version=setup.PACKAGE_VERSION, complete=True, release_profile=setup.RELEASE_PROFILE,
            runtime_sha256=pins["payload/runtime/" + setup.EXE], files=pins)))
        self.iso = self.root / "original.iso"
        make_iso(self.iso, self.data)
        self.backend = setup.Setup(self.package, self.package / "GameData", notify=lambda *a, **kw: None)
        def fixture_characters(assets, payload, cancel, progress):
            # The archive/retarget adapter is covered separately. Keep these
            # original bonus-selector boundary tests on their tiny fixture.
            target = assets / 'packfile.pck'
            result = bonus.patch_pack(target.read_bytes())
            cancel()
            if sha(result) != bonus.INSTALLED_SHA256:
                raise ValueError('Character conversion verification failed')
            target.write_bytes(result)
        characters = patch.multiple(setup.character_content, prepare=fixture_characters,
                                    INSTALLED={'packfile.pck':(len(EXPECTED),sha(EXPECTED))})
        characters.start()
        self.addCleanup(characters.stop)
        # These selector fixtures are intentionally not PCK archives. Recovery
        # has its own codec/update tests; retain the old-install boundary here.
        recovery = patch.object(setup.installed_source, 'capture',
                                side_effect=lambda assets, output, originals, cancel: cancel())
        recovery.start()
        self.addCleanup(recovery.stop)
        def fixture_preview(assets, output, cancel):
            # Preview parsing is tested against real models elsewhere; this ISO is synthetic.
            cancel()
            data = b'synthetic private preview cache'
            output.write_bytes(data)
            return dict(version=setup.character_preview.VERSION, size=len(data), sha256=sha(data))
        preview = patch.object(setup.character_preview, 'prepare', side_effect=fixture_preview)
        preview.start()
        self.addCleanup(preview.stop)
        for obj, name, replacement in (
            (setup, "require_closed", dict(return_value=None)),
            (setup.subprocess, "Popen", dict(side_effect=AssertionError("No native launch in bonus import tests"))),
            (self.backend, "prepare_shaders", dict(return_value=None)),
            (self.backend, "build_hd", dict(side_effect=lambda stage: (stage / "hd-ui.pack").write_bytes(b"HD fixture"))),
        ):
            mocked = patch.object(obj, name, **replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    def install(self):
        return Path(self.backend.import_iso(self.iso)["install_dir"])

    def snapshot(self):
        return {p.relative_to(self.backend.root).as_posix(): p.read_bytes()
                for p in self.backend.root.rglob("*") if p.is_file()}

    def test_import_preserves_iso_and_verifies_only_expected_transformed_pack(self):
        source = self.iso.read_bytes()
        current = self.install()
        self.assertEqual(self.iso.read_bytes(), source)
        self.assertEqual((current / "assets/packfile.pck").read_bytes(), EXPECTED)
        self.assertEqual((current / "assets/audio.pck").read_bytes(), self.data["audio.pck"])
        self.assertEqual(self.backend.verify(), current)
        for damaged in (ORIGINAL, b"x" + EXPECTED[1:], EXPECTED[:-1]):
            (current / "assets/packfile.pck").write_bytes(damaged)
            with self.assertRaisesRegex(setup.SetupError, "Missing or damaged"):
                self.backend.verify()

    def test_original_portable_install_requires_reimport_and_preserves_latest_state(self):
        previous = self.install()
        metadata = json.loads((previous / "install.json").read_text())
        metadata.pop("content_revision")
        (previous / "install.json").write_text(json.dumps(metadata))
        (previous / "assets/packfile.pck").write_bytes(ORIGINAL)
        (previous / setup.EXE).write_bytes(b"old runtime")
        state = {setup.SETTINGS: b"latest controls", "hdd/E/save.dat": b"latest progress", "cache/a.bin": b"latest cache"}
        for relative, data in state.items():
            target = previous / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.assertFalse(self.backend.status()["ready"])
        with self.assertRaisesRegex(setup.SetupError, "content update"):
            self.backend.verify()
        current = self.install()
        self.assertNotEqual(current, previous)
        self.assertEqual(self.backend.verify(), current)
        self.assertEqual((previous / "assets/packfile.pck").read_bytes(), ORIGINAL)
        for relative, data in state.items():
            self.assertEqual((current / relative).read_bytes(), data)
            self.assertEqual((previous / relative).read_bytes(), data)

    def test_wrong_original_disc_or_mixed_iso_never_publishes_stage(self):
        self.install()
        before = self.snapshot()
        for name, data in (("packfile.pck", EXPECTED), ("audio.pck", b"tampered sound!"),
                           ("default.xbe", b"XBEH unsupported test!")):
            make_iso(self.iso, dict(self.data, **{name: data}))
            with self.assertRaises(setup.SetupError):
                self.install()
            self.assertEqual(self.snapshot(), before)

    def test_failed_or_cancelled_transformation_keeps_active_install(self):
        self.install()
        before = self.snapshot()
        with patch.object(bonus, "INSTALLED_SHA256", "0" * 64), self.assertRaisesRegex(ValueError, "expected packfile"):
            self.install()
        self.assertEqual(self.snapshot(), before)
        with patch.object(bonus, "patch_pack", return_value=bytearray(ORIGINAL)), self.assertRaisesRegex(ValueError, "Character conversion verification"):
            self.install()
        self.assertEqual(self.snapshot(), before)
        cancel = self.root / "cancel"
        original_patch = bonus.patch_pack
        def prepare_then_cancel(source):
            result = original_patch(source)
            cancel.touch()
            return result
        self.backend.cancel_file = cancel
        with patch.object(bonus, "patch_pack", side_effect=prepare_then_cancel), self.assertRaises(setup.Cancelled):
            self.install()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
