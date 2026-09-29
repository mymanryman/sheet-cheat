import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import omr  # noqa: E402

# A piano score (one part, two staves), two systems of two measures,
# laid out the way Audiveris exports it.
SCORE = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <defaults>
    <page-layout>
      <page-height>1400</page-height><page-width>1000</page-width>
      <page-margins type="both"><left-margin>50</left-margin><right-margin>50</right-margin>
        <top-margin>50</top-margin><bottom-margin>50</bottom-margin></page-margins>
    </page-layout>
    <system-layout><system-margins><left-margin>20</left-margin><right-margin>0</right-margin></system-margins>
      <system-distance>120</system-distance><top-system-distance>100</top-system-distance></system-layout>
    <staff-layout><staff-distance>60</staff-distance></staff-layout>
  </defaults>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1" width="300">
      <attributes><divisions>1</divisions><key><fifths>-1</fifths></key><staves>2</staves>
        <clef number="1"><sign>G</sign><line>2</line></clef>
        <clef number="2"><sign>F</sign><line>4</line></clef></attributes>
      <note default-x="40"><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note default-x="40"><chord/><pitch><step>E</step><octave>5</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note default-x="160"><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
      <backup><duration>4</duration></backup>
      <note default-x="40"><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><staff>2</staff></note>
    </measure>
    <measure number="2" width="300">
      <note default-x="40" default-y="-15"><pitch><step>F</step><alter>1</alter><octave>5</octave></pitch><duration>4</duration><staff>1</staff></note>
      <backup><duration>4</duration></backup>
      <note><rest/><duration>4</duration><staff>2</staff></note>
    </measure>
    <measure number="3" width="400">
      <print new-system="yes"/>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
    </measure>
  </part>
</score-partwise>
"""


class ExtractNotesTest(unittest.TestCase):
    def setUp(self):
        self.result = omr.extract_notes(ET.fromstring(SCORE))
        self.notes = self.result["notes"]

    def px(self, note):
        return round(note["x"] * 1000, 1), round(note["y"] * 1400, 1)

    def test_names_and_count(self):
        self.assertEqual([n["name"] for n in self.notes], ["C", "E", "Bb", "C", "F#", "G", "A"])
        self.assertAlmostEqual(self.result["space"], 10 / 1400)

    def test_treble_positions(self):
        # first staff top line at 50 + 100 = 150; C5 is 1.5 spaces below F5
        self.assertEqual(self.px(self.notes[0]), (110.0, 165.0))
        self.assertEqual(self.px(self.notes[1]), (110.0, 155.0))
        self.assertEqual(self.px(self.notes[2]), (230.0, 170.0))

    def test_bass_staff(self):
        # second staff top line at 150 + 40 + 60 = 250; C3 is 2.5 spaces below A3
        self.assertEqual(self.px(self.notes[3]), (110.0, 275.0))

    def test_default_y_and_second_measure(self):
        self.assertEqual(self.px(self.notes[4]), (410.0, 165.0))

    def test_second_system_without_default_x(self):
        # system 2 top = 290 + 120 = 410; notes spread over the measure by time
        g, a = self.notes[5], self.notes[6]
        self.assertEqual(self.px(g), (80.0, 440.0))  # G4 is 3 spaces below F5
        self.assertEqual(self.px(a), (270.0, 435.0))


class AudiverisMarginsTest(unittest.TestCase):
    def test_positions_are_relative_to_the_image_inside_the_margins(self):
        # Audiveris adds its page margins around the scanned image, so the
        # image covers 50..950 x 50..1350 of the 1000 x 1400 page.
        score = SCORE.replace("<defaults>", "<identification><encoding><software>Audiveris 5.11.0"
                              "</software></encoding></identification><defaults>")
        result = omr.extract_notes(ET.fromstring(score))
        first = result["notes"][0]
        self.assertAlmostEqual(first["x"], (110 - 50) / 900, places=4)
        self.assertAlmostEqual(first["y"], (165 - 50) / 1300, places=4)
        self.assertAlmostEqual(result["space"], 10 / 1300)


# A voice part that is hidden on the first system (piano intro) and whose
# layout is carried by the piano part, as Audiveris exports it.
HIDDEN_VOICE = """<score-partwise version="4.0">
  <defaults><page-layout><page-height>1400</page-height><page-width>1000</page-width>
    <page-margins><left-margin>0</left-margin><top-margin>0</top-margin></page-margins></page-layout></defaults>
  <part-list><score-part id="P1"/><score-part id="P2"/></part-list>
  <part id="P1">
    <measure number="1"><attributes><divisions>1</divisions>
      <clef><sign>G</sign><line>2</line></clef><staff-details print-object="no"/></attributes>
      <note><rest measure="yes"/><duration>3</duration></note></measure>
    <measure number="2" width="400"><print new-system="yes"><system-layout>
      <system-margins><left-margin>50</left-margin></system-margins><system-distance>100</system-distance>
      </system-layout></print><attributes><staff-details print-object="yes"/></attributes>
      <note default-x="20"><pitch><step>F</step><octave>5</octave></pitch><duration>3</duration></note></measure>
  </part>
  <part id="P2">
    <measure number="1" width="300"><print><system-layout>
      <system-margins><left-margin>100</left-margin></system-margins><top-system-distance>200</top-system-distance>
      </system-layout></print><attributes><divisions>1</divisions><clef><sign>G</sign><line>2</line></clef></attributes>
      <note default-x="20"><pitch><step>F</step><octave>5</octave></pitch><duration>3</duration></note></measure>
    <measure number="2" width="400"><print new-system="yes"><staff-layout number="1">
      <staff-distance>70</staff-distance></staff-layout></print>
      <note default-x="20"><pitch><step>F</step><octave>5</octave></pitch><duration>3</duration></note></measure>
  </part>
</score-partwise>"""


class HiddenStaffTest(unittest.TestCase):
    def test_hidden_part_takes_no_space_and_layout_comes_from_other_part(self):
        notes = omr.extract_notes(ET.fromstring(HIDDEN_VOICE))["notes"]
        by_part = {(n["part"], round(n["y"] * 1400)): round(n["x"] * 1000) for n in notes}
        # system 1: only the piano, at top-system-distance 200, left margin 100
        self.assertEqual(by_part[(1, 200)], 120)
        # system 2: voice at 240 + 100 = 340, piano below it at 340 + 40 + 70 = 450
        self.assertEqual(by_part[(0, 340)], 70)
        self.assertEqual(by_part[(1, 450)], 70)


if __name__ == "__main__":
    unittest.main()
