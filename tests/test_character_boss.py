"""Offline spectral body conversion contracts; no game or installed archive writes."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'launcher'))
import character_animation as animation
import character_assets as assets
import character_boss as boss


def synthetic(bones, packed=False, events=True):
    flags = (32 if packed else 4) | 8 | (1|2|16 if events else 0) | 0x40000000
    output = bytearray(struct.pack('<IIIfII',40,0xf11e0006,bones,1.,0,flags))
    for bit,stride in animation.ORDER:
        if not flags & bit:
            continue
        if bit == 1:
            output += struct.pack('<I',bones)+struct.pack('<'+'I'*bones,*(i%2 for i in range(bones)))
            continue
        if bit not in (4,8,32):
            output += struct.pack('<III',2,0x12345678,0xabcdef01); continue
        output += struct.pack('<I',2*bones)+struct.pack('<'+'I'*bones,*(2*i for i in range(bones)))
        for bone in range(bones):
            for time in (0.,1.):
                if bit == 8:
                    output += struct.pack('<4f',time,float(bone),2.,3.)
                elif bit == 32:
                    output += struct.pack('<fI',time,0x10000 if time else 0)
                else:
                    output += struct.pack('<f4h',time,0,0,100 if time else 0,32767)
    return bytes(output)


def collapse(data, original):
    """Test-only inverse of 22->51 tracks/mask expansion, with source flags."""
    _,parts = boss.sections(data,51)
    output = bytearray(data[:24]);struct.pack_into('<I',output,8,22)
    source_flags=struct.unpack_from('<I',original,20)[0]
    struct.pack_into('<I',output,20,source_flags)
    for bit,_ in animation.ORDER:
        if bit not in parts:
            continue
        row = parts[bit]
        if bit == 1:
            values=struct.unpack_from('<51I',data,row['keys'])
            if values[22:] != (1,)*29:
                raise AssertionError('Player layer does not exclude wing bones')
            if source_flags & 1:
                output += struct.pack('<I',22)+data[row['keys']:row['keys']+88]
            elif values[:22] != (0,)*22:
                raise AssertionError('Unmasked player bones changed')
            continue
        if row['indices']:
            if row['indices'][22:] != (boss.MISSING,)*29:
                raise AssertionError('Player layer acquired wing tracks')
            output += struct.pack('<I',row['count'])+struct.pack('<22I',*row['indices'][:22])
            output += data[row['keys']:row['end']]
        else:
            output += data[row['start']:row['end']]
    return bytes(output)


class SyntheticTests(unittest.TestCase):
    def test_player_events_pose_bytes_and_absent_tracks_preserved(self):
        for packed in (False,True):
            raw = synthetic(22,packed)
            self.assertEqual(collapse(boss.expand_player(raw),raw),raw)
            raw=synthetic(22,packed,events=False)
            self.assertEqual(collapse(boss.expand_player(raw),raw),raw)
        raw = bytearray(synthetic(22))
        _,parts=animation.sections(raw)
        for bit in (4,8):
            struct.pack_into('<I',raw,parts[bit]['start']+4+4*10,boss.MISSING)
        self.assertEqual(collapse(boss.expand_player(raw),raw),raw)

    def test_malformed_animation_rejected(self):
        raw=synthetic(22)
        for invalid in (raw[:23],raw[:-1],raw+b'x'):
            with self.assertRaises(ValueError):boss.expand_player(invalid)
        invalid=bytearray(raw);struct.pack_into('<I',invalid,8,51)
        with self.assertRaises(ValueError):boss.expand_player(invalid)
        invalid=bytearray(raw);struct.pack_into('<I',invalid,24,21)
        with self.assertRaises(ValueError):boss.expand_player(invalid)


PINS=ROOT/'launcher/character-catalog.json'




if __name__=='__main__':unittest.main()
