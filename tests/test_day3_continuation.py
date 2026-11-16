from pathlib import Path
import unittest
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
class Day3Continuation(unittest.TestCase):
 def test_approved_content(self):
  s=(ROOT/'student-day-03.html').read_text(encoding='utf-8')
  for value in ['Python basics continuation','3. Conversions','Strings','7:30–8:00','5:45–6:15','All five videos','1qCc9MeZixTeOAgdla3dfF7S5Tdi85kJb','1BskAVTu1IU1CVfD1mN89w6xlRxbcA1Ni','python-quest-ue4r4kw7oq-uw.a.run.app/','source-approved-student-sha256']:
   self.assertIn(value,s)
  for value in ['NumPy and pandas','Instructor packet','Audit/readiness','not published','file://','Private student-schedule']:
   self.assertNotIn(value,s)
  self.assertEqual(10,s.count('https://drive.google.com/file/d/'))
  self.assertIn('not repeating the whole Data Arcade',s)
 def test_navigation(self):
  class Links(HTMLParser):
   def handle_starttag(self,tag,attrs):
    if tag=='a': self.links.append(dict(attrs).get('href',''))
  p=Links(); p.links=[]; p.feed((ROOT/'student-day-03.html').read_text(encoding='utf-8'))
  for href in p.links:
   if not href.startswith(('https://','#')): self.assertTrue((ROOT/href).is_file(),href)
