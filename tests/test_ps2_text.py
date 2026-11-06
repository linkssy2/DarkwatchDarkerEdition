"""PS2-only text preparation with synthetic archives and no bundled game text."""
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import ps2_text
from test_ps2_dialogue import archive
from test_spanish_text import table


class Pack:
    def __init__(self, resources):
        self.entries = resources
        self.reads = []

    def read(self, name):
        self.reads.append(name)
        return self.entries[name]


def unpack(raw):
    assert raw[:8] == b'DWES0003'
    count, = struct.unpack_from('<I', raw, 8)
    result, pos = {}, 12
    for _ in range(count):
        identity, length = struct.unpack_from('<QI', raw, pos)
        pos += 12
        result[identity] = raw[pos:pos + length].decode('latin1')
        pos += length
    assert pos == len(raw)
    return result


class Ps2TextTests(unittest.TestCase):
    def test_conversion_reads_only_same_table_ps2_and_exact_project_corrections(self):
        first = 'userinterface/localization/one_e.bxml'
        second = 'userinterface/localization/two_e.bxml'
        original = {first: {'spoken': 'Move away', 'control': 'Press ^Jump^.'},
                    second: {'spoken': 'Move away'}}
        xbox = archive({p: table(list(rows.items())) for p, rows in original.items()}
                       | {'world/untouched.bin': b'unchanged original resource'})
        ps2 = Pack({'userinterface/localization/one_s.bxml': table([('spoken', 'Atras'), ('control', 'Boton X')])
                    .replace(b'Atras', b'Atr\xe1s'),
                    'userinterface/localization/unrelated_s.bxml': b'must not be parsed'})
        control_id = ps2_text.context_id('control', 'Press ^Jump^.')
        correction = json.dumps(dict(schema=1, contexts={f'{control_id:016x}': 'Pulsa ^Jump^.'}))
        with patch.object(ps2_text, 'CONTEXT_SHA256', ps2_text.inventory(original)), \
                patch.object(Path, 'read_text', return_value=correction):
            result = unpack(ps2_text.convert(ps2, xbox))
        self.assertEqual(result, {control_id: 'Pulsa ^Jump^.',
                                 ps2_text.context_id('spoken', 'Move away'): 'AtrÁs'})
        self.assertEqual(ps2.reads, ['userinterface/localization/one_s.bxml'])
        self.assertEqual(ps2_text.tables(xbox), original)
        self.assertIn(b'unchanged original resource', xbox)

    def test_installed_original_context_inventory_must_match_before_disc_reads(self):
        original = {'userinterface/localization/one_e.bxml': {'same': 'Original meaning'}}
        altered = archive({'userinterface/localization/one_e.bxml': table([('same', 'Different meaning')])})
        ps2 = Pack({})
        with patch.object(ps2_text, 'CONTEXT_SHA256', ps2_text.inventory(original)), \
                self.assertRaisesRegex(ValueError, 'installed Xbox text'):
            ps2_text.convert(ps2, altered)
        self.assertFalse(ps2.reads)

    def test_missing_context_cannot_borrow_from_other_id_or_other_meaning(self):
        original = {'one_e.bxml': {'line': 'My line'}}
        for ps2 in ({'one_s.bxml': {'other_line': 'Traducción'}},
                    {'two_s.bxml': {'line': 'Traducción'}}):
            with self.assertRaisesRegex(ValueError, 'Missing Spanish context'):
                ps2_text.catalogue(original, ps2, {})
        # A deliberate project correction is bound to the original English too.
        with self.assertRaisesRegex(ValueError, 'Missing Spanish context'):
            ps2_text.catalogue(original, {}, {ps2_text.context_id('line', 'Another line'): 'Otra línea'})

    def test_disc_wording_is_used_when_no_project_ui_override_exists(self):
        original = {'one_e.bxml': {'spoken': 'An English utterance'}}
        ps2 = {'one_s.bxml': {'spoken': 'Otra frase del doblaje'}}
        result, report = ps2_text.catalogue(original, ps2, {})
        self.assertEqual(unpack(result), {ps2_text.context_id('spoken', 'An English utterance'):
                                         'Otra frase del doblaje'})
        self.assertEqual(report['sources'], {'ps2_same_table': 1})

    def test_locale_reads_only_its_table_and_its_context_corrections(self):
        original={'userinterface/localization/one_e.bxml':{'line':'A line','button':'Press ^Jump^'}}
        xbox=archive({p:table(list(rows.items())) for p,rows in original.items()})
        for language,suffix,label in (('fr','f','french'),('de','g','german'),('it','i','italian')):
            with self.subTest(language=language):
                selected='userinterface/localization/one_'+suffix+'.bxml'
                ps2=Pack({selected:table([('line',language+' text'),('button','Missing prompt')]),
                          'userinterface/localization/one_s.bxml':b'must not read Spanish'})
                identity=ps2_text.context_id('button','Press ^Jump^')
                correction=json.dumps({'schema':1,'contexts':{f'{identity:016x}':language+' ^Jump^'}})
                reads=[]
                def read(path,**kwargs):
                    reads.append(path.name)
                    return correction
                with patch.object(ps2_text,'CONTEXT_SHA256',ps2_text.inventory(original)), \
                     patch.object(Path,'read_text',read):
                    raw=ps2_text.convert(ps2,xbox,language=language)
                self.assertEqual(ps2.reads,[selected])
                self.assertEqual(reads,['ps2-'+label+'-corrections.json'])
                self.assertEqual(unpack(raw),{identity:language+' ^Jump^',ps2_text.context_id('line','A line'):language+' text'})

    def test_all_native_disc_accents_and_locale_rejections(self):
        self.assertEqual(ps2_text.normalized('àâäçèêëìîïòôöùûüß'), 'ÀÂÄÇÈÊËÌÎÏÒÔÖÙÛÜß')
        for invalid in ('œ','ÿ','\x80','\0'):
            with self.assertRaises(ValueError): ps2_text.normalized(invalid)
        for language in ('en','pt-BR','../fr',None):
            with self.assertRaisesRegex(ValueError,'Unsupported PS2 disc language'):
                ps2_text.convert(Pack({}),b'not opened',language=language)

    def test_new_locales_require_resolved_missing_conflicts_and_semantic_tokens(self):
        original={'one_e.bxml':{'line':'Press ^Jump^'},'two_e.bxml':{'line':'Press ^Jump^'}}
        for language,suffix in (('fr','f'),('de','g'),('it','i')):
            for candidate,reason in (({},'Missing'),
                ({'one_'+suffix+'.bxml':{'line':'A ^Jump^'},'two_'+suffix+'.bxml':{'line':'B ^Jump^'}},'Conflicting'),
                ({'one_'+suffix+'.bxml':{'line':'A ^Fire^'}},'semantic tokens')):
                with self.subTest(language=language,reason=reason),self.assertRaisesRegex(ValueError,reason):
                    ps2_text.catalogue(original,candidate,{},language)


if __name__ == '__main__':
    unittest.main()
