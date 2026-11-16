"""Deferred conversion keeps table bytes, cancellation, and failures intact."""
from concurrent.futures import Future
import hashlib
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import character_assets as art
import character_campaign as campaign
import third_person_animation as animation


class DeferredPreparationTests(unittest.TestCase):
    def test_sniper_fixed_reference_is_available_to_each_sample(self):
        actor = SimpleNamespace(binding={'actor': 'Chaz'}, stance='STAND',
                                bind={}, ready={}, ready_world={}, parents={})
        data = struct.pack('<6I', 20, 0xf11e0006, 22, 0, 0, 0x10000000)
        reference = object()
        def stage(pack, weapon, groups, prefix, convert, **kwargs):
            return convert(actor, data, 'Movement UB Rifle')
        def bake(actor, data, transform, **kwargs):
            return [transform(actor, None, phase) for phase in (0., .5, 1.)]
        for mode, method in (('initial', 'initial_sniper'), ('frame', 'sniper_frame')):
            with patch.object(campaign, 'weapon_stage', stage), patch.object(campaign, 'bake', bake), \
                    patch.object(campaign.p, 'world', return_value={}), \
                    patch.object(campaign.p, 'localize', return_value=reference), \
                    patch.object(campaign.pose, 'ring', return_value={}), \
                    patch.object(campaign.pose, 'frame_correct', return_value=reference), \
                    patch.object(campaign.pose, method, return_value='pose') as sample:
                result = campaign.sniper_stage(None, mode, {'initial_arcs': {'Chaz|STAND': 10.}})
            self.assertEqual(result, ['pose'] * 3)
            for call in sample.call_args_list:
                self.assertIs(call.kwargs['reference'], reference)

    def test_worker_reads_keep_hash_checks_and_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'test.pck'
            archive.write_bytes(b'original')
            metadata = dict(originals={'test': {'size': 8}}, sources={
                'clip': dict(archive='test', offset=0, size=8,
                             sha256=hashlib.sha256(b'original').hexdigest()),
                'bad': dict(archive='test', offset=0, size=8, sha256='0' * 64)})
            stopped = multiprocessing.get_context('spawn').Event()
            animation._start_character_worker({'test': archive}, metadata, {}, {}, {}, {}, stopped)
            source = animation._worker_inputs[0]
            try:
                self.assertEqual(source.read('clip'), b'original')
                with self.assertRaisesRegex(ValueError, 'verification failed'):
                    source.read('bad')
                stopped.set()
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    source.read('clip')
            finally:
                for stream in source.streams.values():
                    stream.close()
                animation._worker_inputs = None

    def setUp(self):
        node = dict(name='KeyframeAnimation', value=None,
                    attributes={'Name': 'original', 'AnimationID': 'RELOAD'},
                    children=[dict(name='Modifier', value=None, children=[],
                                   attributes={'Flag': 'CROSSBOW'})])
        self.tree = dict(name='AnimationSystem', value=None, attributes={}, children=[
            dict(name='AnimationGroup', value=None,
                 attributes={'ToolName': 'Reload Crossbow', 'KeyedAnimationCount': '1'},
                 children=[node])])
        self.raw = art.encode(self.tree)
        self.pack = campaign.Overlay(lambda path: self.raw if path == 'table' else b'clip', lambda: None)

    def run_stage(self, convert, **options):
        with patch.object(campaign.pose, 'Actor', side_effect=lambda *args:
                          SimpleNamespace(binding={'table': 'table'})):
            return campaign.weapon_stage(self.pack, 'CROSSBOW', {'Reload Crossbow'},
                                         'test', convert, aliases={'test'}, **options)

    def test_deferred_output_is_identical(self):
        expected = self.run_stage(lambda *args: b'converted')
        def deferred(*args):
            future = Future()
            future.set_result(b'converted')
            return future
        self.assertEqual(self.run_stage(deferred), expected)

    def test_worker_failure_cancels_remaining_jobs(self):
        failed, waiting = Future(), Future()
        failed.set_exception(ValueError('invalid animation'))
        jobs = iter((failed, waiting))
        with self.assertRaisesRegex(ValueError, 'invalid animation'):
            self.run_stage(lambda *args: next(jobs))
        self.assertTrue(waiting.cancelled())

    def test_checked_result_resolver_preserves_output_and_failure_cancellation(self):
        expected = self.run_stage(lambda *args: b'converted')
        resolved = []
        def deferred(*args):
            future = Future()
            future.set_result(('private-result', 'digest'))
            return future
        def resolve(future):
            self.assertEqual(future.result(), ('private-result', 'digest'))
            resolved.append(future)
            return b'converted'
        self.assertEqual(self.run_stage(deferred, resolve_future=resolve), expected)
        self.assertEqual(len(resolved), 2)

        complete, waiting = Future(), Future()
        complete.set_result(('private-result', 'bad-digest'))
        jobs = iter((complete, waiting))
        def fail(future):
            raise ValueError('Worker result failed verification')
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            self.run_stage(lambda *args: next(jobs), resolve_future=fail)
        self.assertTrue(waiting.cancelled())

    def test_cancel_and_input_error_cancel_queued_jobs(self):
        for during_input in (False, True):
            waiting = Future()
            def fail():
                raise RuntimeError('cancelled')
            def convert(*args):
                if during_input:
                    self.pack.original_read = lambda path: fail()
                else:
                    self.pack.cancel = fail
                return waiting
            # A second alias exercises failure after an earlier job was queued.
            with patch.object(campaign.pose, 'Actor', side_effect=lambda *args:
                              SimpleNamespace(binding={'table': 'table'})):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    campaign.weapon_stage(self.pack, 'CROSSBOW', {'Reload Crossbow'},
                                          'test', convert, aliases={'first', 'second'})
            self.assertTrue(waiting.cancelled())
            self.setUp()


if __name__ == '__main__':
    unittest.main()
