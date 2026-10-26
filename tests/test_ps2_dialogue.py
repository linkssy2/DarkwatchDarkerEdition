"""Synthetic media only: codec bounds, derived cue identity and isolated replacement."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import character_archive as pck
import character_assets as bxml
import ps2_dialogue as dialogue


def node(name, value=None, children=()):
    return dict(name=name, value=value, children=list(children), attributes={})


def catalog(rows):
    return bxml.encode(node('SoundBankConfig', children=[node('prototypes', children=[
        node('element', children=[node('id', cue), node('sourceSpecList', children=[
            node('element', children=[node('name', name)]) for name in names])])
        for cue, names in rows])]))


def archive(resources):
    raw = bytearray(128)
    entries = []
    for name, data in resources.items():
        entries.append(dict(name=name, offset=len(raw), size=len(data), pointer=0))
        raw.extend(data)
    start = len(raw)
    capacity = 64
    while capacity < len(entries) * 2:
        capacity *= 2
    rows, names = pck.build_rows(entries, capacity)
    raw.extend(struct.pack('<4I', capacity, len(entries), capacity - 1, 0))
    for row in rows:
        raw.extend(struct.pack('<QII', *row))
    for name in names:
        if name:
            raw.extend(struct.pack('<II', 0, len(name)) + name.encode())
    footer = bytearray(40)
    struct.pack_into('<II', footer, 32, start, 0xFFFFFFFB)
    return bytes(raw + footer)


def adx(samples=32, history=(0, 0), scale=10, residual=0x10):
    raw = bytearray(40)
    raw[:8] = bytes([0x80, 0, 0, 0x24, 3, 0x12, 4, 1])
    struct.pack_into('>IIH', raw, 8, 24000, samples, 500)
    raw[18] = 4
    struct.pack_into('>hh', raw, 24, *history)
    raw[34:40] = b'(c)CRI'
    for _ in range((samples + 31) // 32):
        raw.extend(struct.pack('>H', scale) + bytes([residual]) * 16)
    return bytes(raw + b'\x80\x01\0\x0e' + bytes(14))


def xsb(cues):
    sounds = sum(len(waves) for _, waves in cues)
    raw = bytearray(56 + 20 * (sounds + len(cues)))
    raw[:6] = b'SDBK\x0b\0'
    struct.pack_into('<4H', raw, 28, sounds, len(cues), sounds, 1)
    struct.pack_into('<I', raw, 8, len(raw))
    raw.extend(b'DIALOG_BASE_S\0\0\0')
    sound = 0
    for i, (cue, waves) in enumerate(cues):
        name = len(raw)
        raw.extend(cue.encode() + b'\0')
        variation = 0xFFFFFFFF
        if len(waves) > 1:
            variation = len(raw)
            raw.extend(struct.pack('<HH', len(waves), len(waves) * 2))
            for j in range(len(waves)):
                raw.extend(struct.pack('<IHH', sound + j, 0, 10000))
        struct.pack_into('<HHII', raw, 56 + i * 20, 0,
                         sound if len(waves) == 1 else 65535, name, variation)
        for wave in waves:
            pos = 56 + len(cues) * 20 + sound * 20
            struct.pack_into('<I', raw, pos, len(raw))
            raw[pos + 8] = 1
            raw.extend(struct.pack('<I', ((len(raw) + 4) << 8) | 1))
            raw.extend(struct.pack('<IIHH', 0, 4, wave, 0))
            sound += 1
    return bytes(raw)


class Audio:
    def __init__(self, resources):
        self.entries = resources

    def read(self, path):
        return self.entries[path]


def fixture():
    count, meta, start = 1544, 80, 80 + 1544 * 24
    bank = bytearray(start + count * 2048)
    bank[:8] = b'WBND\x03\0\0\0'
    struct.pack_into('<II', bank, 16, meta, count * 24)
    struct.pack_into('<4I', bank, 32, start, count * 2048, 1, count)
    bank[48:64] = b'DIALOG_BASE_S\0\0\0'
    struct.pack_into('<4I', bank, 64, 24, 0, 2048, 0)
    for i in range(count):
        struct.pack_into('<6I', bank, meta + i*24, 0, 768005, i*2048, 36, 0, 0)
        bank[start + i*2048:start + i*2048+36] = bytes([i % 251 + 1]) * 36
    rows = [('CUE' + str(i), ['line' + str(i)]) for i in range(count)]
    resources = {dialogue.DIALOGUE: bytes(bank), 'audio/dialog_base/dialog_base.babf': catalog(rows),
                 'audio/test/test.babf': catalog(rows),
                 'audio/test/test.xsb': xsb([(c, [i]) for i, (c, _) in enumerate(rows)]),
                 'audio/unchanged.bin': b'preserve me'}
    audio = {dialogue.SPANISH + 'dialog_base_s.babf': catalog(rows)}
    for i in range(count):
        audio[dialogue.SPANISH + 'line' + str(i) + '.adx'] = adx(residual=0 if i % 3 == 0 else 0x12)
    return archive(resources), Audio(audio)


class DialogueTests(unittest.TestCase):
    def test_adx_history_scale_signed_residuals_and_exact_declared_extent(self):
        # Independently verified against vgmstream's unchanged v4 decoder.
        # History100/-50, scale10+1, residuals alternating1/0.
        values = struct.unpack('<8h', dialogue.decode_adx(adx(8, (100, -50)))[:16])
        self.assertEqual(values, (207, 271, 315, 333, 344, 339, 335, 321))
        self.assertEqual(len(dialogue.decode_adx(adx(33))), 66)
        self.assertEqual(dialogue.decode_adx(adx(32, residual=0)), bytes(64))
        self.assertTrue(any(dialogue.decode_adx(adx(32, residual=0x8F))))

    def test_adx_rejects_unsupported_or_truncated_media(self):
        good = adx()
        for offset, value in [(0, 0), (4, 4), (7, 2), (8, 1), (18, 3), (19, 8), (34, 0), (40, 128)]:
            with self.subTest(offset=offset):
                bad = bytearray(good)
                bad[offset] = value
                with self.assertRaises(ValueError):
                    dialogue.decode_adx(bad)
        for bad in [good[:39], good[:-1], good + b'\0']:
            with self.assertRaises(ValueError):
                dialogue.decode_adx(bad)

    def test_cue_variants_and_aliases_derive_from_catalog_not_slot_order(self):
        rows = [('TEST', ['first', 'renamed'])]
        contents = {'audio/dialog_base/dialog_base.babf': catalog(rows),
                    'audio/a/a.babf': catalog(rows), 'audio/a/a.xsb': xsb([('TEST', [1, 0])])}
        audio = Audio({dialogue.SPANISH + 'dialog_base_s.babf': catalog([('TEST', ['first', 'second'])]),
                       dialogue.SPANISH + 'first.adx': adx(), dialogue.SPANISH + 'second.adx': adx()})
        result = dialogue.map_slots(contents, contents.__getitem__, audio, 2)
        self.assertEqual(result, {1: dialogue.SPANISH + 'first.adx', 0: dialogue.SPANISH + 'second.adx'})
        del audio.entries[dialogue.SPANISH + 'second.adx']
        with self.assertRaises(ValueError):
            dialogue.map_slots(contents, contents.__getitem__, audio, 2)

    def test_mapping_rejects_conflicts_missing_slots_and_bad_event_offsets(self):
        contents = {'audio/dialog_base/dialog_base.babf': catalog([('A', ['one']), ('B', ['two'])]),
                    'audio/a/a.babf': catalog([('A', ['one']), ('B', ['two'])]),
                    'audio/a/a.xsb': xsb([('A', [0]), ('B', [0])])}
        audio = Audio({dialogue.SPANISH + 'dialog_base_s.babf': contents['audio/a/a.babf'],
                       dialogue.SPANISH + 'one.adx': adx(), dialogue.SPANISH + 'two.adx': adx()})
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            dialogue.map_slots(contents, contents.__getitem__, audio, 1)
        contents['audio/a/a.xsb'] = xsb([('A', [0])])
        with self.assertRaisesRegex(ValueError, 'cover'):
            dialogue.map_slots(contents, contents.__getitem__, audio, 2)
        bad = bytearray(contents['audio/a/a.xsb'])
        struct.pack_into('<I', bad, 76, 0xFFFFFF00)
        with self.assertRaises(ValueError):
            list(dialogue.cue_waves(bad))

    def test_full_bank_retains_silent_originals_and_other_resources(self):
        source, audio = fixture()
        notifications = []
        result = dialogue.convert(audio, source, lambda: None,
                                  lambda k, m, **kw: notifications.append(kw))
        _, _, original = dialogue.archive(source)
        _, _, output = dialogue.archive(result)
        self.assertEqual(output('audio/unchanged.bin'), b'preserve me')
        self.assertEqual(output('audio/test/test.xsb'), original('audio/test/test.xsb'))
        before, after = original(dialogue.DIALOGUE), output(dialogue.DIALOGUE)
        start = struct.unpack_from('<I', after, 32)[0]
        self.assertEqual(start + struct.unpack_from('<I', after, 36)[0], len(after))
        for i in range(1544):
            flags, fmt, offset, size, loop_start, loop_size = struct.unpack_from('<6I', after, 80 + i*24)
            self.assertEqual((flags, loop_start, loop_size, offset % 2048), (0, 0, 0, 0))
            if i % 3 == 0:
                self.assertEqual(fmt, 768005)
                self.assertEqual(after[start+offset:start+offset+size], before[start+i*2048:start+i*2048+36])
            else:
                self.assertEqual(fmt, dialogue.PCM_FORMAT)
                self.assertEqual(after[start+offset:start+offset+size], dialogue.decode_adx(adx(residual=0x12)))
        self.assertEqual(notifications[-1], dict(translated=1029, original_fallbacks=515))
        percentages = [n['percent'] for n in notifications if 'percent' in n]
        self.assertEqual(percentages, sorted(percentages))
        self.assertEqual(percentages[-1], 100)

    def test_cancel_and_bad_original_fail_without_touching_inputs(self):
        source, audio = fixture()
        def cancel():
            raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            dialogue.convert(audio, source, cancel, lambda *a, **kw: None)
        with self.assertRaises(ValueError):
            dialogue.convert(audio, source[:-1], lambda: None, lambda *a, **kw: None)


if __name__ == '__main__':
    unittest.main()
