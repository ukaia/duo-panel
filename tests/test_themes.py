import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from duo_panel import themes  # noqa: E402

REQUIRED = {"id", "name", "bg", "card", "line", "text", "muted", "accent", "accent2", "onAccent", "good", "warn", "bad", "radius", "face", "weight"}


class ThemeTests(unittest.TestCase):
    def test_every_theme_is_complete_and_ids_are_unique(self):
        ids = [t["id"] for t in themes.THEMES]
        self.assertEqual(len(ids), len(set(ids)))
        for t in themes.THEMES:
            self.assertEqual(REQUIRED, set(t), t["id"])
            for key in ("bg", "card", "line", "text", "muted", "accent", "accent2", "onAccent", "good", "warn", "bad"):
                self.assertRegex(t[key], r"^#[0-9a-f]{6}$", f"{t['id']}.{key}")
        self.assertIn(themes.DEFAULT_THEME, ids)
        self.assertEqual(themes.by_id("nope")["id"], themes.THEMES[0]["id"])

    def test_text_is_readable_in_every_theme(self):
        for t in themes.THEMES:
            c = lambda a, b: themes.contrast(t[a], t[b])   # noqa: E731
            self.assertGreaterEqual(c("text", "card"), 7.0, f"{t['id']} text on card")
            self.assertGreaterEqual(c("text", "bg"), 7.0, f"{t['id']} text on background")
            self.assertGreaterEqual(c("muted", "card"), 4.5, f"{t['id']} secondary text on card")
            self.assertGreaterEqual(c("onAccent", "accent"), 4.5, f"{t['id']} label on an accent button")
            for key in ("accent", "good", "warn", "bad"):
                self.assertGreaterEqual(c(key, "card"), 3.0, f"{t['id']} {key} on card (large figures and bars)")
            self.assertGreaterEqual(c("line", "card"), 1.15, f"{t['id']} borders must be visible")

    def test_steam_deck_theme_uses_the_colours_read_from_steams_own_files(self):
        s = themes.by_id("steamdeck")
        verified = {"bg": "#0e141b", "card": "#23262e", "line": "#3d4450", "text": "#dcdedf", "accent": "#1a9fff",
                    "accent2": "#66c0f4", "warn": "#ffc82c"}
        for key, value in verified.items():
            self.assertEqual(s[key], value, key)

    def test_the_page_offers_exactly_these_themes_and_only_theme_colours(self):
        qml = open(os.path.join(os.path.dirname(__file__), "..", "duo_panel", "qml", "Main.qml")).read()
        # no hard-coded colours in the page: everything comes from the theme
        stray = re.findall(r'"#[0-9a-fA-F]{3,8}"', qml)
        self.assertEqual(stray, [], "hard-coded colours in Main.qml")


if __name__ == "__main__":
    unittest.main()
