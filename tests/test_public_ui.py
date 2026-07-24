import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_public_navigation_and_footer_exclude_private_surfaces(self):
        self.assertNotIn('data-mode="Instructor"', self.index)
        self.assertNotIn("Archive &amp; Review", self.index)
        self.assertNotIn("organization_manifest_current.csv", self.index)
        self.assertNotIn("web_app_activities.csv", self.index)
        self.assertNotIn("llms.txt", self.index)
        self.assertIn('href="data/course-catalog.json"', self.index)
        self.assertIn(
            'href="https://github.com/dhar174/AI-and-Data-Science-in-Python-class"',
            self.index,
        )

    def test_three_views_and_core_library_controls_remain(self):
        for marker in (
            'data-view="library"',
            'data-view="tree"',
            'data-view="visual"',
            'id="searchInput"',
            'id="filterPanel"',
            'id="pagination"',
        ):
            self.assertIn(marker, self.index)

    def test_project_site_assets_are_relative(self):
        self.assertIn('href="styles.css"', self.index)
        self.assertIn('src="data/catalog-data.js"', self.index)
        self.assertIn('src="app.js"', self.index)
        for attribute, value in re.findall(r'\b(href|src)="([^"]+)"', self.index):
            if value.startswith(("https://", "data:", "#")):
                continue
            self.assertFalse(
                value.startswith("/"),
                f"{attribute}={value!r} would escape the GitHub project-site subpath",
            )

    def test_local_file_folder_and_upload_actions_are_removed(self):
        for forbidden in (
            'id="openFile"',
            'id="openFolder"',
            'id="copyPath"',
            'id="cloudGuideDialog"',
            "Copy local path",
            "Upload to a Google app",
            "record.absolute_path",
            "recordAbsolutePath",
            "recordFolderHref",
            "directoryHref",
            "showCloudGuide",
            "Google link source",
            "Absolute path",
            "Review note",
        ):
            self.assertNotIn(forbidden, self.index + self.app)

    def test_drive_is_primary_and_google_copy_actions_explain_sign_in(self):
        self.assertRegex(
            self.index,
            r'id="driveAction"[^>]*>.*Open in Google Drive',
        )
        self.assertIn("cloud.source_url", self.app)
        self.assertIn("Viewing is anonymous", self.app)
        self.assertIn("Google sign-in is required", self.app)

    def test_files_open_drive_and_web_apps_keep_external_launch(self):
        self.assertIn(
            "return isWebApp(record) ? record.web_app.url : record.cloud.source_url;",
            self.app,
        )
        self.assertIn("Launch Web App", self.index)
        self.assertIn("record.web_app.url", self.app)

    def test_text_preview_is_embedded_and_binary_preview_never_loads_course_bytes(self):
        self.assertIn("record.preview_text", self.app)
        self.assertIn("Preview in Google Drive", self.app)
        self.assertNotRegex(self.app, r'<(?:img|source|iframe)[^>]+src="\$\{href\}')
        self.assertNotIn("Loading preview", self.app)

    def test_legacy_instructor_hash_normalizes_to_all(self):
        self.assertIn('if (state.mode === "Instructor") state.mode = "All";', self.app)
        self.assertIn('["All", "Student"].includes(state.mode)', self.app)

    def test_public_repository_support_files_exist(self):
        self.assertTrue((ROOT / ".nojekyll").is_file())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("manual", readme.lower())
        self.assertIn("anonymous", readme.lower())
        self.assertIn(
            "https://dhar174.github.io/AI-and-Data-Science-in-Python-class/",
            readme,
        )
        self.assertNotIn("is deployed", readme.lower())

    def test_public_site_verifier_passes(self):
        verifier = ROOT / "scripts" / "verify_public_site.py"
        self.assertTrue(verifier.is_file())
        result = subprocess.run(
            [sys.executable, str(verifier), "--root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
