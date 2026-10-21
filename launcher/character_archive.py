"""Bounded native PCK reader and additive writer. No game data is embedded."""
import hashlib
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
    for item in entries:
        name = item['name']
        home = path_hash(name) & (mask >> 1)
        key = path_hash(name[::-1]) & ~mask
        candidate = [key | 1, item['offset'], item['size']]
        if not rows[home][0]:
            rows[home], names[home] = candidate, name
            continue
        predecessor = next((i for i, row in enumerate(rows) if row[0] & mask == home), None) if home >= 2 else None
        free = next((i for i in range(2, capacity) if not rows[i][0]), None)
        if free is None:
            raise ValueError('No free collision row')
        if predecessor is not None:
            rows[free], names[free] = rows[home], names[home]
            rows[predecessor][0] = (rows[predecessor][0] & ~mask) | free
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
        rows[free], names[free] = candidate, name
    for e in entries:
        slot = lookup(rows, mask, e['name'])
        if slot is None or names[slot] != e['name'] or rows[slot][1:] != [e['offset'], e['size']]:
            raise AssertionError('Rebuilt lookup mismatch')
    return rows, names


def compose(source, replacements):
    """Append checked resources and rebuild the native lookup; retain old data."""
    original = read(source)
    old_entries = {e['name']: e for e in original['entries']}
    original_count = len(replacements)
    replacements = {canonical(name): bytes(data) for name, data in replacements.items()}
    if len(replacements) != original_count:
        raise ValueError('Duplicate canonical resource name')
    if not replacements or any(not data for data in replacements.values()):
        raise ValueError('Empty candidate resource')
    # Existing payloads retain exact positions, including originals superseded by new rows.
    payload = bytearray(original['raw'][:original['start']])
    entries = [dict(e) for e in original['entries'] if e['name'] not in replacements]
    for name, data in sorted(replacements.items()):
        payload.extend(b'\0' * (-len(payload) % 2048))
        entries.append(dict(name=name, offset=len(payload), size=len(data), pointer=0))
        payload.extend(data)
    payload.extend(b'\0' * (-len(payload) % 2048))
    start = len(payload)
    capacity = len(original['rows'])
    while capacity < len(entries) + 2:
        capacity *= 2
    rows, names = build_rows(entries, capacity)
    payload.extend(struct.pack('<4I', capacity, len(entries), capacity - 1, 0))
    for row in rows:
        payload.extend(struct.pack('<QII', *row))
    by_name = {e['name']: e for e in entries}
    for name in names:
        if name is None:
            continue
        encoded = name.encode('ascii')
        payload.extend(struct.pack('<II', by_name[name]['pointer'], len(encoded)))
        payload.extend(encoded)
    footer = bytearray(original['footer'])
    struct.pack_into('<I', footer, 32, start)
    payload.extend(footer)
    result = read(payload)
    by_output = {e['name']: e for e in result['entries']}
    for name, entry in by_output.items():
        expected = replacements.get(name)
        if expected is None:
            old = old_entries[name]
            expected = original['raw'][old['offset']:old['offset'] + old['size']]
        actual = result['raw'][entry['offset']:entry['offset'] + entry['size']]
        if actual != expected:
            raise AssertionError('Payload preservation failure')
    return bytes(payload)
