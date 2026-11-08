"""Fixed-size pose arithmetic retains Python's exact accumulation behavior."""
from pathlib import Path
import random
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import character_animation as animation
import character_weapon_pose as pose


class FixedPoseMathTests(unittest.TestCase):
    def test_bitwise_equivalent_to_original_ordered_sums(self):
        random_values = random.Random(71107)
        matrices = [((1e16, 1., -1e16), (-0., 0., -0.), (1., 1., 1.))]
        for index in range(3000):
            def value():
                if index < 2000:
                    return random_values.uniform(-8., 8.)
                return random_values.choice((-1., 1.)) * random_values.choice(
                    (0., 2.**-400, 2.**-30, 1., 2.**30, 2.**400))
            matrices.append(tuple(tuple(value() for _ in range(3)) for _ in range(3)))
        for first, second in zip(matrices, matrices[1:] + matrices[:1]):
            expected = tuple(tuple(sum(first[i][k] * second[k][j] for k in range(3))
                                   for j in range(3)) for i in range(3))
            actual = animation._multiply(first, second)
            for old, new in zip(expected, actual):
                self.assertEqual(struct.pack('<3d', *old), struct.pack('<3d', *new))
            expected = tuple(sum(first[0][j] * second[j][i] for j in range(3)) for i in range(3))
            self.assertEqual(struct.pack('<3d', *expected),
                             struct.pack('<3d', *pose.rotate(first[0], second)))


if __name__ == '__main__':
    unittest.main()
