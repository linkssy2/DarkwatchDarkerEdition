"""Checked bulk handoffs reject corruption and clean up after worker failures."""
from concurrent.futures import Future
import hashlib
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import character_workers as workers


_initial = None


def initialize(data, stopped):
    global _initial
    _initial = data, stopped


def echo(data):
    if _initial is not None:
        original, stopped = _initial
        if stopped.is_set():
            raise RuntimeError('cancelled')
        assert original == data
    return [memoryview(data).tobytes() for _ in range(4)]


def fail():
    raise ValueError('worker conversion failed')


def mark_called(path, data):
    Path(path).write_text('called')
    return data


def fail_initialize(stopped):
    raise ValueError('initializer failed')


class WorkerFileTests(unittest.TestCase):
    def test_large_input_initializer_and_result_remain_exact(self):
        original = bytes(range(256)) * 8193
        stopped = multiprocessing.get_context('spawn').Event()
        with workers.pool(2, initializer=initialize,
                          initargs=(original,), stopped=stopped) as pool:
            folder = Path(pool.folder)
            jobs = [pool.submit(echo, original) for _ in range(8)]
            for job in jobs:
                self.assertEqual(workers.result(job), [original] * 4)
            self.assertEqual(len(list(folder.iterdir())), 2)  # Shared initializer metadata/raw pair.
        self.assertFalse(folder.exists())

    def test_corrupted_and_truncated_files_rejected_before_unpickle(self):
        for change in ('zero', 'truncate'):
            with tempfile.TemporaryDirectory() as folder:
                reference = workers._write(b'original nonzero bytes' * 100, folder)
                path = Path(reference[0])
                raw = bytearray(path.read_bytes())
                if change == 'zero':
                    raw[30] = 0
                else:
                    raw.pop()
                path.write_bytes(raw)
                future = Future()
                future.set_result(reference)
                with patch.object(workers, '_RawUnpickler') as decode:
                    with self.assertRaisesRegex(ValueError, 'verification failed'):
                        workers.result(future)
                    decode.assert_not_called()

    def test_raw_bytes_bypass_pickle_and_preserve_shared_object_state(self):
        from types import SimpleNamespace
        original = bytes(range(256)) * 4096
        value = SimpleNamespace(data=original, nested=[original, {'clip': original}], label='metadata')
        with tempfile.TemporaryDirectory() as folder:
            reference = workers._write(value, folder)
            path = Path(reference[0])
            self.assertEqual(path.with_suffix('.raw').read_bytes(), original)
            self.assertLess(path.stat().st_size, 1024)
            restored = workers._read(reference)
            self.assertEqual(restored.data, original)
            self.assertIs(restored.data, restored.nested[0])
            self.assertIs(restored.data, restored.nested[1]['clip'])
            self.assertEqual(restored.label, 'metadata')
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix('.raw').exists())

    def test_same_size_raw_input_corruption_rejected_before_worker_call(self):
        original_write = workers._write
        def corrupt(value, folder):
            reference = original_write(value, folder)
            path = Path(reference[0]).with_suffix('.raw')
            raw = path.read_bytes()
            path.write_bytes(b'\0' + raw[1:])
            return reference
        with tempfile.TemporaryDirectory() as evidence:
            marker = Path(evidence) / 'called'
            with self.assertRaisesRegex(ValueError, 'payload verification failed'):
                with workers.pool(1) as pool:
                    folder = Path(pool.folder)
                    with patch.object(workers, '_write', side_effect=corrupt):
                        job = pool.submit(mark_called, str(marker), b'original nonzero data')
                    workers.result(job)
            self.assertFalse(marker.exists())
            self.assertFalse(folder.exists())

    def test_same_size_raw_result_corruption_rejected_before_acceptance(self):
        with self.assertRaisesRegex(ValueError, 'payload verification failed'):
            with workers.pool(1) as pool:
                folder = Path(pool.folder)
                reference = pool.submit(echo, b'original nonzero data').result(timeout=15)
                path = Path(reference[0]).with_suffix('.raw')
                raw = path.read_bytes()
                path.write_bytes(b'\0' + raw[1:])
                future = Future()
                future.set_result(reference)
                workers.result(future)
        self.assertFalse(folder.exists())

    def test_reconstruction_checks_the_accepted_payload_objects_again(self):
        original_load = workers._RawUnpickler.load
        def changed(decoder):
            original_load(decoder)
            reference, data = decoder.references[0]
            changed_value = b'\0' + data[1:]
            decoder.references[0] = reference, changed_value
            return changed_value
        with tempfile.TemporaryDirectory() as folder:
            reference = workers._write(b'original', folder)
            with patch.object(workers._RawUnpickler, 'load', changed):
                with self.assertRaisesRegex(ValueError, 'after reconstruction'):
                    workers._read(reference)

    def test_worker_failure_and_unconsumed_results_remove_owned_files(self):
        with self.assertRaisesRegex(ValueError, 'worker conversion failed'):
            with workers.pool(2) as pool:
                folder = Path(pool.folder)
                jobs = [pool.submit(echo, b'input') for _ in range(8)]
                workers.result(pool.submit(fail))
        self.assertFalse(folder.exists())
        self.assertTrue(all(job.done() for job in jobs))

    def test_input_corruption_fails_worker_and_cleans_pool(self):
        original_write = workers._write
        def corrupt(value, folder):
            reference = original_write(value, folder)
            Path(reference[0]).write_bytes(b'broken')
            return reference
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            with workers.pool(1) as pool:
                folder = Path(pool.folder)
                with patch.object(workers, '_write', side_effect=corrupt):
                    job = pool.submit(echo, b'original')
                workers.result(job)
        self.assertFalse(folder.exists())

    def test_scratch_write_failure_cleans_pool(self):
        with self.assertRaisesRegex(OSError, 'scratch unavailable'):
            with workers.pool(1) as pool:
                folder = Path(pool.folder)
                with patch.object(workers, '_write', side_effect=OSError('scratch unavailable')):
                    pool.submit(echo, b'original')
        self.assertFalse(folder.exists())

    def test_missing_or_invalid_serialized_result_cleans_pool(self):
        for missing in (False, True):
            with self.assertRaises((FileNotFoundError, workers.pickle.UnpicklingError)):
                with workers.pool(1) as pool:
                    folder = Path(pool.folder)
                    reference = pool.submit(echo, b'original').result(timeout=15)
                    path = Path(reference[0])
                    if missing:
                        path.unlink()
                    else:
                        data = b'invalid pickle'
                        path.write_bytes(data)
                        reference = (str(path), len(data), hashlib.sha256(data).hexdigest())
                    future = Future()
                    future.set_result(reference)
                    workers.result(future)
            self.assertFalse(folder.exists())

    def test_initializer_failure_cleans_pool(self):
        from concurrent.futures.process import BrokenProcessPool
        with self.assertRaises(BrokenProcessPool):
            with workers.pool(1, initializer=fail_initialize) as pool:
                folder = Path(pool.folder)
                workers.result(pool.submit(echo, b'original'))
        self.assertFalse(folder.exists())


if __name__ == '__main__':
    unittest.main()
