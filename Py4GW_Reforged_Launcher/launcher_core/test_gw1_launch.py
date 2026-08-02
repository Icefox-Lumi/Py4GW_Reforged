"""Unit tests for launcher_core/gw1_launch.py's gMod graceful-skip fix (RELAY 091).

No committed test coverage existed for gw1_launch.py at all before this --
verified via a real search, not assumed (same situation RELAY 088 hit for
prereqs.py). The full launch pipeline is heavily Win32-coupled
(CreateProcessW, CreateRemoteThread, window polling), not something to mock
wholesale for a scope this small -- _resolve_gmod_launch_decision was pulled
out specifically so the actual decision logic is testable in isolation.

One regression test at the full launch_py4gw_profile level confirms the
py4gw_dll_path hard-fail (deliberately unchanged by this entry) still fires
before any process gets created -- that path doesn't touch Win32 either,
since it returns before CreateProcessW.

RELAY 094 adds two more testable-without-Win32 pieces: _write_account_anchor
(same plain-configparser read-modify-write shape as _write_autoexec_script,
just a different ini key) and _attach_to_steam_process's process-name-match-
plus-path-validation logic (mocks psutil.process_iter directly rather than
touching real OS processes -- the actual OpenProcess/ReadProcessMemory/
CreateRemoteThread injection surface stays untested here, same boundary
the rest of this file already draws).

Run: .venv\\Scripts\\python.exe -m unittest launcher_core.test_gw1_launch -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher_core import gw1_launch
from launcher_core.gw1_launch import (
    _attach_to_steam_process,
    _resolve_gmod_launch_decision,
    _write_account_anchor,
    launch_py4gw_profile,
)
from launcher_core.profile import GameProfile


class ResolveGmodLaunchDecisionTests(unittest.TestCase):
    def setUp(self):
        self.log: list = []

    def test_gmod_disabled_on_profile_returns_false_no_autodetect(self):
        profile = GameProfile(gmod_enabled=False, gmod_dll_path="")
        with patch.object(gw1_launch.mod_root, "find_dll_under_mod_root") as mock_detect:
            result = _resolve_gmod_launch_decision(profile, gmod_injection_enabled=True, log=self.log)
        self.assertFalse(result)
        mock_detect.assert_not_called()

    def test_gmod_disabled_globally_returns_false_no_autodetect(self):
        profile = GameProfile(gmod_enabled=True, gmod_dll_path="")
        with patch.object(gw1_launch.mod_root, "find_dll_under_mod_root") as mock_detect:
            result = _resolve_gmod_launch_decision(profile, gmod_injection_enabled=False, log=self.log)
        self.assertFalse(result)
        mock_detect.assert_not_called()

    def test_path_already_valid_returns_true_no_autodetect(self):
        with tempfile.NamedTemporaryFile(suffix=".dll", delete=False) as f:
            real_path = f.name
        try:
            profile = GameProfile(gmod_enabled=True, gmod_dll_path=real_path)
            with patch.object(gw1_launch.mod_root, "find_dll_under_mod_root") as mock_detect:
                result = _resolve_gmod_launch_decision(profile, gmod_injection_enabled=True, log=self.log)
            self.assertTrue(result)
            mock_detect.assert_not_called()
        finally:
            Path(real_path).unlink()

    def test_missing_path_autodetect_resolves_it_mutates_profile_and_logs(self):
        profile = GameProfile(gmod_enabled=True, gmod_dll_path="")
        with patch.object(gw1_launch.mod_root, "find_dll_under_mod_root", return_value="C:/found/gMod.dll") as mock_detect:
            result = _resolve_gmod_launch_decision(profile, gmod_injection_enabled=True, log=self.log)
        self.assertTrue(result)
        mock_detect.assert_called_once_with("gMod.dll")
        self.assertEqual(profile.gmod_dll_path, "C:/found/gMod.dll")
        self.assertTrue(any("auto-detected" in line for line in self.log))

    def test_missing_path_autodetect_still_fails_graceful_skip_not_hard_fail(self):
        """The core RELAY 091 behavior change: this used to hard-fail the
        whole launch (LaunchResult(False, ...)) -- now it's just a decision
        of False, with a clear log line, so the caller can proceed without
        gMod instead of aborting Py4GW injection too."""
        profile = GameProfile(gmod_enabled=True, gmod_dll_path="")
        with patch.object(gw1_launch.mod_root, "find_dll_under_mod_root", return_value=""):
            result = _resolve_gmod_launch_decision(profile, gmod_injection_enabled=True, log=self.log)
        self.assertFalse(result)
        self.assertEqual(profile.gmod_dll_path, "")  # not persisted from a failed redetect
        self.assertTrue(any("launching without gMod injection" in line for line in self.log))

    def test_stale_nonexistent_path_treated_same_as_empty(self):
        """A saved path that doesn't exist on disk anymore (not just an
        empty string) should also trigger the redetect attempt."""
        profile = GameProfile(gmod_enabled=True, gmod_dll_path="C:/does/not/exist/gMod.dll")
        with patch.object(gw1_launch.mod_root, "find_dll_under_mod_root", return_value="C:/found/gMod.dll") as mock_detect:
            result = _resolve_gmod_launch_decision(profile, gmod_injection_enabled=True, log=self.log)
        self.assertTrue(result)
        mock_detect.assert_called_once()
        self.assertEqual(profile.gmod_dll_path, "C:/found/gMod.dll")


class Py4GwHardFailRegressionTest(unittest.TestCase):
    """RELAY 091 explicitly scoped gMod-only -- confirms the identical
    py4gw_dll_path check just above it is genuinely untouched, not just
    read-and-assumed unchanged."""

    def test_py4gw_path_missing_still_hard_fails_before_any_process_created(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake_exe = f.name
        try:
            profile = GameProfile(
                executable_path=fake_exe,
                py4gw_enabled=True,
                py4gw_dll_path="C:/does/not/exist/Py4GW.dll",
                gmod_enabled=False,
            )
            result = launch_py4gw_profile(profile, py4gw_injection_enabled=True, gmod_injection_enabled=True)
        finally:
            Path(fake_exe).unlink()

        self.assertFalse(result.success)
        self.assertIn("py4gw_dll_path not found", result.error or "")


class WriteAccountAnchorTests(unittest.TestCase):
    """RELAY 094: _write_account_anchor mirrors _write_autoexec_script's own
    read-modify-write shape exactly (RELAY 057) -- these tests are the same
    shape as that function would need, just none existed for either before
    this entry (verified via a real search, same situation this file's own
    module docstring already flags)."""

    def setUp(self):
        self.log: list = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.mod_root_path = Path(self._tmpdir.name)
        self._patcher = patch.object(gw1_launch, "_mod_root", return_value=self.mod_root_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_writes_key_into_new_ini(self):
        _write_account_anchor("my-anchor", self.log)
        ini_path = self.mod_root_path / "Py4GW.ini"
        self.assertTrue(ini_path.exists())
        content = ini_path.read_text()
        self.assertIn("account_anchor = my-anchor", content)
        self.assertTrue(any("Wrote account_anchor" in line for line in self.log))

    def test_preserves_other_keys_and_sections(self):
        ini_path = self.mod_root_path / "Py4GW.ini"
        ini_path.write_text("[settings]\nautoexec_script = C:/some/script.py\n\n[other]\nkey = value\n")

        _write_account_anchor("my-anchor", self.log)

        content = ini_path.read_text()
        self.assertIn("autoexec_script = C:/some/script.py", content)
        self.assertIn("account_anchor = my-anchor", content)
        self.assertIn("[other]", content)
        self.assertIn("key = value", content)

    def test_overwrites_stale_value_for_same_key(self):
        ini_path = self.mod_root_path / "Py4GW.ini"
        ini_path.write_text("[settings]\naccount_anchor = old-anchor\n")

        _write_account_anchor("new-anchor", self.log)

        content = ini_path.read_text()
        self.assertIn("account_anchor = new-anchor", content)
        self.assertNotIn("old-anchor", content)

    def test_write_failure_is_non_fatal(self):
        with patch("builtins.open", side_effect=OSError("disk full")):
            _write_account_anchor("my-anchor", self.log)  # must not raise
        self.assertTrue(any("non-fatal" in line for line in self.log))


class AttachToSteamProcessTests(unittest.TestCase):
    """RELAY 094: _attach_to_steam_process's name-match-plus-path-validation
    logic, ported from GWxLauncher's SteamProcessAttachService.TryAttachToSteamProcess
    with one addition that reference doesn't have (see the function's own
    docstring) -- mocks psutil.process_iter directly, no real processes or
    Win32 calls involved."""

    class _FakeProc:
        def __init__(self, info: dict):
            self.info = info

    def _iter(self, procs):
        return lambda attrs: iter(procs)

    def test_finds_matching_process_by_name_and_path(self):
        proc = self._FakeProc({"pid": 4242, "name": "Gw.exe", "exe": "C:/Games/GW/Gw.exe", "create_time": 1000.0})
        with patch.object(gw1_launch.psutil, "process_iter", side_effect=self._iter([proc])):
            pid = _attach_to_steam_process("C:/Games/GW/Gw.exe", launched_after=999.0, log=[], timeout=1.0)
        self.assertEqual(pid, 4242)

    def test_rejects_process_with_mismatched_exe_path(self):
        """The addition GWxLauncher's own reference doesn't have: name-only
        matching isn't enough in a multibox tool where more than one Gw.exe
        copy across different accounts is the normal case."""
        wrong_path_proc = self._FakeProc(
            {"pid": 111, "name": "Gw.exe", "exe": "C:/Other/Account/Gw.exe", "create_time": 1000.0}
        )
        with patch.object(gw1_launch.psutil, "process_iter", side_effect=self._iter([wrong_path_proc])):
            pid = _attach_to_steam_process("C:/Games/GW/Gw.exe", launched_after=999.0, log=[], timeout=0.05)
        self.assertIsNone(pid)

    def test_rejects_process_created_before_launch_timestamp(self):
        """A leftover Gw.exe from an earlier session must not be mistaken
        for the one Steam just spawned."""
        stale_proc = self._FakeProc(
            {"pid": 222, "name": "Gw.exe", "exe": "C:/Games/GW/Gw.exe", "create_time": 500.0}
        )
        with patch.object(gw1_launch.psutil, "process_iter", side_effect=self._iter([stale_proc])):
            pid = _attach_to_steam_process("C:/Games/GW/Gw.exe", launched_after=999.0, log=[], timeout=0.05)
        self.assertIsNone(pid)

    def test_empty_exe_path_skips_path_check(self):
        """profile.executable_path being unresolvable/empty shouldn't reject
        an otherwise-good name+recency match -- name-plus-recency is still
        meaningfully selective on its own (see the function's own docstring)."""
        proc = self._FakeProc({"pid": 333, "name": "Gw.exe", "exe": "C:/Anything/Gw.exe", "create_time": 1000.0})
        with patch.object(gw1_launch.psutil, "process_iter", side_effect=self._iter([proc])):
            pid = _attach_to_steam_process("", launched_after=999.0, log=[], timeout=1.0)
        self.assertEqual(pid, 333)

    def test_ignores_unrelated_process_names(self):
        unrelated = self._FakeProc(
            {"pid": 444, "name": "notepad.exe", "exe": "C:/Windows/notepad.exe", "create_time": 1000.0}
        )
        with patch.object(gw1_launch.psutil, "process_iter", side_effect=self._iter([unrelated])):
            pid = _attach_to_steam_process("C:/Games/GW/Gw.exe", launched_after=999.0, log=[], timeout=0.05)
        self.assertIsNone(pid)

    def test_timeout_returns_none_and_logs(self):
        log: list = []
        with patch.object(gw1_launch.psutil, "process_iter", side_effect=self._iter([])):
            pid = _attach_to_steam_process("C:/Games/GW/Gw.exe", launched_after=999.0, log=log, timeout=0.05)
        self.assertIsNone(pid)
        self.assertTrue(any("Timed out" in line for line in log))


if __name__ == "__main__":
    unittest.main()
