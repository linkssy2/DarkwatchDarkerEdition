"""Original-disc checks for complete boss arms adapted to the native POV rig."""
from collections import Counter
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'launcher'))
import character_boss as boss
import character_boss_effects as effects
import character_hand_seams as seams
import character_repaint as rw
import character_spectral_hands as hands


class SpectralImport(unittest.TestCase):
    def test_helpers_import_without_site_packages(self):
        result = subprocess.run([sys.executable,'-I','-S','-B','-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import character_boss_effects',str(ROOT/'launcher')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)




if __name__ == '__main__':
    unittest.main()
