from pathlib import Path
import unittest
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
class Day3Continuation(unittest.TestCase):
 def test_approved_content(self):
  s=(ROOT/'student-day-03.html').read_text(encoding='utf-8').replace('\u2013','-')
  for value in ['Python basics continuation','3. Conversions','Strings','7:30-8:00','5:45-6:15','All five videos','1qCc9MeZixTeOAgdla3dfF7S5Tdi85kJb','1BskAVTu1IU1CVfD1mN89w6xlRxbcA1Ni','python-quest-ue4r4kw7oq-uw.a.run.app/','source-approved-student-sha256']:
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

 def test_scoped_notebook_roles(self):
  s=(ROOT/'student-day-03.html').read_text(encoding='utf-8')
  for value in ['IN-CLASS WORK','8b, 8d and 8e','HOMEWORK','numbered problems #7','#8 (division)','#13 (slice end index)','#21 (missing f in f-strings)','#22 (string immutability)','infinite loop','one scenario only','calculate_mean','File &gt; Save a copy in Drive','Approximate time','No new due date','1sNxpUNjT-0TDpaPf1iPiHHrltqXkz4a_','14kEw2IesCKSz_nuEqtDXf0tg4kZ0kRXN','1MA6vl37HPD0fYG5Btb9CuwWLDTU9A_wI','1VwNFAc4BMVve7W6TK5p4liYySUemhKby','1mSGNur5CIizqmqXM70MujfpHBoT3rcKY','13taMXjbRJ4h69ltX8UZmZ3wo6vZMFmKe','1uOQe8NKPqvA2_hvrt39vAJnBwIkCiL3A','1g4lf-dHo1YkmHDNLBzB1GFkAbeSVtN8z']:
   self.assertIn(value,s)
  self.assertNotIn('\ufffd',s)
