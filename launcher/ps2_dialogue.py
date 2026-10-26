"""Convert user-supplied PAL PS2 dialogue into the Xbox cue-indexed bank.

Names and variants come from the user's archives. No dialogue catalog or audio
is embedded. Silent PS2 placeholders retain the matching original Xbox line.
"""
import array
import struct
import sys

import character_archive
import character_assets
from ps2_disc import require

DIALOGUE = 'audio/dialog_base/dialog_base_stream.xwb'
SPANISH = 'audio/dialog_base_s/'
PCM_FORMAT = 0x800BB804  # Native 3EB3AC: PCM16, mono, 24 kHz.


def archive(raw):
    require(len(raw) >= 56, 'Truncated Xbox dialogue archive.')
    start, marker = struct.unpack_from('<II', raw, len(raw) - 8)
    require(marker == 0xFFFFFFFB and 0 < start <= len(raw) - 56,
            'Invalid Xbox dialogue archive footer.')
    capacity, count, mask, upper = struct.unpack_from('<4I', raw, start)
    require(64 <= capacity <= mask + 1 <= 1048576 and not ((mask + 1) & mask)
            and upper == 0 and count <= capacity - 2,
            'Invalid Xbox dialogue archive table.')
    end = start + 16 + capacity * 16
    require(end <= len(raw) - 40, 'Truncated Xbox dialogue archive table.')
    if capacity != mask + 1:
        raw = bytearray(raw[:end] + bytes((mask + 1 - capacity) * 16) + raw[end:])
        struct.pack_into('<I', raw, start, mask + 1)
    parsed = character_archive.read(raw)
    entries = {e['name']: e for e in parsed['entries']}

    def resource(name):
        require(name in entries, 'Missing Xbox dialogue resource: ' + name)
        entry = entries[name]
        return bytes(parsed['raw'][entry['offset']:entry['offset'] + entry['size']])

    return parsed, entries, resource


def child(node, name):
    return next((n for n in node['children'] if n['name'] == name),
                {'children': [], 'value': None})


def prototypes(raw):
    result = {}
    for node in child(character_assets.decode(raw), 'prototypes')['children']:
        key = child(node, 'id')['value']
        names = [child(source, 'name')['value']
                 for source in child(node, 'sourceSpecList')['children']]
        require(isinstance(key, str) and all(isinstance(n, str) and n for n in names),
                'Invalid dialogue prototype.')
        result[key] = names
    return result


def cue_waves(raw):
    """Read the title's simple XSB v11 tracks and ordered variation table."""
    require(len(raw) >= 56 and raw[:6] == b'SDBK\x0b\0', 'Unsupported dialogue cue bank.')
    sounds, cues, tracks, banks = struct.unpack_from('<4H', raw, 28)
    bank_offset = struct.unpack_from('<I', raw, 8)[0]
    require(0 < sounds <= 4096 and 0 < cues <= 4096 and 0 < banks <= 16
            and bank_offset + 16 * banks <= len(raw)
            and 56 + 20 * (sounds + cues) <= len(raw), 'Invalid dialogue cue bounds.')
    bank_names = [raw[bank_offset + 16*i:bank_offset + 16*(i+1)].rstrip(b'\0')
                  for i in range(banks)]
    for i in range(cues):
        pos = 56 + 20*i
        flags, sound, name_offset, variation = struct.unpack_from('<HHII', raw, pos)
        require(flags == 0 and name_offset < len(raw), 'Unsupported dialogue cue flags/name.')
        end = raw.find(b'\0', name_offset, min(len(raw), name_offset + 260))
        require(end > name_offset, 'Invalid dialogue cue name.')
        name = raw[name_offset:end].decode('ascii')
        if sound == 65535:
            require(variation + 4 <= len(raw), 'Invalid dialogue variation table.')
            count, words = struct.unpack_from('<HH', raw, variation)
            require(0 < count <= 64 and words == count * 2
                    and variation + 4 + count * 8 <= len(raw), 'Invalid dialogue variations.')
            indices = [struct.unpack_from('<I', raw, variation + 4 + j*8)[0] for j in range(count)]
        else:
            indices = [sound]
        waves = []
        for index in indices:
            require(index < sounds, 'Dialogue sound index exceeds bank.')
            pos = 56 + 20*cues + 20*index
            offset = struct.unpack_from('<I', raw, pos)[0]
            require(raw[pos + 8] == 1 and offset + 4 <= len(raw), 'Unsupported dialogue track.')
            packed = struct.unpack_from('<I', raw, offset)[0]
            event = packed >> 8
            require(packed & 255 == 1 and event + 12 <= len(raw)
                    and raw[event + 4] == 4, 'Unsupported dialogue track event.')
            wave, bank = struct.unpack_from('<HH', raw, event + 8)
            require(bank < banks and bank_names[bank] == b'DIALOG_BASE_S',
                    'Dialogue references an unexpected wave bank.')
            waves.append(wave)
        yield name, waves


def map_slots(entries, resource, audio, count):
    original_base = prototypes(resource('audio/dialog_base/dialog_base.babf'))
    spanish_base = prototypes(audio.read(SPANISH + 'dialog_base_s.babf'))
    result = {}
    for path in sorted(entries):
        if not path.endswith('.xsb'):
            continue
        local = prototypes(resource(path[:-4] + '.babf'))
        for cue, waves in cue_waves(resource(path)):
            names = local.get(cue) or original_base.get(cue)
            require(names is not None and len(names) == len(waves), 'Dialogue variant catalog differs.')
            for variant, (wave, name) in enumerate(zip(waves, names)):
                target = SPANISH + name.lower() + '.adx'
                if target not in audio.entries:
                    # A source filename was renamed on PS2; require its exact cue/variant identity.
                    alternate = spanish_base.get(cue)
                    require(alternate is not None and len(alternate) == len(waves),
                            'Spanish dialogue cue is unavailable: ' + cue)
                    target = SPANISH + alternate[variant].lower() + '.adx'
                require(target in audio.entries and 0 <= wave < count,
                        'Spanish dialogue resource is missing or outside the bank.')
                require(wave not in result or result[wave] == target,
                        'Conflicting Spanish dialogue cue mapping.')
                result[wave] = target
    require(set(result) == set(range(count)), 'Spanish dialogue does not cover the Xbox cue bank.')
    return result


def decode_adx(raw):
    """Decode the supported disc's unencrypted mono ADX v4, with integer LPC.

    The 500 Hz/24 kHz predictor is (6687, -2729) at 12 fractional bits.
    CRI-v4 adds one to the block scale and retains the two initial history values.
    Reference: vgmstream src/meta/adx.c and src/coding/adx_decoder.c.
    This is speaker PCM, not an Xbox ADPCM re-encoding or a resample.
    """
    require(len(raw) >= 40 and raw[:2] == b'\x80\0'
            and raw[4:8] == bytes((3, 18, 4, 1)), 'Unsupported PS2 dialogue codec.')
    start = int.from_bytes(raw[2:4], 'big') + 4
    rate, samples = struct.unpack_from('>II', raw, 8)
    require(start == 40 and raw[start-6:start] == b'(c)CRI'
            and rate == 24000 and 0 < samples <= rate * 300
            and raw[16:20] == bytes((1, 244, 4, 0))
            and not any(raw[20:24]) and not any(raw[28:34]),
            'Unsupported PS2 dialogue format/history.')
    blocks = (samples + 31) // 32
    require(start + blocks * 18 + 4 <= len(raw), 'Truncated PS2 dialogue samples.')
    trailer = start + blocks * 18
    require(raw[trailer:trailer+2] == b'\x80\x01'
            and trailer + 4 + int.from_bytes(raw[trailer+2:trailer+4], 'big') == len(raw),
            'Invalid PS2 dialogue end block.')
    pcm = array.array('h')
    previous, older = struct.unpack_from('>hh', raw, 24)
    for offset in range(start, trailer, 18):
        scale = int.from_bytes(raw[offset:offset+2], 'big')
        require(scale < 32768, 'Encrypted or premature PS2 dialogue end block.')
        for pair in raw[offset+2:offset+18]:
            for residual in (pair >> 4, pair & 15):
                if residual >= 8:
                    residual -= 16
                sample = residual * (scale + 1) + ((6687 * previous - 2729 * older) >> 12)
                sample = max(-32768, min(32767, sample))
                pcm.append(sample)
                older, previous = previous, sample
    del pcm[samples:]
    if sys.byteorder != 'little':
        pcm.byteswap()
    return pcm.tobytes()


def convert(audio, xbox_dialogue, cancel, notify):
    """Return a complete isolated dialogue PCK; callers publish it atomically."""
    parsed, entries, resource = archive(xbox_dialogue)
    original = resource(DIALOGUE)
    require(len(original) >= 80 and original[:8] == b'WBND\x03\0\0\0',
            'Unsupported Xbox dialogue wave bank.')
    meta, meta_size = struct.unpack_from('<II', original, 16)
    start, size, flags, count = struct.unpack_from('<4I', original, 32)
    element, unused, alignment, unused_format = struct.unpack_from('<4I', original, 64)
    require(flags == 1 and count == 1544 and element == 24 and alignment == 2048
            and original[48:64].rstrip(b'\0') == b'DIALOG_BASE_S'
            and meta_size == count * 24 and 80 <= meta and meta + meta_size <= start
            and start + size == len(original), 'Xbox dialogue wave bank differs.')
    mapping = map_slots(entries, resource, audio, count)
    result, payload, fallbacks = bytearray(original[:start]), bytearray(), []
    for index in range(count):
        cancel()
        values = list(struct.unpack_from('<6I', original, meta + index * 24))
        old_flags, fmt, offset, length, loop_start, loop_size = values
        require(fmt == 768005 and length > 0 and length % 36 == 0
                and offset % alignment == 0 and offset + length <= size
                and loop_start == loop_size == 0, 'Unsupported original dialogue wave.')
        pcm = decode_adx(audio.read(mapping[index]))
        if any(pcm):
            data = pcm
            values[1] = PCM_FORMAT
        else:
            data = original[start + offset:start + offset + length]
            fallbacks.append(index)
        values[2:4] = len(payload), len(data)
        struct.pack_into('<6I', result, meta + index * 24, *values)
        payload.extend(data)
        payload.extend(bytes(-len(payload) % alignment))
        if index % 32 == 0 or index + 1 == count:
            notify('progress', 'Preparing Spanish dialogue', percent=(index + 1) * 100 // count,
                   current=index + 1, total=count)
    struct.pack_into('<I', result, 36, len(payload))
    result.extend(payload)
    cancel()
    notify('progress', 'Spanish dialogue prepared', translated=count-len(fallbacks),
           original_fallbacks=len(fallbacks))
    return character_archive.compose(parsed['raw'], {DIALOGUE: bytes(result)})
