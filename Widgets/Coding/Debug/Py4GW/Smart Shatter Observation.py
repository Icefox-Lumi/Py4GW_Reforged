"""Optional, explicitly armed two-client observation. All game reads run in Draw."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from Py4GWCoreLib.Builds.Skills import SmartShatterObservation as Observation

MODULE_NAME = "Smart Shatter Observation"
MODULE_CATEGORY = "Coding"
MODULE_TAGS = ["debug", "Shatter", "observation"]
OPTIONAL = True

if globals().get("_loaded", False):
    Observation.stop_capture("reloaded")
_loaded = True
_in_draw = False
_mode = 0
_label = "SH1"
_watched_label = 1
_armed_watch = 1
_clock: Callable[[], int] | None = None
_notice = "Same Windows host/boot; independently armed windows."


class _SampleFailure(Exception):
    def __init__(self, reason: str, calls: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.calls = calls


def _sample_context_draw(
    mode: Observation.Mode,
    watched_label: int,
    *,
    initial: bool,
) -> tuple[Observation.ContextSample, tuple[tuple[int, int], ...], Any, int]:
    if not _in_draw:
        raise RuntimeError("Draw sampling required")
    from Py4GWCoreLib import Effects
    from Py4GWCoreLib import Map
    from Py4GWCoreLib import Party
    from Py4GWCoreLib import Player

    calls = 0
    limit = 23 if initial else 11

    def query(function: Callable[..., Any], *args: object) -> Any:
        nonlocal calls
        if calls >= limit:
            raise _SampleFailure("sample_failure", calls)
        calls += 1
        try:
            return function(*args)
        except Exception:
            raise _SampleFailure("sample_failure", calls) from None

    if not query(Map.IsMapReady) or not query(Map.IsExplorable):
        raise _SampleFailure("context_invalid", calls)
    map_id = int(query(Map.GetMapID))
    region = int(query(Map.GetRegion)[0])
    district = int(query(Map.GetDistrict))
    language = int(query(Map.GetLanguage)[0])
    uptime = int(query(Map.GetInstanceUptime))
    player_id = int(query(Player.GetAgentID))
    party_id = int(query(Party.GetPartyID))
    players = query(Party.GetPlayers)
    if len(players) > Observation.MAX_ROSTER:
        raise _SampleFailure("roster_limit", calls)
    if not players or map_id <= 0 or player_id <= 0 or uptime < 0:
        raise _SampleFailure("context_invalid", calls)
    roster = tuple(sorted(int(players[index].login_number) for index in range(len(players))))
    if len(set(roster)) != len(roster) or any(login <= 0 for login in roster):
        raise _SampleFailure("context_invalid", calls)
    mapping: tuple[tuple[int, int], ...] = ()
    if initial:
        mapping = tuple((login, int(query(Party.Players.GetAgentIDByLoginNumber, login))) for login in roster)
        if any(agent <= 0 for _login, agent in mapping):
            raise _SampleFailure("context_invalid", calls)
    effects: Any = None
    if mode == "owner":
        watched_id = player_id
        effects = query(Effects.GetEffects, player_id)
    else:
        if not 1 <= watched_label <= len(roster):
            raise _SampleFailure("context_invalid", calls)
        watched_id = (
            mapping[watched_label - 1][1]
            if initial
            else int(query(Party.Players.GetAgentIDByLoginNumber, roster[watched_label - 1]))
        )
        if watched_id <= 0:
            raise _SampleFailure("context_invalid", calls)
    context = Observation.ContextSample(
        map_id, region, district, language, uptime, player_id, party_id, roster, watched_id
    )
    return context, mapping, effects, calls


def _arm_draw() -> None:
    global _clock, _armed_watch, _notice
    if not _in_draw:
        raise RuntimeError("Draw arming required")
    if not Observation.can_arm():
        return
    try:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64

        _clock = get_uncached_tick_count64
        start = _clock()
        mode: Observation.Mode = "owner" if _mode == 0 else "mesmer"
        context, mapping, effects, calls = _sample_context_draw(mode, _watched_label, initial=True)
        now = _clock()
        armed = Observation.arm_capture(mode, _label, _watched_label, context, mapping, _clock, start, now, calls)
        if armed is not None:
            _armed_watch = _watched_label
            if mode == "owner":
                Observation.owner_sample(armed, effects)
            _notice = "Armed once. P labels are sorted human-player roster labels."
        else:
            _notice = "Arm rejected: check label, watched player, context, and pending output."
    except Exception:
        _notice = "Arm aborted: sampling unavailable or context invalid. No automatic retry."


def _advance_draw() -> None:
    if not _in_draw:
        raise RuntimeError("Draw advancement required")
    request = Observation.draw_request()
    if request is not None:
        epoch, mode, _previous = request
        try:
            if _clock is None:
                raise _SampleFailure("sample_failure", 0)
            context, _mapping, effects, calls = _sample_context_draw(mode, _armed_watch, initial=False)
            if Observation.accept_draw_sample(epoch, context, _clock(), calls) and mode == "owner":
                Observation.owner_sample(epoch, effects)
        except _SampleFailure as error:
            Observation.sample_failed(epoch, error.reason, error.calls)
        except Exception:
            Observation.sample_failed(epoch, "sample_failure", None)
    for line in Observation.drain_console_draw():
        try:
            from Py4GWCoreLib import Console

            Console.Log("SmartShatterObs", line, Console.MessageType.Info)
        except Exception:
            Observation.stop_capture("console_failure")
            break


def on_enable() -> None:
    Observation.stop_capture("enabled_idle")


def on_disable() -> None:
    Observation.stop_capture("widget_disabled")


def draw() -> None:
    global _in_draw, _mode, _label, _watched_label
    from Py4GWCoreLib import PyImGui

    _in_draw = True
    try:
        _advance_draw()
        visible = PyImGui.begin(MODULE_NAME)
        try:
            if not visible:
                return
            PyImGui.text(Observation.capture_status())
            PyImGui.text(_notice)
            PyImGui.text("User designation only; no HR equipment recognition.")
            PyImGui.begin_disabled(not Observation.can_arm())
            try:
                _mode = PyImGui.combo("Mode", _mode, ("HR owner", "My Mesmer"))
                _label = PyImGui.input_text("Capture label (A-Z, 0-9, -, max 16)", _label)[:16]
                if _mode == 1:
                    _watched_label = max(1, min(12, PyImGui.input_int("Watched HR P number", _watched_label)))
                if PyImGui.button("Arm one capture"):
                    _arm_draw()
            finally:
                PyImGui.end_disabled()
            if PyImGui.button("Stop"):
                Observation.stop_capture()
            PyImGui.text("One 30-second window. Results: SmartShatterObs in the Py4GW console.")
            PyImGui.text("Compare overlapping boot-time timestamps and compatible context only.")
            PyImGui.text("Binding returns and continued hex presence do not prove removal.")
        finally:
            PyImGui.end()
    finally:
        _in_draw = False
