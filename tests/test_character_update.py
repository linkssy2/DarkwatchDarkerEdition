"""Metadata-only update, bounded preload writing and staged failure checks."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'launcher'))
import character_archive as archive
import character_assets as art
import character_content as content
import character_update as update
from test_launcher_characters import tiny_archive, pin


def fixture():
    original = tiny_archive()
    before = archive.compose(original, {'fixture/replaced.bin':b'old', 'fixture/cached.bin':b'cached'})
    changed = {'fixture/replaced.bin':b'new locally derived resource'}
    after = archive.compose(original, {**changed, 'fixture/cached.bin':b'cached'})
    parsed = archive.read(after)
    prefix = archive.read(original)['start']
    entries = [dict(name=e['name'], offset=e['offset'], size=e['size'], slot=e['slot'], next=e['key']&parsed['mask'])
               for e in parsed['entries']]
    resources = []
    for entry in sorted(entries, key=lambda e:e['offset']):
        if entry['offset'] < prefix:
            continue
        data = after[entry['offset']:entry['offset']+entry['size']]
        resources.append(dict(name=entry['name'], source='generated' if entry['name'] in changed else 'previous', **pin(data)))
    plan = dict(schema_version=1, from_revision='character-tala-presentation-v26',
        to_revision='character-movement-reload-v27', dependencies=[], suffixes=[],
        archives={'packfile.pck':dict(before=pin(before), after=pin(after), prefix=pin(before[:prefix]),
            index=dict(capacity=len(parsed['rows']), start=parsed['start'], entries=entries), resources=resources)})
    metadata = dict(content_revision=plan['to_revision'], installed={'packfile.pck':pin(after)},
                    originals={'packfile.pck':pin(original)}, sources={})
    return original, before, after, changed, plan, metadata


class CharacterUpdateTests(unittest.TestCase):
    def test_body_resources_drop_only_unreferenced_intermediate_animations(self):
        def node(name,attributes=None,children=()):
            return dict(name=name,attributes=dict(name=name,**(attributes or {})),children=list(children),value=None)
        def table(*paths):
            return art.encode(node('AnimationSystem',children=[node('AnimationGroup',children=[
                node('KeyframeAnimation',dict(Name=path)) for path in paths])]))
        actors=node('Actors',children=[node(name,children=[
            node('AlternativeModelsRenderComponent',children=[node('m_modelResourcePath',dict(value='fixture/model'))]),
            node('LocatorAttachmentComponent',children=[node('m_locatorFileName',dict(value='fixture/locator'))]),
            node('AnimationComponent',children=[node('m_AnimationFiles',children=[
                node('element',dict(key='Multi',value='fixture/'+name))])])]) for name in ('One','Two')])
        previous={update.animation.CHARACTERS:art.encode(actors), 'fixture/model.rx1':b'model',
                  'fixture/locator.bllist':b'locator', 'fixture/one.bxml':table('fixture/original'),
                  'fixture/two.bxml':table('fixture/original')}
        saved=dict(previous)
        def held(raw,read,original,model,locator,basis,actor,offsets):
            actor=actor.lower()
            additions={'fixture/shared.sanm':b'shared', 'fixture/temporary-'+actor+'.sanm':b'intermediate'}
            if actor=='one':
                additions.update({'fixture/only-two.sanm':b'referenced by a later table',
                                  'fixture/preserved.bin':b'not an animation'})
            return table('fixture/shared','fixture/temporary-'+actor),additions
        def mechanical(raw,read,original,model,locator,basis,actor,offsets):
            actor=actor.lower()
            self.assertEqual(read('fixture/shared.sanm'),b'shared')
            paths=['fixture/shared','fixture/mechanical-'+actor]
            if actor=='two':paths.append('fixture/only-two')
            return table(*paths),{'fixture/mechanical-'+actor+'.sanm':b'completed '+actor.encode()}
        with patch.object(update.animation,'PLAYERS',()), patch.object(update.animation,'COOP_PLAYERS',('One','Two')), \
                patch.object(update.character_weapon_pose,'read_grip_offsets',return_value={}), \
                patch.object(update,'starter_fanning',side_effect=lambda raw,*args:(raw,{})), \
                patch.object(update,'starter_reload',side_effect=lambda raw,*args:(raw,{})), \
                patch.object(update.enemy_blood,'append',side_effect=lambda actors:actors), \
                patch.object(update.character_weapon_hold,'prepare_aimed_motion_table',side_effect=held), \
                patch.object(update.character_reload,'prepare_mechanical_table',side_effect=mechanical):
            result=update.body_resources(previous.__getitem__,SimpleNamespace(read=lambda path:b'original',report=lambda message:None))
        self.assertEqual(set(result),{'fixture/one.bxml','fixture/two.bxml','fixture/shared.sanm',
            'fixture/only-two.sanm','fixture/mechanical-one.sanm','fixture/mechanical-two.sanm','fixture/preserved.bin',
            update.animation.CHARACTERS})
        self.assertEqual(result[update.animation.CHARACTERS], previous[update.animation.CHARACTERS])
        self.assertEqual(set(update.animation.clips(result['fixture/two.bxml'])),
                         {'fixture/shared','fixture/mechanical-two','fixture/only-two'})
        self.assertEqual(previous,saved)

    def prepare_fixture(self, folder):
        original,before,after,changed,plan,metadata = fixture()
        root = Path(folder)
        assets,previous,payload = (root/name for name in ('stage','previous','payload'))
        for path in (assets,previous,payload):
            path.mkdir()
        (assets/'packfile.pck').write_bytes(original)
        (previous/'packfile.pck').write_bytes(before)
        packed = gzip.compress(json.dumps(plan).encode(),mtime=0)
        (payload/update.RECIPE_NAME).write_bytes(packed)
        return assets,previous,payload,metadata,changed,after,hashlib.sha256(packed).hexdigest()

    def test_reuses_previous_bytes_and_exact_index_without_changing_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            assets,previous,payload,metadata,changed,after,digest = self.prepare_fixture(folder)
            saved = (previous/'packfile.pck').read_bytes()
            with patch.object(update,'RECIPE_SHA256',digest), patch.object(update,'body_resources',return_value=changed):
                self.assertTrue(update.try_prepare(assets,payload,previous,metadata,lambda:None,lambda message:None))
            self.assertEqual((assets/'packfile.pck').read_bytes(),after)
            self.assertEqual((previous/'packfile.pck').read_bytes(),saved)
            self.assertEqual([p.name for p in assets.iterdir()],['packfile.pck'])

    def test_corrupt_or_linked_previous_is_a_cache_miss(self):
        for linked in (False,True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as folder:
                assets,previous,payload,metadata,changed,_,digest = self.prepare_fixture(folder)
                original = (assets/'packfile.pck').read_bytes()
                source = previous/'packfile.pck'
                if linked:
                    os.link(source,previous/'second-link.pck')
                else:
                    raw = bytearray(source.read_bytes());raw[0] ^= 1;source.write_bytes(raw)
                with patch.object(update,'RECIPE_SHA256',digest), patch.object(update,'body_resources') as producer:
                    self.assertFalse(update.try_prepare(assets,payload,previous,metadata,lambda:None,lambda message:None))
                    producer.assert_not_called()
                self.assertEqual((assets/'packfile.pck').read_bytes(),original)

    def test_cancel_valueerror_during_admission_and_write_keeps_stage(self):
        class Cancelled(ValueError):pass
        for writing in (False,True):
            with self.subTest(writing=writing), tempfile.TemporaryDirectory() as folder:
                assets,previous,payload,metadata,changed,_,digest = self.prepare_fixture(folder)
                original = (assets/'packfile.pck').read_bytes()
                stop = not writing
                def cancel():
                    if stop:raise Cancelled('cancelled')
                def progress(message):
                    nonlocal stop
                    if message.startswith('Writing updated character archive:'):stop=True
                with patch.object(update,'RECIPE_SHA256',digest), patch.object(update,'body_resources',return_value=changed):
                    with self.assertRaises(Cancelled):
                        update.try_prepare(assets,payload,previous,metadata,cancel,progress)
                self.assertEqual((assets/'packfile.pck').read_bytes(),original)
                self.assertEqual([p.name for p in assets.iterdir()],['packfile.pck'])

    def test_bad_generated_resource_cannot_replace_staged_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            assets,previous,payload,metadata,changed,_,digest = self.prepare_fixture(folder)
            original = (assets/'packfile.pck').read_bytes()
            changed = {name:b'incorrect' for name in changed}
            with patch.object(update,'RECIPE_SHA256',digest), patch.object(update,'body_resources',return_value=changed):
                with self.assertRaisesRegex(ValueError,'resource verification'):
                    update.try_prepare(assets,payload,previous,metadata,lambda:None,lambda message:None)
            self.assertEqual((assets/'packfile.pck').read_bytes(),original)
            self.assertEqual([p.name for p in assets.iterdir()],['packfile.pck'])

    def test_preload_suffix_matches_full_canonical_encoder(self):
        rows=[('fixture/one','TextureResource'),('fixture/two','ModelResource'),('fixture/one','TextureResource'),
              ('fixture/three','ModelResource'),('fixture/four','TextureResource')]
        # Unique name/type keys are required by the native resource list.
        rows=rows[:2]+rows[3:]
        tree=dict(name='ResourceSetCInfo',attributes={},value=None,
                  children=[dict(name='data',attributes={},value=None,children=[art.element(dict(name=n,type=k))for n,k in rows])])
        raw=art.encode(tree)
        suffix=[('characters/Generated/A','AnimationResource'),('fixture/one','TextureResource')]
        for keep in range(len(rows)+1):
            expected=copy.deepcopy(tree)
            art.named(expected,'data')['children']=art.named(expected,'data')['children'][:keep]
            expected=art.append_resources(expected,suffix)[0]
            self.assertEqual(update.preload(raw,keep,suffix),art.encode(expected))
        with self.assertRaises(ValueError):update.preload(raw[:7],1,suffix)

    def test_recipe_rejects_paths_extents_dependency_indexes_and_duplicate_slots(self):
        *_,plan,metadata=fixture()
        def changed_entry(value):
            return next(e for e in value['archives']['packfile.pck']['index']['entries'] if e['offset']>=value['archives']['packfile.pck']['prefix']['size'])
        def cross_prefix(value):
            item=value['archives']['packfile.pck']
            entry=next(e for e in item['index']['entries'] if e['offset']==0)
            entry['size']=item['prefix']['size']+1
        changes=[lambda value:changed_entry(value).update(name='../escape'),
                 lambda value:changed_entry(value).update(offset=-1), cross_prefix,
                 lambda value:changed_entry(value).update(offset=value['archives']['packfile.pck']['index']['start']+1),
                 lambda value:value.update(dependencies=[['fixture/one','TextureResource']],suffixes=[[1]]),
                 lambda value:changed_entry(value).update(size=True),
                 lambda value:value['archives']['packfile.pck']['index']['entries'].append(copy.deepcopy(changed_entry(value)))]
        for change in changes:
            candidate=copy.deepcopy(plan);change(candidate)
            with self.subTest(change=changes.index(change)),self.assertRaises(ValueError):
                update.validate_recipe(candidate,metadata)

    def test_recipe_hash_is_checked_before_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            _,_,payload,metadata,_,_,digest=self.prepare_fixture(folder)
            with patch.object(update,'RECIPE_SHA256',digest):
                update.recipe(payload,metadata)
                (payload/update.RECIPE_NAME).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'recipe changed'):update.recipe(payload,metadata)


if __name__=='__main__':unittest.main()
