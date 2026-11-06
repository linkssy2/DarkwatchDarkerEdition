"""Standalone fan-text preparation rejects unreviewed or malformed inputs."""
import hashlib
import struct
import unittest

from tools import prepare_ptbr_catalog as ptbr
from tests.test_spanish_text import table


class PortugueseCatalogueTests(unittest.TestCase):
    def test_only_pinned_zero_padding_can_be_removed(self):
        original = table([('example', 'Aperte aqui')])
        padded = original + bytes(12)
        pin = hashlib.sha256(padded).hexdigest()
        self.assertEqual(ptbr.read_padded(padded,pin,12), {'example':'Aperte aqui'})
        for raw,digest,padding in ((padded,'0'*64,12), (padded,pin,11),
                                   (padded,pin,1241), (padded+b'x',pin,12)):
            with self.assertRaises(ValueError):
                ptbr.read_padded(raw,digest,padding)
        wrong = original + b'x'
        with self.assertRaisesRegex(ValueError,'padding'):
            ptbr.read_padded(wrong,hashlib.sha256(wrong).hexdigest(),1)

    def test_nasal_vowels_are_normalized_without_touching_control_tokens(self):
        self.assertEqual(ptbr.normalized('N\xe4o, op\xe7\xf6es; ^Move^. N\xe3o, op\xe7\xf5es.'),
                         'N\xc3o, op\xc7\xd5es; ^Move^. N\xc3o, op\xc7\xd5es.')
        for value in ('bad\0text','bad\x01text','\u20ac','x'*4096,''):
            with self.assertRaises(ValueError):
                ptbr.normalized(value)

    def test_missing_conflicting_and_unchanged_spanish_need_explicit_review(self):
        original = {'one_e.bxml':{'missing':'Absent phrase','same':'Same phrase',
                                'conflict':'A context','token':'Press ^Jump^'},
                    'two_e.bxml':{'conflict':'A context'}}
        fan = {'one_s.bxml':{'same':'Sin cambiar','conflict':'Frase A','token':'Aperte X'},
               'two_s.bxml':{'conflict':'Frase B'}}
        spanish = {'one_s.bxml':{'same':'Sin cambiar'}}
        raw, report = ptbr.catalogue(original,fan,spanish,{})
        self.assertIsNone(raw)
        self.assertEqual(report['review_count'],4)
        self.assertEqual(report['reasons'],{'missing':1,'conflict':1,
                         'unchanged_spanish_requires_review':1,'semantic_tokens':1})
        edits = {ptbr.ps2_text.context_id(k,e):text for k,e,text in (
            ('missing','Absent phrase','Frase ausente'),('same','Same phrase','Igual'),
            ('conflict','A context','Uma frase'),('token','Press ^Jump^','Aperte ^Jump^'))}
        raw, report = ptbr.catalogue(original,fan,spanish,edits)
        self.assertEqual(raw[:8],b'DWES0003')
        self.assertEqual(struct.unpack_from('<I',raw,8)[0],4)
        self.assertEqual(report['review_count'],0)
        self.assertNotIn(b'Absent phrase',raw)
        self.assertNotIn(b'missing',raw)
        self.assertFalse(report['original_contexts_embedded'])

    def test_review_cannot_change_semantics_or_borrow_another_context(self):
        original = {'one_e.bxml':{'same':'Press ^Jump^'}}
        for key,english in (('other','Press ^Jump^'),('same','Another meaning')):
            with self.assertRaisesRegex(ValueError,'Corrections'):
                ptbr.catalogue(original,{}, {}, {ptbr.ps2_text.context_id(key,english):'Aperte ^Jump^'})
        raw, report = ptbr.catalogue(original,{}, {},
            {ptbr.ps2_text.context_id('same','Press ^Jump^'):'Aperte ^Fire^'})
        self.assertIsNone(raw)
        self.assertEqual(report['reasons'],{'semantic_tokens':1})


if __name__ == '__main__':
    unittest.main()
