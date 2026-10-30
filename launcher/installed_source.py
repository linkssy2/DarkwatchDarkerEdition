"""Keep private PCK indexes so installed payloads can rebuild their original inputs.

Only a caller-owned, uncommitted stage may receive capture/restore output. No
game bytes are supplied by the launcher; every restored archive must match its disc pin.
"""
import hashlib
import os
from pathlib import Path
import re
import struct

import bonus_content
import intake

CHUNK = 8 * 1024 * 1024
MAX_TAIL = 16 * 1024 * 1024


def checked(root, name):
    intake.safe_component(name.encode('ascii'))
    path = intake.safe_destination(Path(root), name)
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('Source recovery requires regular, unlinked files: ' + name)
    return path


def tail_start(footer, size):
    if len(footer) != 8:
        raise ValueError('Truncated source recovery footer')
    start, marker = struct.unpack('<II', footer)
    if marker != 0xfffffffb or not 0 < start < size - 40 or size - start > MAX_TAIL:
        raise ValueError('Invalid source recovery bounds')
    return start


def validate_pin(pin):
    if (type(pin.get('size')) is not int or pin['size'] < 56 or
            not isinstance(pin.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256'])):
        raise ValueError('Invalid original archive pin')


def read_tail(recovery, name, pin):
    validate_pin(pin)
    path = checked(recovery, name + '.tail')
    if not 40 < path.stat().st_size <= MAX_TAIL:
        raise ValueError('Invalid source recovery size: ' + name)
    with path.open('rb') as stream:
        tail = stream.read(MAX_TAIL + 1)
    start = tail_start(tail[-8:], pin['size'])
    if len(tail) != pin['size'] - start:
        raise ValueError('Source recovery extent differs: ' + name)
    return start, tail


def has_recovery(recovery, originals):
    """Check availability only; restore authenticates the recovered full archives."""
    try:
        return bool(originals) and all(read_tail(recovery, name, pin) for name, pin in originals.items())
    except (OSError, ValueError):
        return False


def capture(assets, recovery, originals, cancel=lambda: None):
    for name, pin in originals.items():
        validate_pin(pin)
        cancel()
        source, destination = checked(assets, name), checked(recovery, name + '.tail')
        with source.open('rb') as stream:
            if os.fstat(stream.fileno()).st_size != pin['size']:
                raise ValueError('Original archive size differs: ' + name)
            stream.seek(-8, 2)
            start = tail_start(stream.read(8), pin['size'])
            stream.seek(0)
            digest, position, tail = hashlib.sha256(), 0, bytearray()
            while position < pin['size']:
                cancel()
                chunk = stream.read(min(CHUNK, pin['size'] - position))
                if not chunk:
                    raise ValueError('Original archive is truncated: ' + name)
                digest.update(chunk)
                if position + len(chunk) > start:
                    tail.extend(chunk[max(0, start - position):])
                position += len(chunk)
            if stream.read(1) or digest.hexdigest() != pin['sha256']:
                raise ValueError('Original archive checksum differs: ' + name)
        cancel()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(tail)


def restore(assets, recovery, target_assets, originals, cancel=lambda: None):
    for name, pin in originals.items():
        cancel()
        start, tail = read_tail(recovery, name, pin)
        source, target = checked(assets, name), checked(target_assets, name)
        with source.open('rb') as stream:
            if os.fstat(stream.fileno()).st_size < start:
                raise ValueError('Installed source prefix is truncated: ' + name)
            patches = bonus_content.PATCHES if name.casefold() == 'packfile.pck' else ()
            for offset, before, after in patches:
                if offset < 0 or len(before) != len(after) or offset + len(before) > start:
                    raise ValueError('Invalid source recovery patch')
                stream.seek(offset)
                if stream.read(len(before)) not in (before, after):
                    raise ValueError('Installed bonus selector differs: ' + name)
            stream.seek(0)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation keeps the installed source and any existing output intact.
            with target.open('xb') as output:
                try:
                    digest, position = hashlib.sha256(), 0
                    while position < start:
                        cancel()
                        chunk = bytearray(stream.read(min(CHUNK, start - position)))
                        if not chunk:
                            raise ValueError('Installed source prefix is truncated: ' + name)
                        for offset, before, _ in patches:
                            low, high = max(position, offset), min(position + len(chunk), offset + len(before))
                            if low < high:
                                chunk[low - position:high - position] = before[low - offset:high - offset]
                        output.write(chunk)
                        digest.update(chunk)
                        position += len(chunk)
                    cancel()
                    output.write(tail)
                    digest.update(tail)
                    if digest.hexdigest() != pin['sha256']:
                        raise ValueError('Recovered archive checksum differs: ' + name)
                except BaseException:
                    output.close()
                    target.unlink()
                    raise
