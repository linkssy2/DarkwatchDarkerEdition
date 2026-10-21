"""Combine authored hand pixels with the player's own unchanged first-person model."""
import hashlib
import struct

SOURCE = 'characters/player_first/base_pov_chaz.rx1'
SOURCE_SHA = 'a323481cc83532c746ff5926e3c7f033a455f91309a6161c06569ba4b7759b77'
OUTPUT_SHA = 'e834d2eb9ff52e795fc01b5fc283e259404a6a3176d8668f3fc99782784cf4d4'
OLD, NEW = b'POV_chaz_B_clr', b'POV_Cass_B_clr'


def chunks(raw, start=0):
    result = []
    while start < len(raw):
        if start + 12 > len(raw):
            raise ValueError('Truncated character model chunk')
        tag, size, _ = struct.unpack_from('<3I', raw, start)
        end = start + 12 + size
        if end > len(raw):
            raise ValueError('Invalid character model chunk')
        result.append((tag, raw[start:end]))
        start = end
    return result


def rebuild(raw, data):
    tag, _, version = struct.unpack_from('<3I', raw)
    return struct.pack('<3I', tag, len(data), version) + data


def repaint(original, pixels):
    """pixels(size) returns a package-verified DDS containing only authored art."""
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA:
        raise ValueError('Unsupported first-person character model')
    top = chunks(original)
    if [tag for tag, _ in top] != [0x24, 0x16, 0x16, 0x10, 0x1b]:
        raise ValueError('Unexpected first-person model structure')
    output, dictionary = [], 0
    for tag, raw in top:
        if tag == 0x16:
            size = (1024, 256)[dictionary]
            dds = pixels(size)
            count = size.bit_length()
            expected = sum(((max(1, size >> n) + 3) // 4) ** 2 * 8 for n in range(count))
            if (len(dds) != expected + 128 or dds[:4] != b'DDS ' or dds[84:88] != b'DXT1' or
                    struct.unpack_from('<II', dds, 12) != (size, size) or
                    struct.unpack_from('<I', dds, 28)[0] != count):
                raise ValueError('Invalid authored hand repaint')
            entries, found = [], 0
            for child, part in chunks(raw, 12):
                if child == 0x15:
                    inner, structs = [], 0
                    for kind, value in chunks(part, 12):
                        if kind == 1:
                            header = bytearray(value[12:104])
                            if (len(header) != 92 or struct.unpack_from('<I', header)[0] != 5 or
                                    header[8:40].split(b'\0')[0] != OLD or
                                    struct.unpack_from('<II', header, 72) != (0x8600, 0) or
                                    (header[84], header[86], header[87]) != (32, 4, 12)):
                                raise ValueError('Unexpected first-person texture schema')
                            header[8:40] = NEW + bytes(32-len(NEW))
                            struct.pack_into('<HH', header, 80, size, size)
                            header[85] = count
                            struct.pack_into('<I', header, 88, expected)
                            value = rebuild(value, header + dds[128:])
                            structs += 1
                        inner.append(value)
                    if structs != 1:
                        raise ValueError('Unexpected first-person texture count')
                    part = rebuild(part, b''.join(inner))
                    found += 1
                entries.append(part)
            if found != 1:
                raise ValueError('Unexpected first-person dictionary count')
            raw = rebuild(raw, b''.join(entries))
            dictionary += 1
        elif tag == 0x10:
            if raw.count(OLD + b'\0') != 1:
                raise ValueError('Unexpected first-person material name')
            raw = raw.replace(OLD + b'\0', NEW + b'\0')
        output.append(raw)
    result = b''.join(output)
    if hashlib.sha256(result).hexdigest() != OUTPUT_SHA:
        raise ValueError('Character repaint differs from the supported conversion')
    return result
