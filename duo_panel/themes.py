"""Themes for the Duo panel. One definition, used by the QML page and checked by the tests (contrast, ids).

Steam Deck: the colours marked [steam] were read off the Steam client on the Duo itself
(~/.local/share/Steam/steamui/css/sp.css and sp.js): --gpColor-Blue #1a9fff, --gpColor-Yellow #ffc82c, background
#0e141b, panel #23262e, border/inactive #3d4450, text #dcdedf, light blue #66c0f4. The UI font there is "Motiva Sans",
which is not installed on the device, so the nearest installed face is used. Colours marked [derived] are
picked to sit with those (Steam's own green and red were not found in its files).
"""
from __future__ import annotations

THEMES = [
    {
        "id": "steamdeck", "name": "Steam Deck",
        "bg": "#0e141b",        # [steam]
        "card": "#23262e",      # [steam] panel
        "line": "#3d4450",      # [steam] border / inactive track
        "text": "#dcdedf",      # [steam]
        "muted": "#9ea3ab",     # [derived] text at about 65% over the panel
        "accent": "#1a9fff",    # [steam] --gpColor-Blue
        "accent2": "#66c0f4",   # [steam]
        "onAccent": "#0e141b",
        "good": "#5ec26a",      # [derived]
        "warn": "#ffc82c",      # [steam] --gpColor-Yellow
        "bad": "#ff6b5e",       # [derived]
        "radius": 8, "face": "Adwaita Sans", "weight": 600,
    },
    {
        "id": "midnight", "name": "Midnight",
        "bg": "#0d1117", "card": "#161b22", "line": "#2a3341", "text": "#e6edf5", "muted": "#8b98a9",
        "accent": "#4cc2ff", "accent2": "#a78bfa", "onAccent": "#06121c",
        "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171",
        "radius": 18, "face": "Adwaita Sans", "weight": 700,
    },
    {
        "id": "oled", "name": "OLED Black",
        "bg": "#000000", "card": "#0c0c0e", "line": "#26262c", "text": "#f4f4f5", "muted": "#9a9aa3",
        "accent": "#2ee6a6", "accent2": "#f472b6", "onAccent": "#00140c",
        "good": "#4ade80", "warn": "#fbbf24", "bad": "#fb7185",
        "radius": 14, "face": "Adwaita Sans", "weight": 700,
    },
    {
        "id": "daylight", "name": "Daylight",
        "bg": "#e9edf2", "card": "#ffffff", "line": "#cdd5df", "text": "#16202b", "muted": "#566475",
        "accent": "#0b63d6", "accent2": "#7c3aed", "onAccent": "#ffffff",
        "good": "#15803d", "warn": "#a16207", "bad": "#b91c1c",
        "radius": 16, "face": "Adwaita Sans", "weight": 700,
    },
    {
        "id": "amber", "name": "Amber Terminal",
        "bg": "#0a0700", "card": "#130e02", "line": "#4a3608", "text": "#ffb000", "muted": "#b07a00",
        "accent": "#ffd45e", "accent2": "#ff8a3d", "onAccent": "#1a1200",
        "good": "#9be564", "warn": "#ffd45e", "bad": "#ff6b4a",
        "radius": 4, "face": "Adwaita Mono", "weight": 700,
    },
]

DEFAULT_THEME = "steamdeck"
IDS = [t["id"] for t in THEMES]


def by_id(theme_id):
    for t in THEMES:
        if t["id"] == theme_id:
            return t
    return THEMES[0]


def _lum(hex_color):
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    """WCAG contrast ratio between two #rrggbb colours."""
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
