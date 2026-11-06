"""Synthetic grip-table validation and standalone importer checks."""
from contextlib import ExitStack
import mmap
import math
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'launcher'))
import character_archive as archive
import character_assets as art
import character_animation as animation
import character_boss as boss
import character_reload as reloads
import character_weapon_pose as poses



class ImportTests(unittest.TestCase):
    def test_no_third_party_runtime_dependency(self):
        result=subprocess.run([sys.executable,'-I','-S','-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import character_weapon_pose',str(ROOT/'launcher')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_shared_grips_reject_unknown_duplicate_and_out_of_range_rows(self):
        row='BODY_WEAPON_GRIP("CassidySolo", "Rifle", 0.025, 0.0)'
        self.assertEqual(poses.read_grip_offsets(row),{('CassidySolo','Rifle'):(.025,0.)})
        for invalid in(row+'\n'+row,row.replace('CassidySolo','CassidyNPC'),row.replace('Rifle','Cannon'),
                        row.replace('0.025','0.081'),row.replace('0.025','nan'),row.replace('0.0)','0.01)'),
                        row+' trailing',row.replace('0.025','..')):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):poses.read_grip_offsets(invalid)
        self.assertEqual(poses.read_grip_offsets()[('BossTalaSolo','BasicPistol')],(.0596478,0.))




if __name__=='__main__':unittest.main()
