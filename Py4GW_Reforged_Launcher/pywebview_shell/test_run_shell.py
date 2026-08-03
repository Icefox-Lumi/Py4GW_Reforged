"""Unit tests for pywebview_shell/run_shell.py's pure geometry (RELAY 095).

No committed test file existed for run_shell.py before now -- same "no test
existed, wrote one" situation this repo has hit before (088/091's own
precedent). clamp_window_geometry() was deliberately pulled out as a pure
function (same "no live window needed" split snap.py's zone_rect/
classify_zone already established) specifically so it's testable in
isolation from webview/Win32.

Run: .venv\\Scripts\\python.exe -m unittest pywebview_shell.test_run_shell -v
"""
from __future__ import annotations

import unittest

from pywebview_shell.run_shell import MIN_SIZE, clamp_window_geometry


class TestClampWindowGeometry(unittest.TestCase):
    SCREEN = (0, 0, 2560, 1440)  # left, top, right, bottom

    def test_geometry_fully_on_screen_is_unchanged(self):
        result = clamp_window_geometry(100, 100, 601, 817, [self.SCREEN], MIN_SIZE)
        self.assertEqual(result, (100, 100, 601, 817))

    def test_width_and_height_grown_to_min_size(self):
        x, y, w, h = clamp_window_geometry(100, 100, 50, 50, [self.SCREEN], MIN_SIZE)
        self.assertEqual((w, h), MIN_SIZE)

    def test_partially_off_right_edge_is_nudged_fully_onscreen(self):
        # Window's right edge would land past the screen's right edge.
        x, y, w, h = clamp_window_geometry(2500, 100, 601, 817, [self.SCREEN], MIN_SIZE)
        self.assertEqual((w, h), (601, 817))  # size untouched, it still fits
        self.assertEqual(x + w, self.SCREEN[2])  # nudged so the far edge lands exactly on-screen
        self.assertGreaterEqual(x, self.SCREEN[0])

    def test_partially_off_bottom_edge_is_nudged_fully_onscreen(self):
        x, y, w, h = clamp_window_geometry(100, 1400, 601, 817, [self.SCREEN], MIN_SIZE)
        self.assertEqual(y + h, self.SCREEN[3])
        self.assertGreaterEqual(y, self.SCREEN[1])

    def test_negative_position_is_nudged_onscreen(self):
        x, y, w, h = clamp_window_geometry(-500, -500, 601, 817, [self.SCREEN], MIN_SIZE)
        self.assertEqual(x, self.SCREEN[0])
        self.assertEqual(y, self.SCREEN[1])

    def test_disconnected_monitor_falls_back_to_first_screen(self):
        """A saved position from a second monitor that's since been
        unplugged must not strand the window somewhere unreachable --
        the whole point of this entry."""
        screens = [(0, 0, 1920, 1080)]
        # Saved position was on a monitor to the right that no longer exists.
        x, y, w, h = clamp_window_geometry(2500, 100, 601, 817, screens, MIN_SIZE)
        left, top, right, bottom = screens[0]
        self.assertGreaterEqual(x, left)
        self.assertLessEqual(x + w, right)
        self.assertGreaterEqual(y, top)
        self.assertLessEqual(y + h, bottom)

    def test_picks_the_screen_with_the_most_overlap(self):
        """Multi-monitor: a window mostly on the second screen should clamp
        against that screen, not silently snap back to the first one."""
        screens = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
        # Window sits almost entirely on the second screen, just 1px over the seam.
        x, y, w, h = clamp_window_geometry(1919, 100, 601, 817, screens, MIN_SIZE)
        self.assertGreaterEqual(x, 1920 - 1)  # stayed on/near the second screen, not yanked to screen 1

    def test_window_bigger_than_screen_is_shrunk_to_fit(self):
        screens = [(0, 0, 800, 600)]
        x, y, w, h = clamp_window_geometry(0, 0, 1200, 900, screens, MIN_SIZE)
        self.assertLessEqual(w, 800)
        self.assertLessEqual(h, 600)

    def test_empty_screens_list_is_a_no_op_beyond_min_size(self):
        """Couldn't query any screens -- trust the input rather than
        guessing at a fallback rect with no real data behind it."""
        result = clamp_window_geometry(100, 100, 601, 817, [], MIN_SIZE)
        self.assertEqual(result, (100, 100, 601, 817))


if __name__ == "__main__":
    unittest.main()
