"""Derive Spanish text from a supplied PS2 disc, retaining native Xbox identities."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

import character_archive

MAGIC = b'DWES0003'
CONTEXT_SHA256 = '9104a01248dfcf5c47e4dc7c6dead796d4f804ca6e03087da61c6701241a9408'
ACCENTS = str.maketrans('áéíóúüñ\xa0', 'ÁÉÍÓÚÜÑ ')
# Standard's extended glyph map contains uppercase Spanish accents only.
EXTENDED = set('¡¿ÁÉÍÓÚÜÑ©®')


def context_id(key, english):
    # Lookup identity only; package SHA-256 remains the integrity boundary.
    value = 14695981039346656037
    native_key = zlib.crc32(key.upper().encode('ascii'))
    for byte in struct.pack('<I', native_key) + english.encode('latin1'):
        value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value


def normalized(value):
    value = value.translate(ACCENTS)
    if not value or '\0' in value or len(value.encode('latin1')) >= 4096:
        raise ValueError('Invalid Spanish string length or terminator')
    if any(not (32 <= ord(c) < 127 or c in '\r\n\t' or c in EXTENDED) for c in value):
        raise ValueError('Spanish string contains an unsupported native glyph')
    return value


def tokens(value):
    return Counter(re.findall(r'\^([a-z0-9_]+)', value.lower()))


def read_pack(raw):
    """Expand only omitted empty lookup rows in memory, never game resource data."""
    if len(raw) < 56:
        raise ValueError('Truncated PCK')
    _, start, marker = struct.unpack_from('<III', raw, len(raw) - 12)
    if marker != 0xFFFFFFFB or not 0 < start < len(raw) - 40:
        raise ValueError('Unsupported PCK footer')
    rows, count, mask, upper = struct.unpack_from('<4I', raw, start)
    if upper or not 64 <= rows <= mask + 1 <= 1048576 or (mask + 1) & mask:
        raise ValueError('Invalid compact PCK bounds')
    end = start + 16 + rows * 16
    if count > rows - 2 or end > len(raw) - 40:
        raise ValueError('Invalid compact PCK table extent')
    data = bytearray(raw[:end] + bytes((mask + 1 - rows) * 16) + raw[end:])
    struct.pack_into('<I', data, start, mask + 1)
    parsed = character_archive.read(data)
    for entry in parsed['entries']:
        if entry['slot'] >= rows or character_archive.path_hash(entry['name']) & (mask >> 1) >= rows:
            raise ValueError('PCK lookup references omitted rows')
    return parsed


def read_table(raw):
    """Read bounded version-one BXML using its original single-byte text encoding."""
    if raw[:4] != b'\x01\0\0\0':
        raise ValueError('Unsupported localization BXML version')
    pos, nodes = 4, 0
    def word():
        nonlocal pos
        if pos + 2 > len(raw):
            raise ValueError('Truncated localization BXML')
        value = struct.unpack_from('<H', raw, pos)[0]
        pos += 2
        return value
    count = word()
    if count >= 20000:
        raise ValueError('Localization string count limit')
    strings = []
    for _ in range(count):
        length = word()
        if length >= 4096 or pos + length > len(raw):
            raise ValueError('Localization string extent')
        value = raw[pos:pos + length].decode('latin1')
        if '\0' in value:
            raise ValueError('Embedded localization string terminator')
        strings.append(value)
        pos += length
    def text(index):
        if index >= len(strings):
            raise ValueError('Localization string index')
        return strings[index]
    rows = {}
    def node(depth=0):
        nonlocal nodes
        nodes += 1
        if depth >= 64 or nodes >= 300000:
            raise ValueError('Localization node/depth limit')
        name, count = text(word()), word()
        if count >= 64:
            raise ValueError('Localization attribute count')
        attributes = set()
        for _ in range(count):
            key, _ = text(word()), text(word())
            if key in attributes:
                raise ValueError('Duplicate localization attribute')
            attributes.add(key)
        count = word()
        if count >= 20000:
            raise ValueError('Localization child count')
        children = [node(depth + 1) for _ in range(count)]
        value = word()
        value = None if value == 65535 else text(value)
        fields = {key: value for key, value in children}
        if 'textID' in fields:
            if len(fields) != len(children) or not isinstance(fields['textID'], str):
                raise ValueError('Invalid localization row')
            key = fields['textID'].lower()
            if key in rows or not key or len(key) >= 256 or not key.isascii():
                raise ValueError('Duplicate or invalid localization key')
            rows[key] = fields.get('localizedText') or ''
        return name, value
    node()
    if pos != len(raw):
        raise ValueError('Trailing localization BXML')
    if not rows:
        raise ValueError('Empty localization table')
    return rows


def tables(raw):
    pack = read_pack(raw)
    return {entry['name']: read_table(pack['raw'][entry['offset']:entry['offset'] + entry['size']])
            for entry in pack['entries'] if '/localization/' in entry['name']
            and entry['name'].endswith('.bxml')}


def corrections(raw):
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != {'schema', 'contexts'} or document['schema'] != 1:
        raise ValueError('Unsupported PS2 text corrections')
    if not isinstance(document['contexts'], dict) or len(document['contexts']) > 10000:
        raise ValueError('Invalid PS2 text correction count')
    result = {}
    for identity, spanish in document['contexts'].items():
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{16}', identity) or not isinstance(spanish, str):
            raise ValueError('Invalid PS2 text correction context')
        result[int(identity, 16)] = normalized(spanish)
    return result


def catalogue(original, ps2, edits):
    result, uses, seen_edits, per_table, contexts = {}, Counter(), set(), {}, {}
    for path, english_rows in sorted(original.items()):
        if not path.endswith('_e.bxml'):
            continue
        spanish_rows = ps2.get(path[:-6] + 's.bxml', {})
        count = 0
        for key, english in english_rows.items():
            if not english:
                continue
            context = key, english
            candidates = contexts.setdefault(context, set())
            if spanish_rows.get(key):
                candidates.add(normalized(spanish_rows[key]))
            count += 1
        per_table[path] = count
    # Repeated native key/English contexts have one V3 identity. A candidate is
    # accepted only from a matching table for that same context, never another ID.
    for (key, english), candidates in contexts.items():
        identity = context_id(key, english)
        if identity in edits:
            spanish = edits[identity]
            seen_edits.add(identity)
            source = 'project_correction'
        elif len(candidates) == 1:
            spanish = next(iter(candidates))
            source = 'ps2_same_table'
        elif candidates:
            raise ValueError('Conflicting Spanish for identical English context: ' + key)
        else:
            raise ValueError('Missing Spanish context: ' + key)
        if tokens(english) != tokens(spanish):
            raise ValueError('Changed semantic tokens: ' + key)
        result[key, english] = spanish
        uses[source] += 1
    if seen_edits != edits.keys():
        raise ValueError('Unused corrections do not match this disc')
    if not result or len(result) > 100000:
        raise ValueError('Invalid catalogue count')
    output = bytearray(MAGIC + struct.pack('<I', len(result)))
    identities = {}
    for (key, english), spanish in sorted(result.items()):
        values = key.encode('ascii'), english.encode('latin1'), spanish.encode('latin1')
        if not 0 < len(values[0]) <= 128 or any(not 0 < len(value) < 4096 or b'\0' in value for value in values):
            raise ValueError('Catalogue record limits')
        identity = context_id(key, english)
        if identity in identities and identities[identity] != (key, english):
            raise ValueError('Context identity collision')
        identities[identity] = key, english
        output.extend(struct.pack('<QI', identity, len(values[2])))
        output.extend(values[2])
    return bytes(output), dict(english_nonempty_rows=sum(per_table.values()),
        unique_contexts=len(result), tables=per_table, sources=dict(uses),
        missing_contexts=0, conflicting_contexts=0, token_mismatches=0,
        unsupported_glyphs=0, reviewed_corrections=len(seen_edits),
        format=MAGIC.decode('ascii'), original_contexts_embedded=False,
        context_identity_collisions=0)


def inventory(original):
    contexts = sorted({(key, english) for path, rows in original.items() if path.endswith('_e.bxml')
                       for key, english in rows.items() if english})
    return hashlib.sha256(json.dumps(contexts, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()


def convert(ps2_pack, xbox_pack_bytes):
    """Build text locally; the caller verifies the supported PS2 archive hash."""
    original = tables(xbox_pack_bytes)
    if inventory(original) != CONTEXT_SHA256:
        raise ValueError('The installed Xbox text does not match this language import.')
    selected = {path[:-6] + 's.bxml' for path in original if path.endswith('_e.bxml')}
    ps2 = {path: read_table(ps2_pack.read(path)) for path in sorted(selected) if path in ps2_pack.entries}
    edits = corrections(Path(__file__).with_name('ps2-spanish-corrections.json').read_text(encoding='utf8'))
    return catalogue(original, ps2, edits)[0]

