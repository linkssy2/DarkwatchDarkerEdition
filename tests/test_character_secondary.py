"""Synthetic checks for authored character weighting bounds."""
import hashlib
import json
import math
from pathlib import Path
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
