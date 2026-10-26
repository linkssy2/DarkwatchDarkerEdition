"""Import PAL Spanish stereo FMV audio without changing Xbox video or clocks.

The native Xbox AIX layout stays intact: Spanish replaces its front pair and the
other pairs become silence. This is stereo movie audio, not a Spanish 5.1 mix.
All media comes from the user's verified discs; none is embedded here.
"""
from collections import defaultdict
import struct

import character_archive
from ps2_disc import require

# The native PAL movie selector maps language S to stream index 4. Extras and
# single-track movies keep their original Xbox audio; Animatic2 has another edit.
MOVIES = frozenset('movies/' + name + '.sfd' for name in (
    'intro', 'm01s1', 'm01s2', 'm01s4', 'm04s1', 'm05s1', 'm09s2',
    'm09s3', 'm10s1', 'm11s2', 'm22s1', 'm22s2', 'm22s3', 'm22s4'))


def timestamp(raw):
    require(len(raw) == 5 and all(raw[i] & 1 for i in (0, 2, 4)), 'Invalid PES timestamp markers')
    return ((raw[0] & 14) << 29) | (raw[1] << 22) | ((raw[2] & 254) << 14) | (raw[3] << 7) | (raw[4] >> 1)


def stamp(value, tag):
    require(0 <= value < 1 << 33 and tag in (1, 2, 3), 'Invalid PES timestamp')
    return bytes([(tag << 4) | ((value >> 29) & 14) | 1, (value >> 22) & 255,
                  ((value >> 14) & 254) | 1, (value >> 7) & 255, ((value << 1) & 254) | 1])


def packets(raw):
    """Bounded MPEG program-stream parser; timestamp positions refer to raw bytes."""
    pos = 0
    while pos < len(raw):
        require(pos + 4 <= len(raw) and raw[pos:pos + 3] == b'\0\0\1', 'Invalid program-stream boundary')
        sid = raw[pos + 3]
        if sid == 0xb9:
            require(all(x in (0, 255) for x in raw[pos + 4:]), 'Unexpected program-stream trailer')
            return
        require(pos + 14 <= len(raw), 'Truncated program-stream header')
        if sid == 0xba:
            size = 12 if raw[pos + 4] >> 4 == 2 else 14 + (raw[pos + 13] & 7)
            require(pos + size <= len(raw), 'Truncated pack header')
            yield sid, pos + size, pos + size, None, None
            pos += size
            continue
        end = pos + 6 + int.from_bytes(raw[pos + 4:pos + 6], 'big')
        require(pos + 6 < end <= len(raw), 'Invalid PES extent')
        body = pos + 6
        pts_at = dts_at = None
        if 0xc0 <= sid <= 0xef:
            while body < end and raw[body] == 255:
                body += 1
            require(body < end, 'Missing PES payload')
            if raw[body] & 192 == 64:
                body += 2
            require(body < end, 'Truncated STD field')
            if raw[body] >> 4 in (2, 3):
                pts_at = body
                both = raw[body] >> 4 == 3
                body += 10 if both else 5
                dts_at = pts_at + 5 if both else None
            elif raw[body] == 15:
                body += 1
            elif raw[body] & 192 == 128:
                require(body + 3 <= end, 'Truncated MPEG-2 PES header')
                flags, length = raw[body + 1:body + 3]
                pts_at = body + 3 if flags & 128 else None
                dts_at = body + 8 if flags & 64 else None
                body += 3 + length
            else:
                raise ValueError('Unsupported PES header')
            require(body <= end and all(p is None or p + 5 <= body for p in (pts_at, dts_at)), 'Truncated PES timestamps')
            for at in (pts_at, dts_at):
                if at is not None:
                    timestamp(raw[at:at + 5])
        yield sid, body, end, pts_at, dts_at
        pos = end


def elementary(raw):
    streams = defaultdict(bytearray)
    for sid, start, end, unused, unused2 in packets(raw):
        if 0xc0 <= sid <= 0xef:
            streams[sid].extend(raw[start:end])
    return {sid: bytes(data) for sid, data in streams.items()}


def adx_tracks(raw):
    """Extract all bounded AIX substreams for actual ADX decode verification."""
    if raw[:2] == b'\x80\0':
        return [raw]
    require(raw[:4] == b'AIXF', 'Unsupported movie audio container')
    tracks = defaultdict(bytearray)
    pos, ended = 0, False
    while pos < len(raw):
        require(pos + 8 <= len(raw), 'Truncated AIX chunk')
        tag = raw[pos:pos + 4]
        end = pos + 8 + int.from_bytes(raw[pos + 4:pos + 8], 'big')
        require(pos + 8 <= end <= len(raw) and tag in (b'AIXF', b'AIXP', b'AIXE'), 'Invalid AIX extent/tag')
        if tag == b'AIXP':
            require(pos + 16 <= end, 'Truncated AIX packet')
            sid, count = raw[pos + 8:pos + 10]
            size = int.from_bytes(raw[pos + 10:pos + 12], 'big')
            require(sid < count <= 8 and pos + 16 + size <= end, 'Invalid AIX stream/payload')
            tracks[sid].extend(raw[pos + 16:pos + 16 + size])
        if tag == b'AIXE':
            require(end == len(raw), 'Unexpected data after AIX end')
            ended = True
        pos = end
    require(ended and tracks and sorted(tracks) == list(range(len(tracks))), 'Incomplete AIX streams')
    return [bytes(tracks[i]) for i in range(len(tracks))]


def adx_extent(raw):
    """Validate the unencrypted ADX v4 format shared by the two pinned discs."""
    require(len(raw) >= 58 and raw[:2] == b'\x80\0'
            and raw[4:8] == b'\x03\x12\x04\x02'
            and raw[18:24] == b'\x04\0\0\0\0\0', 'Unsupported movie ADX format')
    start = int.from_bytes(raw[2:4], 'big') + 4
    rate, samples = struct.unpack_from('>II', raw, 8)
    require(start in (40, 288) and rate == 48000 and samples > 0
            and raw[start - 6:start] == b'(c)CRI'
            and not any(raw[32:start - 8]), 'Unsupported movie ADX header')
    end = start + ((samples + 31) // 32) * 36
    require(end + 18 == len(raw) and raw[end:end + 4] == b'\x80\x01\0\x0e',
            'Truncated movie ADX samples or terminator')
    return start, end


def normalized_adx(raw):
    start, unused = adx_extent(raw)
    result = bytearray(raw[:32] + raw[start - 8:start] + raw[start:])
    struct.pack_into('>H', result, 2, 36)
    adx_extent(result)
    return bytes(result)


def silent_adx(raw):
    start, end = adx_extent(raw)
    result = bytearray(raw)
    # Clear initial predictor history as well as encoded samples, preventing a
    # residual click/decay from the original English component's first samples.
    result[24:32] = bytes(8)
    result[start:end] = bytes(end - start)
    return bytes(result)


def replace_aix(raw, replacements, cancel):
    tracks = adx_tracks(raw)
    require(len(tracks) == len(replacements) == 3 and raw[:4] == b'AIXF'
            and all(len(a) == len(b) for a, b in zip(tracks, replacements)),
            'Movie AIX component layout changed')
    result, offsets, pos = bytearray(raw), [0, 0, 0], 0
    while pos < len(raw):
        cancel()
        end = pos + 8 + int.from_bytes(raw[pos + 4:pos + 8], 'big')
        if raw[pos:pos + 4] == b'AIXP':
            sid, count = raw[pos + 8:pos + 10]
            size = int.from_bytes(raw[pos + 10:pos + 12], 'big')
            require(count == 3 and sid < 3, 'Unexpected movie AIX component count')
            offset = offsets[sid]
            result[pos + 16:pos + 16 + size] = replacements[sid][offset:offset + size]
            offsets[sid] += size
        pos = end
    require(offsets == [len(track) for track in replacements] and len(result) == len(raw),
            'Incomplete movie AIX replacement')
    return bytes(result)


def convert_movie(original, translated, cancel=lambda: None):
    cancel()
    xbox, ps2 = elementary(original), elementary(translated)
    require(set(xbox) == {0xc1, 0xe0} and set(ps2) == {0xc0, 0xc1, 0xc2, 0xc3, 0xc4, 0xe0},
            'Unexpected movie language stream layout')
    front = normalized_adx(ps2[0xc4])
    tracks = adx_tracks(xbox[0xc1])
    require(len(tracks) == 3, 'Expected three Xbox movie audio components')
    for track in tracks:
        adx_extent(track)
    require(tracks[0][4:20] == front[4:20] and len(tracks[0]) == len(front),
            'Spanish movie audio does not match the original timeline')
    replacement = replace_aix(xbox[0xc1], [front, silent_adx(tracks[1]), silent_adx(tracks[2])], cancel)
    result, offset = bytearray(original), 0
    for sid, start, end, unused, unused2 in packets(original):
        if sid == 0xc1:
            cancel()
            result[start:end] = replacement[offset:offset + end - start]
            offset += end - start
    require(offset == len(replacement) and len(result) == len(original), 'Incomplete movie audio stream')
    return bytes(result)


def convert(ps2_movies, xbox_movie, cancel, notify):
    """Return a new Xbox MoviesN.pck, retaining unrelated resources verbatim."""
    cancel()
    parsed = character_archive.read(xbox_movie)
    selected = sorted((entry for entry in parsed['entries'] if entry['name'] in MOVIES),
                      key=lambda entry: entry['name'])
    if not selected:
        return xbox_movie
    result = bytearray(xbox_movie)
    for index, entry in enumerate(selected):
        cancel()
        name = entry['name']
        notify('progress', 'Preparing Spanish movie ' + name.split('/')[-1],
               percent=100 * index // max(1, len(selected)))
        start, end = entry['offset'], entry['offset'] + entry['size']
        require(all(other is entry or end <= other['offset']
                    or start >= other['offset'] + other['size'] for other in parsed['entries']),
                'Overlapping movie archive resources')
        original = xbox_movie[start:end]
        replacement = convert_movie(original, ps2_movies.read(name), cancel)
        require(len(replacement) == end - start, 'Movie archive resource size changed')
        result[start:end] = replacement
    cancel()
    require(len(result) == len(xbox_movie), 'Movie archive size changed')
    return bytes(result)


