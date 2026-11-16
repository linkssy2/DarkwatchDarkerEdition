"""Resource batches preserve exact serial output, order and worker cleanup."""
import multiprocessing
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import character_assets as art
from test_character_resource_append import resource_tree


class ResourceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.children = {child.pid for child in multiprocessing.active_children()}
        self.raw = art.encode(resource_tree([('Body', 'ModelResource')]))
        self.profiles = [([('base', 'ModelResource')], [
            (('body', 'ModelResource'), [('selected', 'AnimationResource')]),
            (('absent', 'ModelResource'), [('wrong', 'AnimationResource')])]), ((), ())]

    def tearDown(self):
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, self.children)

    def test_exact_serial_bytes_and_input_order(self):
        jobs = [(str(i), self.raw, i % 2) for i in range(67)]
        actual = list(art.append_resource_jobs(jobs, self.profiles, lambda: None))
        expected = []
        for path, raw, profile in jobs:
            base, choices = self.profiles[profile]
            def select(present):
                return list(base) + [dep for key, deps in choices if key in present for dep in deps]
            converted, added = art.append_resource_bytes(raw, select=select)
            expected.append((path, converted, bool(added)))
        self.assertEqual(actual, expected)

    def test_malformed_input_propagates_and_workers_exit(self):
        with self.assertRaises((ValueError, IndexError)):
            list(art.append_resource_jobs([('bad', b'bad', 0)], self.profiles, lambda: None))

    def test_cancel_during_queued_work_and_generator_close(self):
        for close in (False, True):
            cancelled = False
            def cancel():
                if cancelled:
                    raise InterruptedError('cancelled')
            jobs = ((str(i), self.raw, 0) for i in range(1000))
            results = art.append_resource_jobs(jobs, self.profiles, cancel)
            next(results)
            if close:
                results.close()
            else:
                cancelled = True
                with self.assertRaisesRegex(InterruptedError, 'cancelled'):
                    next(results)

    def test_input_reader_failure_cleans_queued_work(self):
        def jobs():
            for i in range(20):
                yield str(i), self.raw, 0
            raise OSError('source changed')
        with self.assertRaisesRegex(OSError, 'source changed'):
            list(art.append_resource_jobs(jobs(), self.profiles, lambda: None))


if __name__ == '__main__':
    unittest.main()
