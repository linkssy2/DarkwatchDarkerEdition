"""Launcher animation conversion: synthetic contracts without game resources.

No game is launched and no generated resource is saved by these tests.
"""
import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('character_animation', ROOT / 'launcher/character_animation.py')
animation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(animation)


def model():
    def chunk(tag, data):
        return struct.pack('<III', tag, len(data), 0) + data
    identity = (1., 0., 0., 0., 1., 0., 0., 0., 1.)
    transforms = b''.join(struct.pack('<12f2i', *identity, 1., 0., 0., i - 1, 0) for i in range(23))
    frames = chunk(1, struct.pack('<I', 23) + transforms) + chunk(3, b'')
    frames += b''.join(chunk(3, chunk(0x11e, struct.pack('<III', 0, bone, 0))) for bone in range(22))
    return chunk(16, chunk(14, frames))


def clip(packed=False):
    # One indexed pose per bone plus opaque native event/path words.
    flags = 0x4000001b | (32 if packed else 4)
    result = bytearray(struct.pack('<IIIfII', 16, 0xf11e0006, 22, 1., 7, flags))
    for bit, _ in animation.ORDER:
        if not flags & bit:
            continue
        count = 22 if bit in (4, 8, 32) else 2
        result += struct.pack('<I', count)
        if bit in (4, 8, 32):
            result += struct.pack('<22I', *range(22))
        if bit == 4:
            result += struct.pack('<f4h', .25, 0, 0, 0, 32767) * count
        elif bit == 32:
            result += struct.pack('<fI', .25, 0) * count
        elif bit == 8:
            result += struct.pack('<4f', .25, 3., 0., 0.) * count
        else:
            result += struct.pack('<II', 0xDEADBEEF, 0x01234567)
    return bytes(result)


class CharacterAnimationTests(unittest.TestCase):
    def test_runtime_import_needs_only_standard_library(self):
        path = ROOT / 'launcher/character_animation.py'
        imports = {n.names[0].name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Import)}
        self.assertEqual(imports, {'hashlib', 'math', 'struct'})
        self.assertFalse(any(isinstance(n, ast.ImportFrom) for n in ast.walk(ast.parse(path.read_text()))))
        result = subprocess.run([sys.executable, '-B', '-I', '-S', '-c',
                                 'import runpy,sys; runpy.run_path(sys.argv[1])', str(path)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hierarchy_rotation_translation_and_identity_keys(self):
        source = animation.frames(model())
        self.assertEqual(len(source), 22)
        raw = clip()
        unchanged, count = animation.retarget(raw, animation.parameters(source, source))
        self.assertEqual(unchanged, raw)
        self.assertEqual(count, 0)
        target = {i: dict(row) for i, row in source.items()}
        target[0]['translation'] = (2., 0., 0.)
        target[0]['rotation'] = (0., 1., 0., -1., 0., 0., 0., 0., 1.)
        adapted, count = animation.retarget(raw, animation.parameters(source, target))
        self.assertEqual(count, 2)
        _, sections = animation.sections(adapted)
        self.assertEqual(struct.unpack_from('<4f', adapted, sections[8]['keys']), (.25, 6., 0., 0.))
        self.assertEqual(struct.unpack_from('<4h', adapted, sections[4]['keys'] + 4), (0, 0, 23170, 23170))
        animation.verify_preserved(raw, adapted)
        # Rest-pose changes must never rewrite unmodified neighboring bones.
        for bit in (4, 8):
            p = sections[bit]
            self.assertEqual(raw[p['keys'] + p['stride']:p['end']], adapted[p['keys'] + p['stride']:p['end']])

    def test_packed_quaternions_expand_without_changing_times_or_events(self):
        raw = clip(packed=True)
        expanded = animation.expand(raw)
        self.assertEqual(expanded, clip())
        animation.verify_preserved(raw, expanded)
        for word in (0, 1, 0x3ffff, 0x10000000, 0xA7654321, 0xffffffff):
            q = animation.decode_word(word)
            self.assertAlmostEqual(sum(v*v for v in q), 1., places=13)
            self.assertTrue(all(math.isfinite(v) for v in q))
        for word in (-1, 0x100000000):
            with self.assertRaises(ValueError):
                animation.decode_word(word)

    def test_malformed_models_and_animations_fail_closed(self):
        raw, rig = clip(), model()
        for bad in (rig[:-1], rig + b'x', b'', struct.pack('<III', 16, 0xffffffff, 0)):
            with self.subTest(model_length=len(bad)), self.assertRaises(ValueError):
                animation.frames(bad)
        _, sections = animation.sections(raw)
        invalid = [raw[:n] for n in (0, 23, 24, 27, len(raw)-1)] + [raw + b'x']
        for at, fmt, value in ((0, '<I', 0), (8, '<I', 23), (12, '<f', float('nan')),
                               (sections[4]['start'] + 4, '<I', 22),
                               (sections[4]['start'] + 8, '<I', 21),
                               (sections[8]['keys'] + 4, '<f', float('inf'))):
            bad = bytearray(raw); struct.pack_into(fmt, bad, at, value); invalid.append(bad)
        for bad in invalid:
            with self.subTest(animation_length=len(bad)), self.assertRaises(ValueError):
                animation.sections(bad)
        source = animation.frames(rig)
        target = {i: dict(row) for i, row in source.items()}
        target[0]['parent'] = 22
        with self.assertRaises(ValueError):
            animation.parameters(source, target)
        target[0] = dict(source[0], rotation=(0.,)*9)
        with self.assertRaises(ValueError):
            animation.parameters(source, target)
        mutated = bytearray(raw); struct.pack_into('<f', mutated, sections[4]['keys'], .5)
        with self.assertRaises(ValueError):
            animation.verify_preserved(raw, mutated)
        mutated = bytearray(raw); mutated[sections[1]['keys']] ^= 1
        with self.assertRaises(ValueError):
            animation.verify_preserved(raw, mutated)
        for bad in ('../a', '/a', 'a//b', 'a/./b', 'c:/a'):
            with self.assertRaises(ValueError):
                animation._norm(bad)



if __name__ == '__main__':
    unittest.main()
