"""Bounded native PCK reader and additive writer. No game data is embedded."""
import hashlib
import mmap
from pathlib import Path
import struct

U64 = (1 << 64) - 1


def sha(data):
    return hashlib.sha256(data).hexdigest()


def crc_table():
    result = []
    for byte in range(256):
        value = byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04C11DB7 if value >> 31 else 0)) & 0xFFFFFFFF
        result.append(value)
    return result


TABLE = crc_table()


def path_hash(path):
    value = 0
    for byte in path.upper().encode('ascii'):
        value = ((value << 8) ^ TABLE[byte ^ (value >> 56)]) & U64
    return value


def canonical(path):
    path = path.replace('\\', '/').lower()
    if not path or path.startswith('/') or ':' in path or '\0' in path:
        raise ValueError('Absolute/empty resource name')
    if any(p in ('', '.', '..') for p in path.split('/')):
        raise ValueError('Invalid resource path component')
    if len(path.encode('ascii')) >= 260:
        raise ValueError('Native resource path buffer limit')
    return path


def lookup(rows, mask, path):
    slot = path_hash(path) & (mask >> 1)
    key = path_hash(path[::-1]) & ~mask
    visited = set()
    while slot < len(rows) and slot not in visited:
        visited.add(slot)
        row = rows[slot]
        if not row[0] & mask:
            return None
        if row[0] & ~mask == key:
            return slot
        slot = row[0] & mask
        if slot == 1:
            return None
    raise ValueError('Corrupt PCK collision chain')


def read(raw):
    if len(raw) < 56:
        raise ValueError('Truncated archive')
    unknown, start, marker = struct.unpack_from('<III', raw, len(raw) - 12)
    if marker != 0xFFFFFFFB or not 0 < start < len(raw) - 40:
        raise ValueError('Unsupported PCK footer')
    capacity, count, mask, upper_mask = struct.unpack_from('<4I', raw, start)
    if not 64 <= capacity <= 1048576 or capacity & (capacity - 1) or mask != capacity - 1 or upper_mask:
        raise ValueError('Invalid hash-table bounds')
    end = start + 16 + 16 * capacity
    if count > capacity - 2 or end > len(raw) - 40:
        raise ValueError('Invalid PCK row count or extent')
    rows = [list(struct.unpack_from('<QII', raw, start + 16 + i * 16)) for i in range(capacity)]
    occupied = [(i, r) for i, r in enumerate(rows) if r[0]]
    if len(occupied) != count:
        raise ValueError('Occupied count mismatch')
    entries = []
    for slot, (key, offset, size) in occupied:
        if not key & mask or offset + size > start:
            raise ValueError('Invalid row key or data extent')
        if end + 8 > len(raw) - 40:
            raise ValueError('Truncated debug name header')
        pointer, length = struct.unpack_from('<II', raw, end)
        end += 8
        if not 0 < length < 260 or end + length > len(raw) - 40:
            raise ValueError('Invalid debug name length')
        name = raw[end:end + length].decode('ascii')
        end += length
        if canonical(name) != name:
            raise ValueError('Noncanonical original resource name')
        entries.append(dict(name=name, offset=offset, size=size, slot=slot, key=key, pointer=pointer))
    if end != len(raw) - 40 or len({e['name'] for e in entries}) != count:
        raise ValueError('Unexpected name list extent or duplicate names')
    for e in entries:
        if lookup(rows, mask, e['name']) != e['slot']:
            raise ValueError('Debug name does not resolve to its data row')
    return dict(raw=raw, start=start, rows=rows, mask=mask, entries=entries, footer=raw[-40:], unknown=unknown)


def build_rows(entries, capacity):
    """Coalesced chains: native 1D4066; slots 0/1 cannot be overflow links."""
    mask = capacity - 1
    rows = [[0, 0, 0] for _ in range(capacity)]
    names = [None] * capacity
    incoming = [None] * capacity
    free = 2
    for item in entries:
        name = item['name']
        home = path_hash(name) & (mask >> 1)
        key = path_hash(name[::-1]) & ~mask
        candidate = [key | 1, item['offset'], item['size']]
        if not rows[home][0]:
            rows[home], names[home] = candidate, name
            continue
        predecessor = incoming[home] if home >= 2 else None
        # Occupied slots never become empty, including when an overflow moves home.
        while free < capacity and rows[free][0]:
            free += 1
        if free == capacity:
            raise ValueError('No free collision row')
        if predecessor is not None:
            rows[free], names[free] = rows[home], names[home]
            rows[predecessor][0] = (rows[predecessor][0] & ~mask) | free
            incoming[free] = predecessor
            successor = rows[free][0] & mask
            if successor != 1:
                incoming[successor] = free
            incoming[home] = None
            rows[home], names[home] = candidate, name
            continue
        slot = home
        while True:
            if rows[slot][0] & ~mask == key:
                raise ValueError('Duplicate resource hash/name')
            nxt = rows[slot][0] & mask
            if nxt == 1:
                break
            slot = nxt
        rows[slot][0] = (rows[slot][0] & ~mask) | free
        incoming[free] = slot
        rows[free], names[free] = candidate, name
    for e in entries:
        slot = lookup(rows, mask, e['name'])
        if slot is None or names[slot] != e['name'] or rows[slot][1:] != [e['offset'], e['size']]:
            raise AssertionError('Rebuilt lookup mismatch')
    return rows, names


def _compose_to(source, replacements, write, cancel):
    original = read(source)
    original_count = len(replacements)
    replacements = {canonical(name): bytes(data) for name, data in replacements.items()}
    if len(replacements) != original_count:
        raise ValueError('Duplicate canonical resource name')
    if not replacements or any(not data for data in replacements.values()):
        raise ValueError('Empty candidate resource')

    def emit(data, end=None):
        end = len(data) if end is None else end
        with memoryview(data) as view:
            for offset in range(0, end, 4 * 1024 * 1024):
                cancel()
                with view[offset:min(offset + 4 * 1024 * 1024, end)] as chunk:
                    write(chunk)

    # Existing payloads retain exact positions, including originals superseded by new rows.
    emit(source, original['start'])
    position = original['start']
    entries = [dict(e) for e in original['entries'] if e['name'] not in replacements]
    for name, data in sorted(replacements.items()):
        padding = -position % 2048
        emit(b'\0' * padding)
        position += padding
        entries.append(dict(name=name, offset=position, size=len(data), pointer=0))
        emit(data)
        position += len(data)
    padding = -position % 2048
    emit(b'\0' * padding)
    start = position + padding
    capacity = len(original['rows'])
    while capacity < len(entries) + 2:
        capacity *= 2
    cancel()
    rows, names = build_rows(entries, capacity)
    index = bytearray(struct.pack('<4I', capacity, len(entries), capacity - 1, 0))
    for row in rows:
        index.extend(struct.pack('<QII', *row))
    by_name = {e['name']: e for e in entries}
    for name in names:
        if name is None:
            continue
        encoded = name.encode('ascii')
        index.extend(struct.pack('<II', by_name[name]['pointer'], len(encoded)))
        index.extend(encoded)
    footer = bytearray(original['footer'])
    struct.pack_into('<I', footer, 32, start)
    index.extend(footer)
    emit(index)
    return original, replacements


def _verify_composition(original, replacements, output, cancel):
    result = read(output)
    old_entries = {e['name']: e for e in original['entries']}
    by_output = {e['name']: e for e in result['entries']}
    for name, entry in by_output.items():
        expected = replacements.get(name)
        expected_offset = 0
        if expected is None:
            old = old_entries[name]
            expected = original['raw']
            expected_offset = old['offset']
            expected_size = old['size']
        else:
            expected_size = len(expected)
        if expected_size != entry['size']:
            raise AssertionError('Payload preservation failure: ' + name)
        # Bound comparison copies while retaining the fast byte-buffer comparator.
        for offset in range(0, entry['size'], 4 * 1024 * 1024):
            cancel()
            end = min(offset + 4 * 1024 * 1024, entry['size'])
            actual = output[entry['offset'] + offset:entry['offset'] + end]
            if actual != expected[expected_offset + offset:expected_offset + end]:
                raise AssertionError('Payload preservation failure: ' + name)


def compose(source, replacements):
    """Append checked resources and rebuild the native lookup; retain old data."""
    payload = bytearray()
    original, replacements = _compose_to(source, replacements, payload.extend, lambda: None)
    _verify_composition(original, replacements, payload, lambda: None)
    return bytes(payload)


def compose_file(source, replacements, destination, cancel=lambda: None):
    """Write an identical checked archive without holding its payload in memory."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Archive output must differ from its source')
    created = False
    try:
        cancel()
        with source.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw:
            with destination.open('xb') as output:
                created = True
                original, replacements = _compose_to(raw, replacements, output.write, cancel)
            with destination.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as output:
                _verify_composition(original, replacements, output, cancel)
            cancel()
    except BaseException:
        if created:
            destination.unlink()
        raise
