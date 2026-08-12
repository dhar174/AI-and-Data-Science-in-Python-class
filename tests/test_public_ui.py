import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClassPlanAnchorParser(HTMLParser):
    def __init__(self, target_href="class-plan.html"):
        super().__init__(convert_charrefs=True)
        self.target_href = target_href
        self.section_stack = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "section":
            classes = (values.get("class") or "").split()
            is_views = "nav-group" in classes and values.get("aria-labelledby") == "viewsLabel"
            self.section_stack.append(is_views or any(self.section_stack))
        if tag == "a" and values.get("href") == self.target_href:
            self.anchors.append((values, any(self.section_stack)))

    def handle_endtag(self, tag):
        if tag == "section" and self.section_stack:
            self.section_stack.pop()


class StudentGuideParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.day_entries = []
        self.current_day = None
        self.phases = []
        self.current_phase = None
        self.in_summary = False
        self.external_links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "li" and "day-entry" in classes:
            self.current_day = {"text": "", "statuses": set(), "hrefs": []}
        elif self.current_day is not None and tag == "span":
            self.current_day["statuses"].update(classes & {"ready", "soon"})
        if self.current_day is not None and tag == "a" and values.get("href"):
            self.current_day["hrefs"].append(values["href"])
        if tag == "details" and "phase-card" in classes:
            self.current_phase = {
                "id": values.get("id"),
                "classes": classes,
                "summary": "",
            }
        elif self.current_phase is not None and tag == "summary":
            self.in_summary = True
        if tag == "a" and (values.get("href") or "").startswith("https://"):
            self.external_links.append(values)

    def handle_data(self, data):
        if self.current_day is not None:
            self.current_day["text"] += " " + data
        if self.current_phase is not None and self.in_summary:
            self.current_phase["summary"] += " " + data

    def handle_endtag(self, tag):
        if tag == "li" and self.current_day is not None:
            self.day_entries.append(self.current_day)
            self.current_day = None
        elif tag == "summary":
            self.in_summary = False
        elif tag == "details" and self.current_phase is not None:
            self.phases.append(self.current_phase)
            self.current_phase = None


class PublicUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")
        class_plan = ROOT / "class-plan.html"
        cls.class_plan = class_plan.read_text(encoding="utf-8") if class_plan.is_file() else ""
        cls.student_guides = (ROOT / "student-guides.html").read_text(encoding="utf-8")
        cls.student_day_01 = (ROOT / "student-day-01.html").read_text(encoding="utf-8")

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

    def test_class_plan_navigation_is_a_single_relative_non_view_link(self):
        parser = ClassPlanAnchorParser()
        parser.feed(self.index)
        self.assertEqual(1, len(parser.anchors))
        attributes, inside_views = parser.anchors[0]
        self.assertTrue(inside_views)
        self.assertIn("nav-item", attributes.get("class", "").split())
        self.assertIn("text-decoration:none", attributes.get("style", "").replace(" ", ""))
        self.assertNotIn("data-view", attributes)

    def test_student_guides_navigation_is_a_single_relative_non_view_link(self):
        parser = ClassPlanAnchorParser("student-guides.html")
        parser.feed(self.index)
        self.assertEqual(1, len(parser.anchors))
        attributes, inside_views = parser.anchors[0]
        self.assertTrue(inside_views)
        self.assertIn("nav-item", attributes.get("class", "").split())
        self.assertIn("text-decoration:none", attributes.get("style", "").replace(" ", ""))
        self.assertNotIn("data-view", attributes)
        anchors = re.findall(
            r'<a\b([^>]*)href="student-guides\.html"([^>]*)>(.*?)</a>',
            self.index,
            re.DOTALL,
        )
        self.assertIn("Student Day Guides", anchors[0][2])

    def test_public_verifier_rejects_student_guides_navigation_attacks(self):
        anchor = re.search(
            r'<a\b[^>]*href="student-guides\.html"[^>]*>.*?</a>',
            self.index,
            re.DOTALL,
        )
        self.assertIsNotNone(anchor)
        malformed_anchor = anchor.group(0).replace(
            'href="student-guides.html"',
            'href="index.html" href="student-guides.html"',
            1,
        )
        mutations = (
            self.index.replace(anchor.group(0), f"<!-- {anchor.group(0)} -->", 1),
            self.index.replace("</body>", "<a href='student-guides.html'>Duplicate</a></body>", 1),
            self.index.replace(anchor.group(0), malformed_anchor, 1),
        )
        for number, mutated in enumerate(mutations):
            with self.subTest(mutation=number), tempfile.TemporaryDirectory() as temp_dir:
                copy = Path(temp_dir) / "site"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
                (copy / "index.html").write_text(mutated, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                output = result.stdout + result.stderr
                self.assertNotEqual(0, result.returncode, output)
                self.assertIn("student-guides.html", output)

    def test_student_guide_hub_has_exact_day_status_contract(self):
        parser = StudentGuideParser()
        parser.feed(self.student_guides)
        self.assertEqual(33, len(parser.day_entries))
        self.assertEqual(
            [f"Day {number}" for number in range(1, 34)],
            [
                " ".join(" ".join(entry["text"].split()).split(" ", 2)[:2])
                for entry in parser.day_entries
            ],
        )
        ready = [entry for entry in parser.day_entries if "ready" in entry["statuses"]]
        soon = [entry for entry in parser.day_entries if "soon" in entry["statuses"]]
        self.assertEqual(1, len(ready))
        self.assertEqual(32, len(soon))
        self.assertEqual(["student-day-01.html"], ready[0]["hrefs"])
        self.assertTrue(all(not entry["hrefs"] for entry in soon))

    def test_day_one_has_eight_phases_break_times_and_five_external_links(self):
        parser = StudentGuideParser()
        parser.feed(self.student_day_01)
        expected = (
            ("orientation", "5:30–6:10 p.m."),
            ("analytic-approaches", "6:10–6:35 p.m."),
            ("guided-practice", "6:35–7:25 p.m."),
            ("capstone-domains", "7:25–7:55 p.m."),
            ("break", "7:55–8:25 p.m."),
            ("case-study-lab", "8:25–9:20 p.m."),
            ("assessment", "9:20–9:50 p.m."),
            ("exit", "9:50–10:00 p.m."),
        )
        self.assertEqual(
            [phase_id for phase_id, _ in expected],
            [phase["id"] for phase in parser.phases],
        )
        for phase, (_, time_range) in zip(parser.phases, expected):
            self.assertIn(time_range, phase["summary"])
        break_phases = [
            phase for phase in parser.phases if "break-phase" in phase["classes"]
        ]
        self.assertEqual(1, len(break_phases))
        self.assertEqual("break", break_phases[0]["id"])
        unique_urls = {attributes["href"] for attributes in parser.external_links}
        self.assertEqual(5, len(unique_urls))
        for attributes in parser.external_links:
            self.assertEqual("_blank", attributes.get("target"))
            self.assertTrue(
                {"noopener", "noreferrer"}.issubset(
                    set(attributes.get("rel", "").split())
                )
            )

    def test_public_verifier_rejects_student_guide_mutations(self):
        mutations = (
            ("missing asset", "student-guides.css", None),
            (
                "hub status count",
                "student-guides.html",
                lambda text: text.replace('class="status soon">Coming soon', 'class="status ready">Ready', 1),
            ),
            (
                "phase time",
                "student-day-01.html",
                lambda text: text.replace("5:30–6:10 p.m.", "5:31–6:10 p.m.", 1),
            ),
            (
                "external link safety",
                "student-day-01.html",
                lambda text: text.replace('rel="noopener noreferrer"', 'rel="noreferrer"', 1),
            ),
            (
                "privacy leak",
                "student-guides.js",
                lambda text: text + "\n// C:\\private\\student-guide\n",
            ),
            (
                "project subpath",
                "student-guides.html",
                lambda text: text.replace('href="student-guides.css"', 'href="/student-guides.css"', 1),
            ),
            (
                "stylesheet subpath",
                "student-guides.css",
                lambda text: text + '\n.bad { background-image: url("/private.png"); }\n',
            ),
        )
        for name, relative, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                copy = Path(temp_dir) / "site"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
                path = copy / relative
                if mutate is None:
                    path.unlink()
                else:
                    path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)

    def test_class_plan_is_self_contained_and_has_all_sessions(self):
        self.assertTrue(self.class_plan, "class-plan.html is missing")
        self.assertEqual(33, self.class_plan.count('<details class="session-detail"'))
        self.assertIn('href="index.html"', self.class_plan)
        self.assertIn("Nine-week summary", self.class_plan)
        self.assertIn("Compact 33-session schedule", self.class_plan)
        self.assertIn("Course expectations", self.class_plan)
        self.assertNotIn("<script", self.class_plan.casefold())
        self.assertNotIn('rel="stylesheet"', self.class_plan.casefold())
        self.assertNotRegex(self.class_plan, r'\b(?:src|href)="/(?!/)')

    def test_class_plan_excludes_private_data_and_internal_ids(self):
        self.assertTrue(self.class_plan, "class-plan.html is missing")
        for forbidden in (
            "retrieval_questions",
            "worked_example",
            "modelling_steps",
            "<dt>Misconception</dt>",
            "hinge_question",
            "hinge_rule",
            "required_resource_ids",
            "featured_optional_ids",
            "scheduled_resource_count",
            "scheduled_optional_count",
            "scheduled_instructor_count",
            "absolute_path",
            "relative_path",
            "review_note",
            "Instructor-only",
        ):
            self.assertNotIn(forbidden, self.class_plan)
        self.assertIsNone(re.search(r"web-[0-9a-f]{12,}", self.class_plan, re.IGNORECASE))
        self.assertIsNone(re.search(r"\b[0-9a-f]{12}-\d{4}\b", self.class_plan, re.IGNORECASE))
        self.assertIsNone(
            re.search(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|file:/{1,3})", self.class_plan)
        )

    def test_public_verifier_scans_class_plan_for_local_path_leaks(self):
        self.assertTrue(self.class_plan, "class-plan.html is missing")
        with tempfile.TemporaryDirectory() as temp_dir:
            copy = Path(temp_dir) / "site"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
            page = copy / "class-plan.html"
            page.write_text(self.class_plan + "C:\\private\\course\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("class-plan.html", result.stdout + result.stderr)

    def test_public_verifier_rejects_a_second_class_plan_link(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copy = Path(temp_dir) / "site"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
            index = copy / "index.html"
            index.write_text(
                index.read_text(encoding="utf-8").replace(
                    "</body>", '<a href="class-plan.html">Duplicate</a></body>', 1
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("exactly one class-plan.html link", result.stdout + result.stderr)

    def test_public_verifier_rejects_commented_and_single_quoted_anchor_attacks(self):
        anchor = re.search(r'<a\b[^>]*href="class-plan\.html"[^>]*>.*?</a>', self.index, re.DOTALL)
        self.assertIsNotNone(anchor)
        mutations = (
            self.index.replace(anchor.group(0), f"<!-- {anchor.group(0)} -->", 1),
            self.index.replace("</body>", "<a href='class-plan.html'>Duplicate</a></body>", 1),
        )
        for number, mutated in enumerate(mutations):
            with self.subTest(mutation=number), tempfile.TemporaryDirectory() as temp_dir:
                copy = Path(temp_dir) / "site"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
                (copy / "index.html").write_text(mutated, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("class-plan.html link", result.stdout + result.stderr)

    def test_public_verifier_rejects_duplicate_href_attributes(self):
        anchor = re.search(r'<a\b[^>]*href="class-plan\.html"[^>]*>.*?</a>', self.index, re.DOTALL)
        self.assertIsNotNone(anchor)
        malformed_anchor = anchor.group(0).replace(
            'href="class-plan.html"',
            'href="index.html" href="class-plan.html"',
            1,
        )
        mutated = self.index.replace(anchor.group(0), malformed_anchor, 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            copy = Path(temp_dir) / "site"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
            (copy / "index.html").write_text(mutated, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(0, result.returncode, output)
            self.assertIn("duplicate attribute", output)
            self.assertIn("exactly one class-plan.html link", output)

    def test_public_verifier_rejects_mutated_source_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copy = Path(temp_dir) / "site"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
            page = copy / "class-plan.html"
            page.write_text(
                self.class_plan.replace(
                    'content="222cb2a9412afb29e1d4247568181108aa7e32104508cf9cc05b30b6b705a659"',
                    'content="0000000000000000000000000000000000000000000000000000000000000000"',
                    1,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("schedule-sha256 does not match", result.stdout + result.stderr)

    def test_public_verifier_rejects_mutated_class_plan_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copy = Path(temp_dir) / "site"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git"))
            page = copy / "class-plan.html"
            page.write_text(self.class_plan.replace("Student guide ·", "Student guide  ·", 1), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(copy / "scripts" / "verify_public_site.py"), "--root", str(copy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("class-plan.html SHA-256 does not match", result.stdout + result.stderr)

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
