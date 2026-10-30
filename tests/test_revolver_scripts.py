"""Pinned campaign edits; original-asset witness stays private to this workspace."""
import importlib.util
from pathlib import Path
import sys

import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import revolver_scripts


class RevolverScriptTests(unittest.TestCase):
    def test_rejects_unrecognized_target_bytes_without_touching_other_scripts(self):
        for path in revolver_scripts.SCRIPT_PATHS:
            with self.assertRaisesRegex(ValueError, 'Unsupported starting-revolver script'):
                revolver_scripts.patch_script(path, b'not the supported original script')
        raw = b'unrelated script bytes'
        self.assertIs(revolver_scripts.patch_script('scripts/removeinventory.lobj', raw), raw)





if __name__ == '__main__':
    unittest.main()
