import json
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
NEW = 'https://dhar174.github.io/AI-and-Data-Science-in-Python-class/games/pyquest/'
OLD = 'pyquest-ue4r4kw7oq-uw.a.run.app'
class PyQuestLinks(unittest.TestCase):
    def test_active_catalog_and_day2_links(self):
        for name in ('class-plan.html', 'student-day-02.html', 'data/course-catalog.json', 'data/catalog-data.js'):
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                self.assertIn(NEW, text)
                self.assertNotIn(OLD, text)
    def test_python_quest_unchanged(self):
        catalog=json.loads((ROOT/'data/course-catalog.json').read_text(encoding='utf-8'))
        records=[r for r in catalog['records'] if r.get('web_app',{}).get('service_name')=='python-quest']
        self.assertEqual(1,len(records))
        self.assertEqual('https://python-quest-ue4r4kw7oq-uw.a.run.app',records[0]['web_app']['url'])
