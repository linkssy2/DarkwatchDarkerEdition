"""Keep native Jericho effects while excluding a foreign co-op eye overlay."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_assets as art


def node(tag, **attributes):
    return dict(name=tag, attributes=attributes, children=[], value=None)


class EyeBillboardGuards(unittest.TestCase):
    def test_only_known_two_eye_overlay_can_be_removed(self):
        actor = node('actor', name='synthetic')
        eye = node('component', name='BillboardSpriteRenderComponent')
        mapping = node('param', name='m_locatorToBillboardMap')
        mapping['children'] = [node('string', key=key, value='FX/Billboards/eyeGlow_billboards')
                               for key in ('loc_LeftEye', 'loc_RightEye')]
        eye['children'] = [mapping, node('param', name='m_visibleIn', value='ThirdPersonOnly')]
        other = node('component', name='ParticleEmitterComponent')
        actor['children'] = [eye, other]
        for bad in ('map', 'visibility', 'extra', 'duplicate', 'missing'):
            changed = copy.deepcopy(actor)
            item = changed['children'][0]
            if bad == 'map': item['children'][0]['children'][0]['attributes']['value'] = 'OtherEffect'
            if bad == 'visibility': item['children'][1]['attributes']['value'] = 'AllViews'
            if bad == 'extra': item['children'].append(node('param', name='other'))
            if bad == 'duplicate': changed['children'].append(copy.deepcopy(item))
            if bad == 'missing': changed['children'].remove(item)
            before = copy.deepcopy(changed)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                art.remove_coop_eye_billboards(changed)
            self.assertEqual(changed, before)
        art.remove_coop_eye_billboards(actor)
        self.assertEqual(actor['children'], [other])




if __name__ == '__main__':
    unittest.main()
