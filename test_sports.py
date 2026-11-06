import unittest, tempfile, gzip, xml.etree.ElementTree as ET
from pathlib import Path
import sports_overlay as o
import dual_sports_epg as s
from datetime import datetime,timezone
class TestSports(unittest.TestCase):
 def test_categories(self):
  for category in ['MLB','MiLB','NBA','MLS','NHL','NFL','NCAA','FLO SPORTS TV']:
   self.assertIsNotNone(o.group_key('AM|USA|'+category))
 def test_number_mapping(self):
  self.assertEqual(o.key_for({'name':'US - NBA GAME 01 : A @ B NOV 6 – 7:00 PM ET','group':'NBA'}),('NBA',1))
  self.assertEqual(o.key_for({'name':'FLO 007 : Bixby High School Open 9:00 AM ET','group':'AM|USA|FLO SPORTS TV'},True),('FLO',7))
 def test_time_only(self):
  e=s.event('US - FLO 007 : Bixby High School Open 9:00 AM ET',datetime(2026,11,6,12,tzinfo=timezone.utc))
  self.assertIn('Bixby High School Open',e[0]);self.assertIsNone(e[1])
 def test_full_overlay(self):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d)/'base.xml.gz';p=Path(d)/'sports.xml.gz'
   r=ET.Element('tv');ET.SubElement(r,'channel',id='regular');ET.SubElement(r,'programme',channel='regular',start='20261106000000 +0000',stop='20261106030000 +0000')
   with gzip.open(b,'wb') as f:f.write(ET.tostring(r))
   s.build([{'name':'US - NBA GAME 01 : ATLANTA @ WASHINGTON NOV 6 – 7:00 PM ET','group':'NBA','id':'sports.nba.001','stream':'1'}],p,datetime(2026,11,6,18,tzinfo=timezone.utc),{})
   result=o.overlay(b,p)
   self.assertTrue(result.find("channel[@id='regular']") is not None)
   self.assertTrue(result.find("channel[@id='sports.nba.001']") is not None)
   self.assertTrue(result.find("programme[@channel='regular']") is not None)
   self.assertTrue(result.find("programme[@channel='sports.nba.001']") is not None)
if __name__=='__main__':unittest.main()

class TestArena(unittest.TestCase):
 def test_arena_mapping_distinct(self):
  self.assertEqual(o.key_for({'name':'US - NBA IN THE ARENA 01','group':'NBA IN THE ARENA'}),('NBA_ARENA',1))
  self.assertEqual(o.key_for({'name':'NBA IN THE ARENA 01','group':'AM|USA|NBA'},True),('NBA_ARENA',1))
 def test_duplicate_only_when_no_own_event(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'out.xml.gz'
   now=datetime(2026,11,6,18,tzinfo=timezone.utc)
   rows=[{'name':'US - NBA GAME 01 : HAWKS @ WIZARDS NOV 6 – 7:00 PM ET','group':'NBA','id':'nba1','stream':'1'},
         {'name':'US - NBA IN THE ARENA 01','group':'NBA IN THE ARENA','id':'arena1','stream':'2'},
         {'name':'US - NBA IN THE ARENA 02 : CELTICS @ HORNETS NOV 6 – 8:00 PM ET','group':'NBA IN THE ARENA','id':'arena2','stream':'3'},
         {'name':'US - NBA GAME 02 : KNICKS @ NETS NOV 6 – 7:00 PM ET','group':'NBA','id':'nba2','stream':'4'}]
   s.build(rows,p,now,{})
   with gzip.open(p,'rb') as f:r=ET.parse(f).getroot()
   def titles(cid):return [x.findtext('title') for x in r.findall('programme') if x.get('channel')==cid]
   self.assertIn('Hawks @ Wizards',titles('arena1'))
   self.assertIn('Celtics @ Hornets',titles('arena2'))
   self.assertNotIn('KNICKS @ NETS',titles('arena2'))
