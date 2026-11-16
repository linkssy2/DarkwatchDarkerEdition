"""Parallel preparation with checked files for bulk process inputs and outputs."""
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import hashlib
import io
import multiprocessing
import os
from pathlib import Path
import pickle
import sys
import tempfile
import uuid


class _RawPickler(pickle.Pickler):
    def __init__(self, stream, raw):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        self.raw, self.references = raw, {}

    def persistent_id(self, value):
        if type(value) is not bytes:
            return None
        previous = self.references.get(id(value))
        if previous is not None:
            return previous[1]
        reference = ('raw-bytes', len(self.references), self.raw.tell(),
                     len(value), hashlib.sha256(value).hexdigest())
        if self.raw.write(value) != len(value):
            raise OSError('Incomplete preparation worker payload')
        self.references[id(value)] = value, reference
        return reference


class _RawUnpickler(pickle.Unpickler):
    def __init__(self, stream, raw):
        super().__init__(stream)
        self.raw, self.references = raw, {}
        self.raw_size = os.fstat(raw.fileno()).st_size

    def persistent_load(self, reference):
        if (type(reference) is not tuple or len(reference) != 5 or
                reference[0] != 'raw-bytes' or
                any(type(value) is not int or value < 0 for value in reference[1:4]) or
                type(reference[4]) is not str or len(reference[4]) != 64 or
                any(char not in '0123456789abcdef' for char in reference[4])):
            raise pickle.UnpicklingError('Invalid preparation worker payload reference')
        _, index, offset, size, digest = reference
        if index in self.references:
            previous, value = self.references[index]
            if previous != reference:
                raise pickle.UnpicklingError('Conflicting preparation worker payload reference')
            return value
        if offset + size > self.raw_size:
            raise ValueError('Preparation worker payload verification failed')
        self.raw.seek(offset)
        value = self.raw.read(size)
        if len(value) != size or hashlib.sha256(value).hexdigest() != digest:
            raise ValueError('Preparation worker payload verification failed')
        self.references[index] = reference, value
        return value

    def verify(self):
        for reference, value in self.references.values():
            if len(value) != reference[3] or hashlib.sha256(value).hexdigest() != reference[4]:
                raise ValueError('Preparation worker payload verification failed after reconstruction')


def _write(value, folder):
    path = Path(folder) / (uuid.uuid4().hex + '.pickle')
    with path.with_suffix('.raw').open('xb') as raw, io.BytesIO() as metadata:
        _RawPickler(metadata, raw).dump(value)
        data = metadata.getvalue()
    reference = str(path), len(data), hashlib.sha256(data).hexdigest()
    with path.open('xb') as stream:
        if stream.write(data) != len(data):
            raise OSError('Incomplete preparation worker file')
    return reference


def _read(reference, *, keep=False):
    path, size, digest = reference
    data = Path(path).read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Preparation worker data verification failed')
    raw_path = Path(path).with_suffix('.raw')
    with raw_path.open('rb') as raw, io.BytesIO(data) as metadata:
        decoder = _RawUnpickler(metadata, raw)
        value = decoder.load()
        decoder.verify()
    if not keep:
        Path(path).unlink()
        raw_path.unlink()
    return value


def _initialize(initializer, reference, stopped):
    if initializer is not None:
        initializer(*_read(reference, keep=True), stopped)


def _call(function, reference, folder):
    return _write(function(*_read(reference)), folder)


def result(future):
    """Verify the exact bytes received before deserializing a completed result."""
    return _read(future.result())


class _Jobs:
    def __init__(self, executor, folder):
        self.executor, self.folder = executor, folder

    def submit(self, function, *args):
        reference = _write(args, self.folder)
        return self.executor.submit(_call, function, reference, self.folder)


@contextmanager
def pool(workers, *, initializer=None, initargs=(), stopped=None):
    # Keep resource bytes out of bulk serialization and verify after reconstruction.
    if os.name == 'nt':
        multiprocessing.set_executable(str(Path(sys._base_executable).with_name('python.exe')))
    with tempfile.TemporaryDirectory(prefix='darkwatch-preparation-') as folder:
        reference = _write(initargs, folder) if initializer is not None else None
        with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context('spawn'),
                initializer=_initialize, initargs=(initializer, reference, stopped)) as executor:
            yield _Jobs(executor, folder)
