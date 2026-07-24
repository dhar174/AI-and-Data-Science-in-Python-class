import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


# Public catalog exporter contract tests.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_public_catalog import (
    build_public_catalog,
    export_catalog,
    normalize_google_url,
)
from verify_public_catalog import load_js_payload, verify_catalog


FIXED_GENERATED_UTC = "2026-07-23T12:00:00Z"


def eligible_file(record_id="file-1", catalog_path="Module A/Topic A/lesson.md"):
    return {
        "id": record_id,
        "name": "lesson.md",
        "display_name": "Lesson",
        "resource_kind": "file",
        "catalog_path": catalog_path,
        "relative_path": catalog_path,
        "absolute_path": r"C:\Users\person\private\lesson.md",
        "file_uri": "file:///C:/Users/person/private/lesson.md",
        "folder_uri": "file:///C:/Users/person/private",
        "extension": ".md",
        "size_bytes": 42,
        "modified_utc": "2026-07-22T10:00:00Z",
        "sha256": "A" * 64,
        "module": "Module A",
        "topic": "Topic A",
        "item_type": "Instruction",
        "audience": "Shared",
        "audience_normalized": "Shared",
        "bundle_id": "",
        "physical_area": r"C:\private",
        "classification_basis": "Approved curriculum placement",
        "confidence": "high",
        "dependency_status": "none detected",
        "dependency_sensitive": False,
        "duplicate_group": "",
        "action": "retain_current_organized",
        "status": "Organized",
        "is_review": False,
        "review_note": "private reviewer comment",
        "preview_text": "A safe preview.",
        "preview_truncated": False,
        "cloud": {
            "provider": "google_drive",
            "status": "verified",
            "file_id": "private-id",
            "source_url": "https://drive.google.com/file/d/ABCDEFGHIJ_123/view?usp=sharing#section",
            "mime_type": "text/markdown",
            "name": "lesson.md",
            "source": "drive_folder:private-folder",
            "note": "Uploaded from a private path",
            "app": "docs",
            "launch_url": "https://docs.google.com/document/d/ABCDEFGHIJ_123/copy?usp=sharing#top",
            "guide_url": "https://docs.google.com/document/u/0/",
            "copy_mode": "forced_copy",
            "available": True,
            "reason": "This file type keeps its local preview and file actions.",
        },
        "search_text": "private reviewer comment C:\\Users\\person\\private",
    }


def web_app(record_id="web-1", catalog_path="Module A/Activities/app"):
    return {
        "id": record_id,
        "name": "Practice App",
        "resource_kind": "web_app",
        "catalog_path": catalog_path,
        "module": "Module A",
        "topic": "Activities",
        "item_type": "Assessment",
        "audience": "Student",
        "audience_normalized": "Student",
        "status": "Available",
        "is_review": False,
        "web_app": {
            "service_name": "practice-app",
            "url": "https://apps.example.test/play?mode=student#start",
            "description": "Practice safely.",
            "link_status": "available",
            "last_checked_utc": "2026-07-22T11:00:00Z",
        },
        "search_text": "Practice App",
    }


def source_catalog():
    excluded_instructor = eligible_file("file-instructor", "Module A/Topic A/instructor.md")
    excluded_instructor["audience_normalized"] = "Instructor"
    excluded_status = eligible_file("file-review", "Module A/Topic A/review.md")
    excluded_status["status"] = "Archive review"
    excluded_cloud = eligible_file("file-unverified", "Module A/Topic A/unverified.md")
    excluded_cloud["cloud"]["status"] = "review"
    excluded_http = eligible_file("file-http", "Module A/Topic A/http.md")
    excluded_http["cloud"]["source_url"] = "http://drive.google.com/file/d/http/view"
    excluded_web = web_app("web-http", "Module A/Activities/http-app")
    excluded_web["web_app"]["url"] = "http://apps.example.test/play"
    return {
        "summary": {
            "catalog_version": 4,
            "library_root_uri": "file:///C:/private",
            "total_files": 9999,
        },
        "directories": [
            {
                "id": "unsafe-source-directory",
                "path": "",
                "folder_uri": "file:///C:/private",
                "descendant_resource_count": 9999,
            }
        ],
        "records": [
            eligible_file(),
            web_app(),
            excluded_instructor,
            excluded_status,
            excluded_cloud,
            excluded_http,
            excluded_web,
        ],
    }


class PublicCatalogExportTests(unittest.TestCase):
    def build(self):
        raw = json.dumps(source_catalog(), separators=(",", ":")).encode("utf-8")
        return build_public_catalog(
            source_catalog(),
            hashlib.sha256(raw).hexdigest().upper(),
            generated_utc=FIXED_GENERATED_UTC,
        )

    def test_filters_files_and_keeps_approved_https_web_apps(self):
        payload = self.build()

        self.assertEqual(["file-1", "web-1"], [record["id"] for record in payload["records"]])
        self.assertEqual("https://apps.example.test/play?mode=student#start", payload["records"][1]["web_app"]["url"])
        self.assertEqual(1, payload["summary"]["total_files"])
        self.assertEqual(1, payload["summary"]["total_web_apps"])
        self.assertEqual(2, payload["summary"]["total_resources"])

    def test_filters_unsafe_catalog_paths_for_files_and_web_apps(self):
        source = {"summary": {"catalog_version": 4}, "records": [eligible_file(), web_app()]}
        unsafe_paths = [
            "../traversal/lesson.md",
            "/absolute/lesson.md",
            r"Module A\Topic A\lesson.md",
            "file:/private/lesson.md",
            "https://example.test/lesson.md",
        ]
        for index, path in enumerate(unsafe_paths):
            source["records"].append(eligible_file(f"bad-file-{index}", path))
            source["records"].append(web_app(f"bad-web-{index}", path))

        payload = build_public_catalog(
            source, "D" * 64, generated_utc=FIXED_GENERATED_UTC,
        )

        self.assertEqual({"file-1", "web-1"}, {record["id"] for record in payload["records"]})

    def test_filters_web_apps_that_are_not_approved(self):
        source = {"summary": {"catalog_version": 4}, "records": [web_app()]}
        mutations = [
            ("bad-status", lambda item: item.update({"status": "Unavailable"})),
            ("bad-audience", lambda item: item.update({"audience_normalized": "Instructor"})),
            ("bad-review", lambda item: item.update({"is_review": True})),
            (
                "bad-link",
                lambda item: item["web_app"].update({"link_status": "unavailable"}),
            ),
        ]
        for record_id, mutate in mutations:
            candidate = web_app(record_id, f"Module A/Activities/{record_id}")
            mutate(candidate)
            source["records"].append(candidate)

        payload = build_public_catalog(
            source, "E" * 64, generated_utc=FIXED_GENERATED_UTC,
        )

        self.assertEqual(["web-1"], [record["id"] for record in payload["records"]])

    def test_sanitizes_by_allowlist_and_rebuilds_safe_search_text(self):
        payload = self.build()
        record = payload["records"][0]
        serialized = json.dumps(payload)

        self.assertEqual(
            {
                "action", "audience", "audience_normalized", "bundle_id",
                "catalog_path", "classification_basis", "cloud", "confidence",
                "dependency_sensitive", "dependency_status", "display_name",
                "duplicate_group", "extension", "id", "is_review", "item_type",
                "modified_utc", "module", "name", "preview_text",
                "preview_truncated", "resource_kind", "search_text", "sha256",
                "size_bytes", "status", "topic",
            },
            set(record),
        )
        self.assertEqual(
            {
                "app", "available", "copy_mode", "launch_url", "mime_type",
                "provider", "reason", "source_url", "status",
            },
            set(record["cloud"]),
        )
        for forbidden in (
            "absolute_path", "relative_path", "file_uri", "folder_uri",
            "library_root_uri", "review_note", "drive_folder:",
            "private reviewer comment", r"C:\Users", "file://",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual("A safe preview.", record["preview_text"])
        self.assertEqual("A" * 64, record["sha256"])
        self.assertIn("lesson.md", record["search_text"])

    def test_sanitizes_forbidden_content_across_retained_string_fields(self):
        source = source_catalog()
        file_record = source["records"][0]
        file_record["name"] = r"Lesson from C:\Users\Name\course"
        file_record["display_name"] = "Open embedded file:/C:/private/lesson.md safely"
        file_record["classification_basis"] = r"Reviewed on \\server\share\private"
        file_record["cloud"]["mime_type"] = "drive_folder:private-folder"
        source["records"][1]["web_app"]["description"] = (
            r"Keep context; local_path:\\server\share\private"
        )
        file_record["preview_text"] = (
            "Never publish sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )

        payload = build_public_catalog(
            source, "F" * 64, generated_utc=FIXED_GENERATED_UTC,
        )
        serialized = json.dumps(payload)

        self.assertIn("Lesson from [local path removed]", serialized)
        self.assertIn("Open embedded [file URL removed]", serialized)
        self.assertIn("Reviewed on [local path removed]", serialized)
        self.assertIn("[source reference removed]", serialized)
        for forbidden in (
            r"C:\Users",
            r"\\server\share",
            "file:/",
            "drive_folder:",
            "local_path:",
            "sk-proj-",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertIn("[secret removed]", serialized)
        self.assertEqual([], verify_catalog(payload, copy.deepcopy(payload)))

    def test_normalizes_only_google_source_and_launch_urls(self):
        record = self.build()["records"][0]

        self.assertEqual(
            "https://drive.google.com/file/d/ABCDEFGHIJ_123/view",
            record["cloud"]["source_url"],
        )
        self.assertEqual(
            "https://docs.google.com/document/d/ABCDEFGHIJ_123/copy",
            record["cloud"]["launch_url"],
        )

        bad = source_catalog()
        bad["records"][0]["cloud"]["source_url"] = "https://evil.example.test/file/d/abc"
        payload = build_public_catalog(bad, "B" * 64, generated_utc=FIXED_GENERATED_UTC)
        self.assertNotIn("file-1", [item["id"] for item in payload["records"]])

    def test_normalizes_supported_google_resource_urls_to_canonical_paths(self):
        resource_id = "ABCDEFGHIJ_123"
        cases = {
            f"https://drive.google.com/file/d/{resource_id}/view?usp=sharing#top":
                f"https://drive.google.com/file/d/{resource_id}/view",
            f"https://docs.google.com/document/d/{resource_id}/edit?usp=sharing":
                f"https://docs.google.com/document/d/{resource_id}/edit",
            f"https://docs.google.com/presentation/d/{resource_id}/edit#slide=id.p":
                f"https://docs.google.com/presentation/d/{resource_id}/edit",
            f"https://docs.google.com/spreadsheets/d/{resource_id}/edit?gid=0":
                f"https://docs.google.com/spreadsheets/d/{resource_id}/edit",
            f"https://colab.research.google.com/drive/{resource_id}?usp=sharing":
                f"https://colab.research.google.com/drive/{resource_id}",
            f"https://sheets.google.com/d/{resource_id}/edit":
                f"https://sheets.google.com/d/{resource_id}/edit",
            f"https://slides.google.com/d/{resource_id}/edit":
                f"https://slides.google.com/d/{resource_id}/edit",
        }

        for source_url, expected in cases.items():
            with self.subTest(source_url=source_url):
                self.assertEqual(expected, normalize_google_url(source_url))

    def test_rejects_nonresource_google_urls(self):
        resource_id = "ABCDEFGHIJ_123"
        invalid_urls = [
            "https://drive.google.com/",
            "https://docs.google.com/not-a-resource",
            "https://drive.google.com/file/d/short",
            "https://docs.google.com/document/d/tiny",
            f"https://drive.google.com/file/d/{resource_id}/../secret",
            f"https://drive.google.com/file/d/{resource_id}%2Fsecret",
            f"https://drive.google.com/file/d/{resource_id}/%2e%2e/secret",
            f"https://drive.google.com/document/d/{resource_id}",
            f"https://docs.google.com/file/d/{resource_id}",
            f"https://colab.research.google.com/document/d/{resource_id}",
            f"https://sheets.google.com/spreadsheets/d/{resource_id}",
        ]

        for source_url in invalid_urls:
            with self.subTest(source_url=source_url):
                self.assertIsNone(normalize_google_url(source_url))
                source = source_catalog()
                source["records"][0]["cloud"]["source_url"] = source_url
                payload = build_public_catalog(
                    source, "1" * 64, generated_utc=FIXED_GENERATED_UTC,
                )
                self.assertNotIn(
                    "file-1",
                    [record["id"] for record in payload["records"]],
                )

    def test_preserves_copy_launch_and_strips_owner_account_segments(self):
        source = source_catalog()
        source["records"][0]["cloud"].update(
            {
                "source_url":
                    "https://drive.google.com/file/u/42/d/ABCDEFGHIJ_123/view"
                    "?usp=sharing",
                "launch_url":
                    "https://docs.google.com/document/u/7/d/ABCDEFGHIJ_123/copy"
                    "?usp=sharing",
            }
        )

        payload = build_public_catalog(
            source, "2" * 64, generated_utc=FIXED_GENERATED_UTC,
        )
        matching = [
            record for record in payload["records"] if record["id"] == "file-1"
        ]
        self.assertEqual(1, len(matching))
        cloud = matching[0]["cloud"]

        self.assertEqual(
            "https://drive.google.com/file/d/ABCDEFGHIJ_123/view",
            cloud["source_url"],
        )
        self.assertEqual(
            "https://docs.google.com/document/d/ABCDEFGHIJ_123/copy",
            cloud["launch_url"],
        )
        self.assertTrue(cloud["available"])

    def test_rejects_contextually_invalid_google_suffixes(self):
        source = source_catalog()
        source["records"][0]["cloud"]["source_url"] = (
            "https://docs.google.com/document/d/ABCDEFGHIJ_123/copy"
        )
        payload = build_public_catalog(
            source, "3" * 64, generated_utc=FIXED_GENERATED_UTC,
        )
        self.assertNotIn("file-1", [record["id"] for record in payload["records"]])

        source = source_catalog()
        source["records"][0]["cloud"]["launch_url"] = (
            "https://docs.google.com/document/d/ABCDEFGHIJ_123/delete"
        )
        payload = build_public_catalog(
            source, "4" * 64, generated_utc=FIXED_GENERATED_UTC,
        )
        cloud = next(
            record["cloud"] for record in payload["records"] if record["id"] == "file-1"
        )
        self.assertEqual("", cloud["launch_url"])
        self.assertFalse(cloud["available"])

    def test_redacts_local_paths_and_file_urls_from_preview_text(self):
        source = source_catalog()
        source["records"][0]["preview_text"] = (
            "Keep this context. Install at C:\\Users\\Name\\course, then open "
            "file:///C:/private/lesson.md. End."
        )

        payload = build_public_catalog(
            source, "C" * 64, generated_utc=FIXED_GENERATED_UTC,
        )

        preview = payload["records"][0]["preview_text"]
        self.assertIn("Keep this context.", preview)
        self.assertIn("[local path removed]", preview)
        self.assertIn("[file URL removed]", preview)
        self.assertNotIn(r"C:\Users", preview)
        self.assertNotIn("file://", preview)

    def test_recomputes_directories_and_summary_from_filtered_records(self):
        payload = self.build()
        directories = {directory["path"]: directory for directory in payload["directories"]}

        self.assertEqual({"", "Module A", "Module A/Activities", "Module A/Topic A"}, set(directories))
        self.assertEqual(2, directories[""]["descendant_resource_count"])
        self.assertEqual(1, directories["Module A/Topic A"]["direct_file_count"])
        self.assertEqual(1, directories["Module A/Activities"]["direct_web_app_count"])
        self.assertEqual(2, directories["Module A"]["child_folder_count"])
        self.assertEqual(3, payload["summary"]["directory_count"])
        self.assertEqual(2, payload["summary"]["max_directory_depth"])
        self.assertEqual({"Module A": 1}, payload["summary"]["module_counts"])
        self.assertEqual({"Module A": 2}, payload["summary"]["resource_module_counts"])
        self.assertEqual({"Assessment": 1, "Instruction": 1}, payload["summary"]["item_type_counts"])
        self.assertEqual("public", payload["summary"]["delivery_mode"])

    def test_export_writes_pretty_json_and_matching_compact_wrapper(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source_path = temp / "source.json"
            json_path = temp / "data" / "course-catalog.json"
            js_path = temp / "data" / "catalog-data.js"
            source_path.write_text(json.dumps(source_catalog()), encoding="utf-8")

            expected = export_catalog(
                source_path, json_path, js_path, generated_utc=FIXED_GENERATED_UTC,
            )

            self.assertEqual(expected, json.loads(json_path.read_text(encoding="utf-8")))
            self.assertEqual(expected, load_js_payload(js_path))
            expected_json = (
                json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            expected_js = (
                "window.COURSE_LIBRARY_DATA="
                + json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
                + ";\n"
            ).encode("utf-8")
            self.assertEqual(expected_json, json_path.read_bytes())
            self.assertEqual(expected_js, js_path.read_bytes())
            self.assertEqual([], verify_catalog(expected, load_js_payload(js_path)))


class PublicCatalogVerifierTests(unittest.TestCase):
    def setUp(self):
        raw = json.dumps(source_catalog(), separators=(",", ":")).encode("utf-8")
        self.payload = build_public_catalog(
            source_catalog(),
            hashlib.sha256(raw).hexdigest().upper(),
            generated_utc=FIXED_GENERATED_UTC,
        )

    def assert_rejected(self, mutate, expected_fragment):
        candidate = copy.deepcopy(self.payload)
        mutate(candidate)
        errors = verify_catalog(candidate, copy.deepcopy(candidate))
        self.assertTrue(
            any(expected_fragment in error for error in errors),
            f"Expected {expected_fragment!r} in errors: {errors}",
        )

    def test_accepts_valid_payload_and_matching_wrapper(self):
        self.assertEqual([], verify_catalog(self.payload, copy.deepcopy(self.payload)))

    def test_accepts_blank_optional_launch_url(self):
        self.payload["records"][0]["cloud"].update(
            {
                "launch_url": "",
                "available": False,
                "reason": "Verified Google Drive link available.",
            }
        )

        self.assertEqual([], verify_catalog(self.payload, copy.deepcopy(self.payload)))

    def test_rejects_forbidden_fields_and_strings(self):
        cases = [
            (lambda p: p["records"][0].update({"absolute_path": r"C:\private\lesson.md"}), "forbidden field"),
            (lambda p: p["records"][0].update({"preview_text": r"C:\private\lesson.md"}), "Windows path"),
            (lambda p: p["records"][0].update({"preview_text": "file:///private/lesson.md"}), "file URL"),
            (
                lambda p: p["records"][0].update(
                    {"preview_text": r"prefix \\server\share\secret suffix"}
                ),
                "Windows path",
            ),
            (
                lambda p: p["records"][0].update(
                    {"preview_text": "prefix file:/C:/private/lesson.md suffix"}
                ),
                "file URL",
            ),
            (
                lambda p: p["records"][0].update(
                    {
                        "preview_text":
                            "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                    }
                ),
                "secret value",
            ),
        ]
        for mutate, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assert_rejected(mutate, fragment)

    def test_rejects_unsafe_catalog_paths_with_shared_predicate(self):
        unsafe_paths = [
            "../traversal/lesson.md",
            "/absolute/lesson.md",
            r"Module A\Topic A\lesson.md",
            "file:/private/lesson.md",
            "https://example.test/lesson.md",
        ]
        for record_index in (0, 1):
            for unsafe_path in unsafe_paths:
                with self.subTest(record_index=record_index, path=unsafe_path):
                    self.assert_rejected(
                        lambda p, i=record_index, value=unsafe_path: p["records"][i].update(
                            {"catalog_path": value}
                        ),
                        "unsafe catalog_path",
                    )

    def test_rejects_web_apps_that_are_not_approved(self):
        mutations = [
            lambda item: item.update({"status": "Unavailable"}),
            lambda item: item.update({"audience_normalized": "Instructor"}),
            lambda item: item.update({"is_review": True}),
            lambda item: item["web_app"].update({"link_status": "unavailable"}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_rejected(
                    lambda p, change=mutate: change(p["records"][1]),
                    "nonapproved web_app",
                )

    def test_rejects_google_query_and_fragment_urls(self):
        cases = [
            (
                lambda p: p["records"][0]["cloud"].update(
                    {
                        "source_url":
                            "https://drive.google.com/file/d/ABCDEFGHIJ_123?usp=sharing"
                    }
                ),
                "query or fragment",
            ),
            (
                lambda p: p["records"][0]["cloud"].update(
                    {
                        "launch_url":
                            "https://docs.google.com/document/d/ABCDEFGHIJ_123#top"
                    }
                ),
                "query or fragment",
            ),
        ]
        for mutate, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assert_rejected(mutate, fragment)

    def test_rejects_invalid_or_noncanonical_google_resource_urls(self):
        resource_id = "ABCDEFGHIJ_123"
        cases = [
            (
                "source_url",
                "https://drive.google.com/",
                "invalid Google resource URL",
            ),
            (
                "source_url",
                "https://docs.google.com/not-a-resource",
                "invalid Google resource URL",
            ),
            (
                "source_url",
                "https://drive.google.com/file/d/short",
                "invalid Google resource URL",
            ),
            (
                "source_url",
                f"https://drive.google.com/file/d/{resource_id}%2Fsecret",
                "invalid Google resource URL",
            ),
            (
                "launch_url",
                f"https://docs.google.com/file/d/{resource_id}",
                "invalid Google resource URL",
            ),
            (
                "source_url",
                f"https://drive.google.com/file/d/{resource_id}/delete",
                "invalid Google resource URL",
            ),
            (
                "launch_url",
                f"https://docs.google.com/document/d/{resource_id}/delete",
                "invalid Google resource URL",
            ),
            (
                "source_url",
                f"https://drive.google.com/file/u/0/d/{resource_id}/view",
                "Google URL is not canonical",
            ),
        ]
        for field, value, fragment in cases:
            with self.subTest(field=field, value=value):
                self.assert_rejected(
                    lambda p, key=field, url=value: p["records"][0]["cloud"].update(
                        {key: url}
                    ),
                    fragment,
                )

    def test_rejects_noncurated_files_and_bad_urls(self):
        cases = [
            (lambda p: p["records"][0].update({"audience_normalized": "Instructor"}), "noncurated file"),
            (
                lambda p: p["records"][0]["cloud"].update({"source_url": "http://drive.google.com/file/d/abc"}),
                "non-HTTPS URL",
            ),
            (
                lambda p: p["records"][0]["cloud"].update({"source_url": "https://evil.example.test/file/d/abc"}),
                "unexpected Google host",
            ),
            (
                lambda p: p["records"][0]["cloud"].update({"source_url": ""}),
                "noncurated file",
            ),
            (
                lambda p: p["records"][1]["web_app"].update({"url": ""}),
                "non-HTTPS URL",
            ),
        ]
        for mutate, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assert_rejected(mutate, fragment)

    def test_rejects_duplicate_ids_and_count_inconsistencies(self):
        cases = [
            (lambda p: p["records"].append(copy.deepcopy(p["records"][0])), "duplicate record id"),
            (lambda p: p["summary"].update({"total_resources": 999}), "summary mismatch"),
            (lambda p: p["directories"][0].update({"descendant_resource_count": 999}), "directory mismatch"),
        ]
        for mutate, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assert_rejected(mutate, fragment)

    def test_rejects_json_and_js_payload_mismatch(self):
        js_payload = copy.deepcopy(self.payload)
        js_payload["summary"]["delivery_mode"] = "different"

        errors = verify_catalog(self.payload, js_payload)

        self.assertTrue(any("JSON and JS payloads differ" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
