"""Synthetic character work reports progress and honors cancellation in CPU loops."""
from contextlib import ExitStack, contextmanager
import copy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
sys.path.insert(0, str(ROOT / 'tests'))
import character_animation as animation
import character_assets as art
import character_content as content
import character_roster as roster
from test_character_animation import clip, model


def node(name, children=(), attributes=None, value=None):
    return dict(name=name, children=list(children), attributes=attributes or {}, value=value)


def animation_source():
    resources = {path: model() for path in (animation.STORM, animation.CHAZ, animation.CASSIDY)}
    resources.update({f'characters/fixture/clip{i}.sanm': clip() for i in range(619)})
    first = 0
    for _, table, _, _, witness, count in animation.TABLES:
        names = [f'characters/fixture/clip{i}' for i in range(first, first + count)]
        first += count
        resources[table] = art.encode(node('root', [
            node('KeyframeAnimation', attributes={'Name': name}) for name in names]))
        entries = [(table[:-5], 'AnimatedCharacterResource')]
        entries += [(name, kind) for name in names for kind in animation.KINDS]
        resources[witness] = art.encode(node('root', [node('data', [
            art.element(dict(name=name, type=kind)) for name, kind in entries])]))
    # One shared clip exercises the existing deduplication without changing its output.
    names = ['characters/fixture/clip0'] + [f'characters/fixture/clip{i}' for i in range(329, 619)]
    resources['characters/multiplayer/multiplayeranimation.bxml'] = art.encode(node('root', [
        node('KeyframeAnimation', attributes={'Name': name}) for name in names]))
    return resources


@contextmanager
def roster_fixture(cancel, progress):
    """Stub body adaptation only; exercise the actual 102-area/35-pair writer."""
    def actor(name):
        return node('Actor', [node('Component', [node('Field', attributes={
            'name': 'm_handActorName', 'value': 'FixtureHands'})],
            {'name': 'InventoryComponent'})], {'name': name})
    actors = node('root', [actor(name) for name in (
        'Chaz', 'JerichoCoop', 'CassidySolo', 'CassidyPlayerTwo',
        'CassidySpectralSolo', 'CassidySpectralPlayerTwo')])
    actors['children'].append(node('Actor', attributes={'name': 'FixtureHands'}))
    actors_raw = art.encode(actors)
    resources = {content.CHARACTERS: actors_raw}
    for prefix, body, _ in roster.ROSTER.values():
        resources[body + '.jlist'] = b'root'
        resources[body + '.rx1'] = b'fixture model'
        resources[body + '.bllist'] = art.encode(node('root'))
    for base in ('characters/player_third/base_chaz',
                 'characters/multiplayer/base_dwstormtrooper_coop',
                 'characters/player_first/base_pov_chaz'):
        for extension in ('jlist', 'llist', 'bllist'):
            resources[base + '.' + extension] = art.encode(node('root'))
    resources['characters/multiplayer/base_dwstormtrooper_coop.bllist'] = art.encode(
        node('root', [node('locator', attributes={'name': 'loc_RightHand', 'parent': 'root',
                                               'pos': '0, 0, 0', 'rot': '0, 0, 0, 1'})]))
    resources[roster.rw.SOURCE] = b'fixture hands'
    resources['audio/tala/tala.babf'] = art.encode(node('root', [node('prototypes', [
        art.element({'id': cue}) for cue in
        ('TALA_ATTACK', 'TALA_DMG_LO', 'TALA_DMG_M', 'TALA_DMG_HI', 'TALA_DEATH')])]))
    for area in range(102):
        path = f'levels/singleplayer/fixture/streaming/area{area:03}_resources.bxml'
        resources[path] = art.encode(node('ResourceSetCInfo', [node('data', [
            art.element(dict(name='fixture/original', type='FixtureResource'))])]))
        audio = path.replace('/streaming/', '/resources/audio/').replace('_resources', '')[:-5] + '.bblf'
        resources[audio] = art.encode(node('root', [node('banks')]))
    raw = bytearray()
    pins = {}
    for path, data in resources.items():
        pins[path] = dict(archive='fixture.pck', offset=len(raw), size=len(data),
                          sha256=content.pck.sha(data))
        raw.extend(data)
    source = content.Source({'fixture.pck': io.BytesIO(raw)},
                            dict(originals={'fixture.pck': {'size': len(raw)}}, sources=pins),
                            cancel, progress)
    groups = {'packfile.pck': {content.CHARACTERS: actors_raw}}
    empty = {'packfile.pck': {}}
    def prepare_animation(*args, **kwargs):
        kwargs['cancel']()
        kwargs['progress']('co-op animations: 1/1')
        return {}, [], []
    with ExitStack() as stack:
        for target, name, value in (
            (animation, 'prepare', prepare_animation),
            (animation, 'frames', lambda data: {0: dict(rotation=(1.,), translation=(0.,))}),
            (roster, '_hands', lambda *args: b'fixture derived hands'),
            (roster, '_actor', lambda original, identity, solo:
             (actor(f'Fixture{identity}{solo}'), 'FixtureHands', f'fixture/locator{identity}{solo}')),
            (roster, '_dependencies', lambda *args: [('fixture/derived', 'FixtureResource')]),
            (art, 'solo_locators', lambda *args: node('root')),
            (art, 'adapt_locators', lambda *args: node('root')),
            (art, 'jericho_locators', lambda *args: node('root')),
            (roster.character_boss_effects, 'dependencies', lambda: []),
        ):
            stack.enter_context(patch.object(target, name, value))
        yield source, groups, empty, empty


class PreparationProgressTests(unittest.TestCase):
    def test_progress_callback_can_cancel_before_next_work_unit(self):
        requested = False
        messages = []
        def cancel():
            if requested:
                raise InterruptedError('cancelled')
        def report(message):
            nonlocal requested
            messages.append(message)
            requested = True
        source = content.Source({}, {}, cancel, report)
        with self.assertRaises(InterruptedError):
            source.report('Preparing character')
        self.assertEqual(messages, ['Preparing character'])
        with self.assertRaises(InterruptedError):
            source.report('Must not be displayed')
        self.assertEqual(len(messages), 1)

    def test_animation_progress_is_bounded_and_outputs_are_identical(self):
        resources = animation_source()
        expected = animation.prepare(resources.__getitem__, art.decode, art.encode)
        messages = []
        actual = animation.prepare(resources.__getitem__, art.decode, art.encode,
                                   progress=messages.append)
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual[0]), 624)
        self.assertIn('co-op animations: 25/300', messages)
        self.assertIn('co-op animations: 300/300', messages)
        self.assertIn('horse-riding animations: 16/16', messages)
        self.assertEqual(messages[-1], 'single-player animations: 291/291')
        self.assertLess(len(messages), 40)

    def test_animation_cancel_does_not_wait_until_next_source_read(self):
        resources = animation_source()
        requested = False
        reads = []
        def read(path):
            reads.append(path)
            return resources[path]
        def report(message):
            nonlocal requested
            requested |= message == 'co-op animations: 25/300'
        def cancel():
            if requested:
                raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            animation.prepare(read, art.decode, art.encode, cancel=cancel, progress=report)
        self.assertEqual(sum(path.endswith('.sanm') for path in reads), 25)

    def test_campaign_progress_reaches_all_areas_without_changing_input(self):
        messages = []
        with roster_fixture(lambda: None, messages.append) as args:
            before = copy.deepcopy(args[1:])
            result, _ = roster.prepare(*args)
            self.assertEqual(args[1:], before)
        self.assertEqual(len(result['LvlSingl.pck']), 3570)
        self.assertEqual(len(result['fixture.pck']), 3570)
        self.assertEqual(messages[-1], 'Preparing campaign character combinations: 102/102 areas')
        self.assertEqual(sum('campaign character combinations:' in value for value in messages), 103)
        for name in ('Civilian Jericho', 'Trooper', 'Blue and Red Troopers', 'Tala'):
            self.assertIn(f'Preparing {name} co-op animations: 1/1', messages)

    def test_campaign_cancels_inside_area_before_next_combination(self):
        calls = 0
        append = art.append_resource_bytes
        def cancel():
            if calls == 3:
                raise InterruptedError('cancelled')
        def adapted(*args):
            nonlocal calls
            calls += 1
            return append(*args)
        with roster_fixture(cancel, lambda message: None) as args:
            with patch.object(art, 'append_resource_bytes', adapted), self.assertRaises(InterruptedError):
                roster.prepare(*args)
        self.assertEqual(calls, 3)


if __name__ == '__main__':
    unittest.main()
