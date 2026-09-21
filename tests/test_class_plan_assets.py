"""Real assets are forbidden; escaped resource examples are ordinary text."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("site_verifier", ROOT / "scripts/verify_public_site.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

class AssetChecks(unittest.TestCase):
    def test_real_assets_fail(self):
        for html in ('<script>bad()</script>', '<img SRC="x">', '<link rel="alternate stylesheet" href="x">'):
            with self.subTest(html=html):
                self.assertTrue(verifier.class_plan_has_assets(html))

    def test_escaped_resource_examples_and_links_are_not_assets(self):
        self.assertFalse(verifier.class_plan_has_assets('<p>&lt;script src=&quot;example.js&quot;&gt;</p>'))
        self.assertFalse(verifier.class_plan_has_assets('<a href="https://example.org">Resource</a>'))
