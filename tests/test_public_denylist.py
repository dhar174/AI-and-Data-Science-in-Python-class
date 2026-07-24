import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_public_denylist import apply_denylist
from export_public_catalog import build_public_catalog, filter_public_catalog, write_catalog_payload
from test_public_catalog import source_catalog
from verify_public_catalog import load_js_payload, verify_catalog


class PublicDenylistTests(unittest.TestCase):
    def public_payload(self):
        return build_public_catalog(source_catalog(), "A" * 64, generated_utc="2026-07-24T00:00:00Z")

    def test_filter_removes_record_and_recomputes_counts(self):
        payload = self.public_payload()
        filtered = filter_public_catalog(payload, {"file-1"})
        self.assertNotIn("file-1", {record["id"] for record in filtered["records"]})
        self.assertEqual(len(payload["records"]) - 1, filtered["summary"]["total_resources"])
        self.assertEqual([], verify_catalog(filtered, copy.deepcopy(filtered), {"file-1"}))

    def test_public_only_command_rewrites_matching_json_and_js(self):
        payload = self.public_payload()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = root / "course-catalog.json"
            denylist = root / "public-denylist.json"
            output_json = root / "out.json"
            output_js = root / "out.js"
            catalog.write_text(json.dumps(payload), encoding="utf-8")
            denylist.write_text(json.dumps({"version": 1, "record_ids": ["file-1"]}), encoding="utf-8")
            result, _ = apply_denylist(catalog, denylist, output_json, output_js)
            written = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(result, written)
            self.assertEqual(result, load_js_payload(output_js))
            self.assertNotIn("file-1", {record["id"] for record in result["records"]})

    def test_verifier_rejects_denylisted_record(self):
        payload = self.public_payload()
        errors = verify_catalog(payload, copy.deepcopy(payload), {"file-1"})
        self.assertTrue(any("denylisted record" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
