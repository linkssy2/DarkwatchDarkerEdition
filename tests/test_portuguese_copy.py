"""Every custom PC menu label has Portuguese copy with intact control tokens."""
from collections import Counter
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / "tools"))
import ps2_text
from prepare_ptbr_catalog import normalized


def rows(path, declaration):
    source = path.read_text(encoding="utf-8").split(declaration, 1)[1].split("\n};", 1)[0]
    literal = r'"(?:[^"\\]|\\.)*"'
    return [tuple(json.loads(value) for value in pair) for pair in
            re.findall(r'\{\s*(' + literal + r')\s*,\s*(' + literal + r')\s*\}', source)]


class PortugueseCopyTests(unittest.TestCase):
    def test_complete_custom_menu_copy(self):
        spanish = rows(ROOT / "xbexbe/src/common/language.cpp", "constexpr Copy copy[]{")
        portuguese = rows(ROOT / "xbexbe/src/common/language_portuguese.h", "copy_portuguese[]{")
        self.assertGreater(len(spanish), 250)
        self.assertEqual(Counter(key for key, _ in spanish), Counter(key for key, _ in portuguese))
        self.assertTrue(all(count == 1 for count in Counter(key for key, _ in portuguese).values()))
        for english, translated in portuguese:
            with self.subTest(english=english):
                self.assertTrue(translated.strip())
                self.assertNotIn("\0", translated)
                self.assertEqual(ps2_text.tokens(english), ps2_text.tokens(translated))
                # printf parameters must retain their exact types and order.
                pattern = r'(?<!\d)%(?:\d+\$)?[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hljztL]*[diuoxXfFeEgGaAcsp%]'
                self.assertEqual(re.findall(pattern, english), re.findall(pattern, translated))
                normalized(translated)


if __name__ == "__main__":
    unittest.main()
