"""Disc-derived skin continuity, nail protection and hand-only texture changes."""
import importlib.util
import math
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'launcher'))
import character_boss as boss
import character_hand_seams as seams
import character_repaint as rw
import character_spectral_hands as hands


def textures(raw):
    result = {}
    for tag, dictionary in rw.chunks(raw):
        if tag == 0x16:
            for child, native in rw.chunks(dictionary, 12):
                if child == 0x15:
                    for kind, value in rw.chunks(native, 12):
                        if kind == 1:
                            name = value[20:52].split(b'\0')[0]
                            width, height = struct.unpack_from('<HH', value, 92)
                            result[name, width, height] = value
    return result


def decode32(value):
    width, height = struct.unpack_from('<HH', value, 92)
    payload = value[104:]
    output = bytearray(width*height*4)
    for y in range(height):
        for x in range(width):
            at = seams._address(x, y, width, height)*4
            output[(y*width+x)*4:(y*width+x)*4+4] = payload[at:at+4]
    return bytes(output)


def recipe(data):
    version, count, pairs, protected, iterations, reserved = struct.unpack_from('<6I', data, 8)
    assert (data[:8], version, count, iterations, reserved) == (b'DWHSEAM1', 1, 2, 12, 0)
    assert len(data) == 32+40*count+32*pairs+16*protected+8
    assert seams.fnv(data[:-8]) == struct.unpack_from('<Q', data, len(data)-8)[0]
    aliases = [struct.unpack_from('<6IQQ', data, 32+i*40) for i in range(count)]
    offset = 32+count*40
    edges = []
    for i in range(pairs):
        values = struct.unpack_from('<8f', data, offset+i*32)
        edges.append(((values[:2], values[2:4]), (values[4:6], values[6:8])))
    offset += pairs*32
    rectangles = [struct.unpack_from('<4f', data, offset+i*16) for i in range(protected)]
    return aliases, edges, rectangles


def error(pixels, width, height, edges):
    differences = []
    for pair in edges:
        for t in range(21):
            colors = [seams._sample(pixels, width, height,
                       a[0]+(b[0]-a[0])*t/20, a[1]+(b[1]-a[1])*t/20) for a, b in pair]
            differences.append(max(abs(a-b) for a, b in zip(*colors)))
    return sum(differences)/len(differences)


class SeamUnit(unittest.TestCase):
    def test_dependency_free_import(self):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import character_hand_seams', str(ROOT/'launcher')],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_wrapped_bilinear_and_protection(self):
        pixels = bytes([20, 40, 60, 255, 100, 120, 140, 255]*2)
        self.assertEqual(seams._sample(pixels, 2, 2, .25, .25), (20., 40., 60.))
        self.assertEqual(seams._sample(pixels, 2, 2, 0., .25), (60., 80., 100.))
        pair = (((.25, .25), (.25, .75)), ((.75, .25), (.75, .75)))
        self.assertEqual(seams.repair(pixels, 2, 2, [pair], [(0., 0., 1., 1.)]), pixels)




if __name__ == '__main__':
    unittest.main()
