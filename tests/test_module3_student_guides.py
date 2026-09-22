"""Shared student-guide contracts for all eleven Module 3 lessons."""
from html import unescape
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class Module3StudentGuides(unittest.TestCase):
    def test_named_teaching_inputs_have_visible_resource_cards(self):
        for day in range(23, 34):
            with self.subTest(day=day):
                page = (ROOT / f'student-day-{day:02d}.html').read_text(encoding='utf-8')
                resources, schedule = page.split('aria-labelledby="scheduleHeading"', 1)
                use = ' '.join(re.findall(r'<dt>Use</dt><dd>(.*?)</dd>', schedule, re.S))
                names = set(re.findall(r'[A-Za-z0-9_-]+\.(?:ipynb|md|py|json)', unescape(use)))
                self.assertIn(f'm3_day_{day-22:02d}_teaching.ipynb', names)
                for name in names:
                    self.assertTrue(re.search(rf'(?:>|\s){re.escape(name)}<', resources), f'Day {day}: missing resource card for {name}')
                self.assertNotIn('harness_workshop.md', use)

    def test_all_full_guides_link_directly_to_focusable_schedule(self):
        for day in range(23, 34):
            page = (ROOT / f'student-day-{day:02d}.html').read_text(encoding='utf-8')
            with self.subTest(day=day):
                self.assertTrue(f'href="#scheduleHeading">Skip to Day {day} schedule' in page, f'Day {day}: wrong skip target')
                self.assertTrue('id="scheduleHeading" tabindex="-1"' in page, f'Day {day}: schedule is not focusable')
                self.assertTrue('7:55–8:25 p.m.' in page, f'Day {day}: missing break')

    def test_deleted_day11_lectures_are_not_student_dependencies(self):
        page = (ROOT / 'student-day-11.html').read_text(encoding='utf-8')
        for phrase in ('Use the showcase lecture', 'Use the bridge lecture', 'Use both lectures'):
            self.assertTrue(phrase not in page, f'Day 11: stale lecture dependency: {phrase}')
        self.assertTrue('problem → evidence → decision → limitation' in unescape(page), 'Day 11: missing self-contained defense frame')

    def test_final_submission_happens_in_class(self):
        page = (ROOT / 'student-day-33.html').read_text(encoding='utf-8')
        homework = page.split('After class', 1)[1]
        self.assertIn('final capstone submission is completed in class', homework)
        self.assertNotIn('Submit the final artifact', homework)
