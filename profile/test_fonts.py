"""fonts.py tests, moved unchanged from windows hosts/common/test_pack.py (the prepare_fonts cases)."""
import json
from pathlib import Path
import tempfile
import unittest

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

import fonts


class FontTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def font(self, name="Test Font", filename="input.ttf", family=None, typographic=None, folder="upstream"):
        builder = FontBuilder(1000, isTTF=True)
        builder.setupGlyphOrder([".notdef", "space"])
        builder.setupCharacterMap({32: "space"})
        builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in (".notdef", "space")})
        builder.setupHorizontalMetrics({name: (500, 0) for name in (".notdef", "space")})
        builder.setupHorizontalHeader(ascent=800, descent=-200)
        names = {"familyName": family or name, "styleName": "Regular", "fullName": name,
                 "uniqueFontIdentifier": name, "psName": name.replace(" ", "")}
        if typographic:
            names["typographicFamily"] = typographic
        builder.setupNameTable(names)
        builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
        builder.setupPost()
        source = self.root / folder
        source.mkdir(exist_ok=True)
        builder.save(source / filename)
        (source / "OFL.txt").write_text("Synthetic test license, not a redistributed font.")
        return {"role": "fixture", "family": name, "version": "1", "directory": str(source), "licenseSource": str(source)}

    def payload(self):
        policy = self.font()
        out = self.root / "fonts"
        fonts.prepare_fonts([policy], out)
        return out

    def test_font_bytes_names_and_license(self):
        out = self.payload()
        entry, = json.loads((out / "fonts.json").read_text())
        self.assertEqual(entry["fullName"], "Test Font")
        path = out / "share/fonts/truetype" / entry["file"]
        self.assertEqual(fonts.digest(path), entry["sha256"])
        self.assertEqual(entry["file"], entry["sha256"] + ".ttf")
        self.assertTrue(list((out / "share/licenses/fixture").iterdir()))

    def test_missing_license_fails(self):
        policy = self.font()
        (Path(policy["licenseSource"]) / "OFL.txt").unlink()
        with self.assertRaisesRegex(ValueError, "license"):
            fonts.prepare_fonts([policy], self.root / "fonts")

    def test_empty_selection_fails(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            fonts.prepare_fonts([], self.root / "fonts")

    def test_duplicate_full_name_fails(self):
        policy = self.font()
        self.font(filename="duplicate.ttf")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            fonts.prepare_fonts([policy], self.root / "fonts")

    def test_every_role_file_is_the_declared_family(self):
        # A weight whose name ID 1 is "<family> Light" belongs by its typographic family (name ID 16).
        policy = self.font()
        self.font(name="Test Font Light", filename="light.ttf", family="Test Font Light", typographic="Test Font")
        fonts.prepare_fonts([policy], self.root / "fonts")
        for case, (family, typographic) in {"name ID 1": ("Test Font Mono", None),
                                            "name ID 16 wins": ("Test Font", "Other Font")}.items():
            self.font(name="Odd", filename="odd.ttf", family=family, typographic=typographic)  # replaces the last
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "Font family"):
                fonts.prepare_fonts([policy], self.root / f"fonts-{case}")


if __name__ == "__main__":
    unittest.main()
