from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_ONE = {
    3: ("NumPy and pandas: from arrays to DataFrames", 50, 1, 54),
    4: ("SQL, exploratory analysis, and applied statistics", 50, 0, 23),
    5: ("Visualization and machine-learning foundations", 40, 2, 15),
    6: ("Preprocessing, feature engineering, and regression", 55, 2, 14),
    7: ("Classification, model selection, and hyperparameter optimization", 55, 0, 34),
    8: ("Clustering and dimensionality reduction", 40, 0, 24),
    9: ("Ensembles, recommenders, and classical text analytics", 45, 0, 13),
    10: ("Module 1 capstone build, feedback, and revision", 75, 0, 16),
    11: ("Module 1 capstone showcase and bridge to deep learning", 40, 0, 8),
}
INCLUSIVE_REQUIRED = {
    10: ("CapstoneProject.ipynb", "housing_data.csv"),
    11: ("heart-disease.README", "reviews.csv"),
    14: ("autograd.ipynb", "creating_tensors.ipynb"),
    15: ("Full Lecture Speech_ Building a Shallow Feedforward Network.docx", "Simple_MLP_Assignment.ipynb"),
    22: ("module_2_capstone_handout.html", "DeskTech_Vision_Capstone_Student.ipynb"),
    28: ("embedding_methods.ipynb",),
}


class ModuleOneStudentGuidePublicContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hub = (ROOT / "student-guides.html").read_text(encoding="utf-8")
        cls.pages = {
            day: (ROOT / f"student-day-{day:02d}.html").read_text(encoding="utf-8")
            for day in MODULE_ONE
        }

    def test_hub_has_eleven_full_guides_and_twenty_two_resource_outlines(self) -> None:
        self.assertEqual(11, self.hub.count("Full guide"))
        self.assertEqual(22, self.hub.count("Resource outline"))
        self.assertNotIn("Ready", self.hub)
        self.assertNotIn("Coming soon", self.hub)
        self.assertEqual(33, self.hub.count('href="student-day-'))

    def test_module_one_full_guides_have_ten_student_phases_and_schedule_metadata(self) -> None:
        for day, (title, homework_minutes, _, _) in MODULE_ONE.items():
            with self.subTest(day=day):
                page = self.pages[day]
                self.assertIn(f"Day {day} · {title}", page)
                self.assertIn("Break: 7:55–8:25 p.m.", page)
                self.assertIn(f"After class · {homework_minutes} minutes", page)
                self.assertIn('name="source-student-view-sha256"', page)
                self.assertEqual(10, page.count('class="phase-card'))

    def test_required_access_warnings_and_public_safe_optional_counts_are_truthful(self) -> None:
        for day, (_, _, instructor_provided, optional_safe) in MODULE_ONE.items():
            with self.subTest(day=day):
                page = self.pages[day]
                self.assertEqual(instructor_provided, page.count("Required · Instructor-mediated access"))
                self.assertEqual(optional_safe, page.count('data-resource-kind="optional"'))

    def test_grouped_resource_order_and_default_expansion_are_visible(self) -> None:
        page = self.pages[7]
        labels = (
            "Required · Core instruction",
            "Required · Guided practice and labs",
            "Required · Retrieval and homework",
            "Required · Assigned-day resources",
            "Optional practice and reference",
        )
        positions = [page.find(label) for label in labels]
        self.assertTrue(all(position >= 0 for position in positions), positions)
        self.assertEqual(positions, sorted(positions))
        for label in labels[:3]:
            self.assertRegex(page, rf'<details class="resource-group" open>.*?{re.escape(label)}')
        for label in labels[3:]:
            self.assertRegex(page, rf'<details class="resource-group">.*?{re.escape(label)}')

    def test_capstone_resources_are_linked_not_replaced_with_fallback(self) -> None:
        for day, names in {
            10: ("CapstoneProject.ipynb", "housing_data.csv"),
            11: ("heart-disease.README", "reviews.csv"),
        }.items():
            with self.subTest(day=day):
                page = self.pages[day]
                self.assertNotIn("No public-surface resource is currently available.", page)
                for name in names:
                    self.assertRegex(page, rf'<a[^>]+href="https://[^\"]+"[^>]*>[^<]*{re.escape(name)}')

    def test_required_resources_are_visible_even_when_their_format_is_not_promoted(self) -> None:
        for day, names in INCLUSIVE_REQUIRED.items():
            with self.subTest(day=day):
                page = (ROOT / f"student-day-{day:02d}.html").read_text(encoding="utf-8")
                for name in names:
                    self.assertRegex(page, rf'<a[^>]+href="https://[^\"]+"[^>]*>[^<]*{re.escape(name)}')
                self.assertIn("Required · Public link", page)

    def test_day_twenty_eight_duplicate_required_resource_has_one_safe_canonical_card(self) -> None:
        page = (ROOT / "student-day-28.html").read_text(encoding="utf-8")
        self.assertEqual(1, page.count("embedding_methods.ipynb"))
        self.assertIn("Required · Public link", page)
        self.assertNotIn("Required · Instructor-mediated access", page)

    def test_public_guides_expose_no_private_data_or_identifiers(self) -> None:
        combined = self.hub + "\n" + "\n".join(self.pages.values())
        self.assertNotRegex(combined, r"[A-Za-z]:\\\\|file:|\b[0-9a-f]{12}-\d{4}\b")
        self.assertNotIn("Instructor answer keys", combined)
        self.assertNotIn("instructor wording", combined.casefold())


if __name__ == "__main__":
    unittest.main()
