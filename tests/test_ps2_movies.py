"""Synthetic media exercises; no original video, audio or game code is included."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_archive
import ps2_movies as media


def adx(start=40, samples=64, value=17):
    raw = bytearray(start)
    raw[:8] = b'\x80\0' + struct.pack('>H', start - 4) + b'\x03\x12\x04\x02'
    struct.pack_into('>IIH', raw, 8, 48000, samples, 500)
    raw[18] = 4
    raw[24:32] = bytes([value]) * 8
    raw[start - 6:start] = b'(c)CRI'
    return bytes(raw) + bytes([value]) * (((samples + 31) // 32) * 36) + b'\x80\x01\0\x0e' + bytes(14)


def chunk(tag, payload):
    return tag + struct.pack('>I', len(payload)) + payload


def aix(tracks):
    result = chunk(b'AIXF', bytes(24))
    for offset in (0, 31):
        for sid, track in enumerate(tracks):
            payload = track[:31] if offset == 0 else track[31:]
            result += chunk(b'AIXP', bytes([sid, len(tracks)]) + struct.pack('>H', len(payload)) + bytes(4) + payload)
    return result + chunk(b'AIXE', bytes(8))


def pes(sid, payload, time=0):
    header = media.stamp(time, 3) + media.stamp(time, 1)
    return b'\0\0\1' + bytes([sid]) + struct.pack('>H', len(header) + len(payload)) + header + payload


def films(samples=64):
    audio = aix([adx(value=7), adx(value=8), adx(samples=32, value=9)])
    xbox = pes(0xc1, audio[:27]) + pes(0xe0, b'original-video-unchanged', 9000) + pes(0xc1, audio[27:], 12000)
    ps2 = b''.join(pes(sid, adx(288, samples, sid - 0xc0 + 1)) for sid in range(0xc0, 0xc5))
    ps2 += pes(0xe0, b'ps2-video-must-not-be-imported', 9500)
    return xbox, ps2


def archive(resources):
    payload = bytearray(2048)
    entries = []
    for name, data in sorted(resources.items()):
        entries.append(dict(name=name, offset=len(payload), size=len(data), pointer=0))
        payload.extend(data)
    start = len(payload)
    rows, names = character_archive.build_rows(entries, 64)
    payload.extend(struct.pack('<4I', 64, len(entries), 63, 0))
    for row in rows:
        payload.extend(struct.pack('<QII', *row))
    for name in names:
        if name is not None:
            payload.extend(struct.pack('<II', 0, len(name)) + name.encode('ascii'))
    payload.extend(bytes(32) + struct.pack('<II', start, 0xfffffffb))
    character_archive.read(payload)
    return bytes(payload)


def contents(raw):
    return {e['name']: raw[e['offset']:e['offset'] + e['size']] for e in character_archive.read(raw)['entries']}


class Ps2MovieTests(unittest.TestCase):
    def test_only_audio_payload_changes_and_spanish_four_selected(self):
        xbox, ps2 = films()
        output = media.convert_movie(xbox, ps2)
        self.assertEqual(len(output), len(xbox))
        cursor = 0
        for sid, start, end, pts, dts in media.packets(xbox):
            if sid == 0xc1:
                self.assertEqual(output[cursor:start], xbox[cursor:start])
                cursor = end
        self.assertEqual(output[cursor:], xbox[cursor:])
        tracks = media.adx_tracks(media.elementary(output)[0xc1])
        self.assertEqual(tracks[0], media.normalized_adx(media.elementary(ps2)[0xc4]))
        self.assertEqual(media.elementary(output)[0xe0], b'original-video-unchanged')
        original_tracks = media.adx_tracks(media.elementary(xbox)[0xc1])
        for before, silent in zip(original_tracks[1:], tracks[1:]):
            start, end = media.adx_extent(silent)
            self.assertEqual(silent[:24], before[:24])
            self.assertEqual(silent[32:start], before[32:start])
            self.assertEqual(silent[end:], before[end:])
            self.assertEqual(silent[24:32], bytes(8))
            self.assertFalse(any(silent[start:end]))

    def test_padded_header_normalization_preserves_prediction_history_and_blocks(self):
        original = adx(288, value=13)
        normalized = media.normalized_adx(original)
        self.assertEqual(normalized[4:32], original[4:32])
        self.assertEqual(normalized[40:], original[288:])
        self.assertEqual(media.normalized_adx(normalized), normalized)

    def test_timeline_mismatch_rejected_not_retimed(self):
        xbox, ps2 = films(samples=96)
        with self.assertRaisesRegex(ValueError, 'timeline'):
            media.convert_movie(xbox, ps2)

    def test_malformed_adx_and_unexpected_language_layout_rejected(self):
        original = adx(288)
        for offset, byte in ((4, 4), (7, 1), (18, 3), (19, 1), (32, 1), (282, 0)):
            damaged = bytearray(original)
            damaged[offset] = byte
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                media.normalized_adx(damaged)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            media.normalized_adx(original[:-1])
        xbox, ps2 = films()
        with self.assertRaisesRegex(ValueError, 'language stream'):
            media.convert_movie(xbox, pes(0xc4, original) + pes(0xe0, b'video'))

    def test_truncated_aix_and_component_size_changes_rejected(self):
        raw = aix([adx(), adx(), adx()])
        with self.assertRaises(ValueError):
            media.replace_aix(raw[:-3], [adx()] * 3, lambda: None)
        with self.assertRaisesRegex(ValueError, 'layout'):
            media.replace_aix(raw, [adx(samples=32)] * 3, lambda: None)
        with self.assertRaises(ValueError):
            list(media.packets(pes(0xc1, raw)[:-1]))

    def test_archive_preserves_unselected_extras_and_original_source(self):
        xbox, ps2 = films()
        resources = {'movies/m01s1.sfd': xbox, 'movies/animatic2.sfd': b'other-edit',
                     'movies/m02s1.sfd': b'no-spanish-track', 'movies/mainmenu.sfd': b'original-menu'}
        original = archive(resources)
        provider = Mock()
        provider.read.return_value = ps2
        notify = Mock()
        converted = media.convert(provider, original, lambda: None, notify)
        output = contents(converted)
        self.assertEqual(len(converted), len(original))
        parsed = character_archive.read(original)
        self.assertEqual(converted[parsed['start']:], original[parsed['start']:])
        provider.read.assert_called_once_with('movies/m01s1.sfd')
        self.assertEqual(contents(original), resources)
        self.assertNotEqual(output['movies/m01s1.sfd'], xbox)
        for name in resources.keys() - {'movies/m01s1.sfd'}:
            self.assertEqual(output[name], resources[name])
        notify.assert_called_once_with('progress', 'Preparing Spanish movie m01s1.sfd', percent=0)

    def test_overlapping_movie_resources_rejected(self):
        xbox, ps2 = films()
        original = bytearray(archive({'movies/m01s1.sfd': xbox, 'movies/mainmenu.sfd': b'other'}))
        parsed = character_archive.read(original)
        entries = {e['name']: e for e in parsed['entries']}
        other = entries['movies/mainmenu.sfd']
        struct.pack_into('<I', original, parsed['start'] + 16 + 16 * other['slot'] + 8,
                         entries['movies/m01s1.sfd']['offset'] + 1)
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            media.convert(Mock(), original, lambda: None, Mock())

    def test_no_selected_movies_returns_same_archive(self):
        original = archive({'movies/mainmenu.sfd': b'original'})
        provider = Mock()
        self.assertIs(media.convert(provider, original, lambda: None, Mock()), original)
        provider.read.assert_not_called()

    def test_cancellation_stops_before_read_and_during_packets(self):
        xbox, ps2 = films()
        provider = Mock()
        cancel = Mock(side_effect=InterruptedError('cancelled'))
        with self.assertRaises(InterruptedError):
            media.convert(provider, archive({'movies/m01s1.sfd': xbox}), cancel, Mock())
        provider.read.assert_not_called()
        count = 0
        def midway():
            nonlocal count
            count += 1
            if count == 4:
                raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            media.convert_movie(xbox, ps2, midway)
        self.assertEqual(count, 4)

    def test_exact_selected_resource_scope(self):
        self.assertEqual(len(media.MOVIES), 14)
        self.assertIn('movies/intro.sfd', media.MOVIES)
        self.assertNotIn('movies/animatic2.sfd', media.MOVIES)
        self.assertNotIn('movies/attract.sfd', media.MOVIES)


if __name__ == '__main__':
    unittest.main()
