"""Unit tests for launcher_core/settings_store.py (RELAY 095).

No committed test file existed for this module before now -- same "no test
existed, wrote one" situation this repo has hit before. Only covers
load_window_geometry/save_window_geometry (what this entry actually
touched) -- not backfilling coverage for the module's other, pre-existing
settings, which this entry didn't change.

Run: .venv\\Scripts\\python.exe -m unittest launcher_core.test_settings_store -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from launcher_core import settings_store


class TestWindowGeometry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "launcher_settings.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_none_when_nothing_saved_yet(self):
        """Caller (run_shell.main()) resolves its own hardcoded first-run
        default from this -- same "None means use the default" shape as
        load_mod_repo_path/load_custom_palette."""
        self.assertIsNone(settings_store.load_window_geometry(self.path))

    def test_round_trip(self):
        geometry = {"x": 12, "y": 34, "width": 601, "height": 817, "maximized": False}
        settings_store.save_window_geometry(geometry, self.path)
        self.assertEqual(settings_store.load_window_geometry(self.path), geometry)

    def test_save_preserves_other_settings_in_the_same_file(self):
        """Real bug this module's own docstring exists to prevent -- a save
        must merge into the existing file, not overwrite it wholesale."""
        settings_store.save_bulk_launch_pacing_seconds(20, self.path)
        settings_store.save_window_geometry({"x": 1, "y": 2, "width": 3, "height": 4, "maximized": True}, self.path)
        self.assertEqual(settings_store.load_bulk_launch_pacing_seconds(self.path), 20)
        self.assertEqual(settings_store.load_window_geometry(self.path)["maximized"], True)

    def test_maximized_round_trips_as_a_real_bool(self):
        settings_store.save_window_geometry(
            {"x": 0, "y": 0, "width": 601, "height": 817, "maximized": True}, self.path
        )
        geometry = settings_store.load_window_geometry(self.path)
        self.assertIs(geometry["maximized"], True)


if __name__ == "__main__":
    unittest.main()
