"""Fresh-install choices, preservation across updates, and original data admission."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_launcher_setup as fixtures
import content_profile as profile

class ProfileTests(unittest.TestCase):
    def test_choices_keep_old_receipts_enhanced_and_reject_switching(self):
        self.assertEqual(profile.choose({}), 'original')
        self.assertEqual(profile.choose({}, 'enhanced'), 'enhanced')
        self.assertEqual(profile.choose({'content_revision': 'old'}), 'enhanced')
        self.assertEqual(profile.choose({'content_profile': 'original'}), 'original')
        for previous, requested in (({'content_revision': 'old'}, 'original'),
                                    ({'content_profile': 'original'}, 'enhanced')):
            with self.assertRaises(ValueError): profile.choose(previous, requested)
        for bad in ('', None, 'typo'):
            with self.assertRaises(ValueError): profile.selected({'content_profile': bad})

    def test_real_transaction_original_fresh_install_update_and_repair(self):
        case = fixtures.LauncherSetupTests('test_incremental_update_payload_must_be_complete')
        fixtures.LauncherSetupTests.setUpClass()
        self.addCleanup(fixtures.LauncherSetupTests.tearDownClass)
        case.setUp()
        try:
            pins = dict(fixtures.characters.INSTALLED)
            catalog = {'originals': {name: {'size': len(case.data[name]), 'sha256': fixtures.sha(case.data[name])} for name in pins}}
            with patch.object(profile, 'ORIGINAL', pins), patch.object(fixtures.characters, 'catalog', return_value=catalog), \
                    patch.object(fixtures.characters, 'prepare', side_effect=AssertionError('Enhanced conversion must not run')), \
                    patch.object(fixtures.setup.character_preview, 'prepare', side_effect=AssertionError('Original previews must not run')):
                current = Path(case.backend.use_iso(case.iso)['install_dir'])
                receipt = json.loads((current/'install.json').read_text())
                self.assertEqual(receipt['content_profile'], 'original')
                self.assertEqual(receipt['content_revision'], profile.ORIGINAL_REVISION)
                preview = current / fixtures.setup.character_preview.NAME
                self.assertFalse(preview.exists())
                self.assertNotIn('character_preview', receipt)
                # Older original installs retain an unused cache; a revision rebuild removes it.
                preview.write_bytes(b'obsolete generated preview')
                receipt['character_preview'] = {'version': 0}
                receipt['content_revision'] = 'previous-original-revision'
                (current/'install.json').write_text(json.dumps(receipt))
                self.assertTrue(case.backend.update()['ready'])
                self.assertFalse(preview.exists())
                self.assertNotIn('character_preview', json.loads((current/'install.json').read_text()))
                self.assertEqual(case.backend.verify(), current)
                self.assertEqual((current/'assets/packfile.pck').read_bytes(), case.installed_data['packfile.pck'])
                self.assertTrue(case.backend.status()['ready'])
                self.assertTrue(case.backend.update()['ready'])
                self.assertTrue(case.backend.use_iso(case.iso)['ready'])
                before = (current/'install.json').read_bytes()
                with self.assertRaises(ValueError): case.backend.import_iso(case.iso, profile='enhanced')
                self.assertEqual(before, (current/'install.json').read_bytes())
                self.assertEqual(case.backend.active(), current)
        finally:
            case.doCleanups()
