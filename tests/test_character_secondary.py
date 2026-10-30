"""Synthetic checks for authored character weighting bounds."""
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'launcher'))
import character_animation as animation
import character_boss as boss
import character_secondary as secondary
import character_spectral_hands as hands


def matrices(raw, leg_angles=None):
    rig, frames, _ = boss.rig(raw, 51)
    rotations = {rig[bone]['frame']: angle for bone, angle in (leg_angles or {}).items()}
    world = []
    for index, frame in enumerate(frames):
        local = [list(frame[i:i+3])+[0.] for i in (0, 3, 6)] + [list(frame[9:12])+[1.]]
        if index in rotations:
            c, s = math.cos(rotations[index]), math.sin(rotations[index])
            turn = ((1., 0., 0.), (0., c, s), (0., -s, c))
            local[:3] = [[sum(local[r][k]*turn[k][col] for k in range(3))
                          for col in range(3)]+[0.] for r in range(3)]
        parent = frame[12]
        if parent > 0:
            local = [[sum(local[r][k]*world[parent][k][c] for k in range(4))
                      for c in range(4)] for r in range(4)]
        world.append(local)
    return [world[rig[i]['frame']] for i in range(51)]


def vertex_pose(point, weights, inverse, world):
    result = [0., 0., 0.]
    for bone, weight in weights.items():
        local = hands._point(point, inverse[bone])
        for i in range(3):
            result[i] += weight*(sum(local[j]*world[bone][j][i] for j in range(3))+world[bone][3][i])
    return result


def animation_pose(model, data, time):
    """Sample real unblended disc keys; missing tracks retain their bind pose."""
    _, sections = animation.sections(data)
    rig, frames, _ = boss.rig(model, 51)
    frame_bones = {row['frame']: bone for bone, row in rig.items()}
    def value(bit, bone):
        section = sections.get(bit)
        if not section or bone is None or bone >= 22:
            return None
        start = section['indices'][bone]
        if start == 0xffffffff:
            return None
        stop = min([i for i in section['indices'] if start < i < 0xffffffff]+[section['count']])
        keys = []
        for key in range(start, stop):
            at = section['keys']+key*section['stride']
            values = struct.unpack_from('<4h' if bit == 4 else '<3f', data, at+4)
            keys.append((struct.unpack_from('<f', data, at)[0],
                         tuple(v/32768 for v in values) if bit == 4 else values))
        a = keys[0]
        for b in keys[1:]:
            if b[0] >= time:
                f = min(1., max(0., (time-a[0])/(b[0]-a[0]))) if b[0] > a[0] else 0.
                other = b[1]
                if bit == 4 and sum(x*y for x, y in zip(a[1], other)) < 0:
                    other = tuple(-v for v in other)
                result = tuple(x*(1-f)+y*f for x, y in zip(a[1], other))
                break
            a = b
        else:
            result = a[1]
        length = math.sqrt(sum(v*v for v in result)) if bit == 4 else 1.
        return tuple(v/length for v in result)
    world = []
    for index, frame in enumerate(frames):
        local = [list(frame[i:i+3])+[0.] for i in (0, 3, 6)]+[list(frame[9:12])+[1.]]
        if index == 0:
            local = [[float(i == j) for j in range(4)] for i in range(4)]
        bone = frame_bones.get(index)
        rotation, translation = value(4, bone), value(8, bone)
        if rotation is not None:
            local[:3] = [list(row)+[0.] for row in animation._quaternion_matrix(rotation)]
        if translation is not None:
            local[3][:3] = translation
        parent = frame[12]
        if parent >= 0:
            local = [[sum(local[i][k]*world[parent][k][j] for k in range(4))
                      for j in range(4)] for i in range(4)]
        world.append(local)
    return [world[rig[i]['frame']] for i in range(51)]


class InfluenceTests(unittest.TestCase):
    def test_local_smooth_bounded_regions(self):
        for joint, center in enumerate(secondary.REGION_CENTERS):
            self.assertGreater(secondary.influence(center, joint), .5)
            self.assertEqual(secondary.influence((0., center[1], center[2]), joint), 0.)
            self.assertEqual(secondary.influence((-center[0], center[1], center[2]), joint), 0.)
            for x in range(-25, 26):
                for y in range(-45, 55):
                    value = secondary.influence((x/100, y/100, center[2]), joint)
                    self.assertGreaterEqual(value, 0.)
                    self.assertLessEqual(value, .65)
            if joint >= 2:
                self.assertEqual(secondary.influence((center[0], .065, center[2]), joint), 0.)
                self.assertEqual(secondary.influence((center[0], -.32, center[2]), joint), 0.)
                self.assertEqual(secondary.influence((center[0], -.15, .12), joint), 0.)
        self.assertEqual(secondary.PARENTS, (8, 8, 0, 0, 4, 1))
        self.assertEqual(secondary.CENTERS, ((.075, .33, .15), (-.075, .33, .15),
                                           (.085, -.015, -.105), (-.085, -.015, -.105)))
        for y in range(-31, 7):
            p = (.10, y/100, -.09)
            self.assertEqual(secondary.influence(p, 2), secondary.influence(p, 4))




if __name__ == '__main__':
    unittest.main()
