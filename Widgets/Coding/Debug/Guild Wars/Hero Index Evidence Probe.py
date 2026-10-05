from __future__ import annotations

from typing import Any

import PyParty
import PySkillbar

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Map
from Py4GWCoreLib import Player

MODULE_NAME = "Hero Index Evidence Probe"
MODULE_ICON = "Assets/Textures/Module_Icons/Debug.png"
OPTIONAL = True

__widget__ = {
    "name": MODULE_NAME,
    "enabled": True,
    "category": "Coding",
    "subcategory": "Debug",
    "icon": "ICON_SEARCH",
    "quickdock": False,
}

_PREFIX = "HERO_INDEX_PROBE_V1"
_INDEX_CASES = (0, 1, 2)
_MAX_TEXT_LENGTH = 120
_MAX_ROSTER_ROWS = 16
_capture_complete = False
_waiting_reported = False


def _text(value: Any, limit: int = _MAX_TEXT_LENGTH) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _field(value: Any, name: str) -> Any | None:
    try:
        return getattr(value, name)
    except Exception:
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _error(error: Exception) -> str:
    return _text(f"{type(error).__name__}: {error}")


def _hero_name(hero_id: int | None) -> str:
    if hero_id is None or hero_id <= 0:
        return "unavailable"
    try:
        name = PyParty.Hero(hero_id).GetName()
    except Exception as error:
        return f"error({_error(error)})"
    return _text(name) if name else "unavailable"


def _skill_name(skill_id: int | None) -> str:
    if skill_id is None:
        return "unavailable"
    if skill_id <= 0:
        return "empty"
    try:
        name = GLOBAL_CACHE.Skill.GetName(skill_id)
    except Exception as error:
        return f"error({_error(error)})"
    return _text(name, 64) if name else "unresolved"


def _report_waiting(reason: str) -> None:
    global _waiting_reported
    if _waiting_reported:
        return
    _waiting_reported = True
    print(f"{_PREFIX} waiting: {_text(reason)}")


def _roster_match(agent_id: int | None, heroes: tuple[Any, ...]) -> str:
    if agent_id is None:
        return "unresolved"
    for roster_order, hero in enumerate(heroes, start=1):
        roster_agent_id = _integer(_field(hero, "agent_id"))
        if roster_agent_id == agent_id:
            hero_id = _integer(_field(hero, "hero_id"))
            owner_id = _integer(_field(hero, "owner_player_id"))
            return f"roster_order={roster_order},hero_id={hero_id},owner_id={owner_id}"
    return "none"


def _skill_slots(bar: Any) -> str:
    result_agent_id = _field(bar, "agent_id")
    result_owner_id = _field(bar, "owner_player_id")
    slots = tuple(bar)
    rendered_slots: list[str] = []
    for slot_number, slot in enumerate(slots[:8], start=1):
        skill_ref = _field(slot, "id")
        skill_id = _integer(_field(skill_ref, "id"))
        rendered_slots.append(f"{slot_number}:{skill_id}:{_skill_name(skill_id)}")
    if len(slots) > 8:
        rendered_slots.append(f"truncated={len(slots) - 8}")
    return (
        f"result_type={type(bar).__name__} "
        f"agent_id={_text(result_agent_id) if result_agent_id is not None else 'unavailable'} "
        f"owner_id={_text(result_owner_id) if result_owner_id is not None else 'unavailable'} "
        f"slot_count={len(slots)} slots=[{'; '.join(rendered_slots)}]"
    )


def _capture(
    *,
    native_party: Any,
    skillbar: Any,
    heroes: tuple[Any, ...],
    local_heroes: tuple[Any, ...],
    player_agent_id: int,
    player_login_number: int,
    map_ready: bool,
    map_loading: bool,
    outpost: bool,
    map_id: int | None,
    party_loaded: bool,
) -> None:
    global _capture_complete

    player_name = "unavailable"
    try:
        player_name = _text(Player.GetName())
    except Exception as error:
        player_name = f"error({_error(error)})"

    lines = [
        f"{_PREFIX} BEGIN",
        (
            f"{_PREFIX} context map_ready={map_ready} map_loading={map_loading} "
            f"outpost={outpost} map_id={map_id} party_loaded={party_loaded} "
            f"player_agent_id={player_agent_id} player_login_number={player_login_number} "
            f"player_name={player_name} party_hero_count={len(heroes)} "
            f"local_owned_hero_count={len(local_heroes)} "
            "roster_source=PyParty.PyParty.GetContext().heroes"
        ),
    ]

    shown_heroes = heroes[:_MAX_ROSTER_ROWS]
    for roster_order, hero in enumerate(shown_heroes, start=1):
        hero_id = _integer(_field(hero, "hero_id"))
        agent_id = _integer(_field(hero, "agent_id"))
        owner_id = _integer(_field(hero, "owner_player_id"))
        primary = _integer(_field(hero, "primary"))
        hero_name = _hero_name(hero_id)
        is_local = owner_id == player_login_number
        lines.append(
            f"{_PREFIX} roster roster_order={roster_order} locally_owned={is_local} "
            f"hero_id={hero_id} agent_id={agent_id} owner_player_id={owner_id} "
            f"primary_profession={primary} hero_name={hero_name}"
        )
    if len(heroes) > len(shown_heroes):
        lines.append(f"{_PREFIX} roster truncated_rows={len(heroes) - len(shown_heroes)}")

    for index in _INDEX_CASES:
        try:
            raw_agent_id = native_party.GetHeroAgentID(index)
        except Exception as error:
            lines.append(
                f"{_PREFIX} hero_agent api=PyParty.PyParty.GetHeroAgentID " f"index={index} error={_error(error)}"
            )
            continue
        agent_id = _integer(raw_agent_id)
        lines.append(
            f"{_PREFIX} hero_agent api=PyParty.PyParty.GetHeroAgentID "
            f"index={index} raw_result={_text(raw_agent_id)} "
            f"agent_id={agent_id if agent_id is not None else 'unresolved'} "
            f"roster_match={_roster_match(agent_id, heroes)}"
        )

    for index in _INDEX_CASES:
        try:
            bar = skillbar.GetHeroSkillbar(index)
            if bar is None:
                lines.append(
                    f"{_PREFIX} hero_skillbar api=PySkillbar.Skillbar.GetHeroSkillbar " f"index={index} result=None"
                )
                continue
            bar_summary = _skill_slots(bar)
            lines.append(
                f"{_PREFIX} hero_skillbar api=PySkillbar.Skillbar.GetHeroSkillbar " f"index={index} {bar_summary}"
            )
        except Exception as error:
            lines.append(
                f"{_PREFIX} hero_skillbar api=PySkillbar.Skillbar.GetHeroSkillbar "
                f"index={index} error={_error(error)}"
            )

    lines.append(f"{_PREFIX} END")
    print("\n".join(lines))
    _capture_complete = True


def main() -> None:
    if _capture_complete:
        return

    try:
        map_loading = bool(Map.IsMapLoading())
        map_ready = bool(Map.IsMapReady())
        if map_loading or not map_ready:
            _report_waiting("waiting for a ready map")
            return
        outpost = bool(Map.IsOutpost())
        if not outpost:
            _report_waiting("waiting for an outpost")
            return
        if not Player.IsPlayerLoaded():
            _report_waiting("waiting for the local player")
            return

        player_agent_id = int(Player.GetAgentID() or 0)
        player_login_number = int(Player.GetLoginNumber() or 0)
        if player_agent_id <= 0 or player_login_number <= 0:
            _report_waiting("local player identity is unavailable")
            return

        native_party = PyParty.PyParty()
        native_party.GetContext()
        party_loaded = bool(native_party.is_party_loaded)
        if not party_loaded:
            _report_waiting("waiting for a loaded party")
            return

        heroes = tuple(native_party.heroes or ())
        local_heroes = tuple(
            hero for hero in heroes if _integer(_field(hero, "owner_player_id")) == player_login_number
        )
        if len(local_heroes) < 2:
            _report_waiting("waiting for at least two locally owned heroes")
            return

        skillbar = PySkillbar.Skillbar()
        skillbar.GetContext()
        map_id = _integer(Map.GetMapID())
        _capture(
            native_party=native_party,
            skillbar=skillbar,
            heroes=heroes,
            local_heroes=local_heroes,
            player_agent_id=player_agent_id,
            player_login_number=player_login_number,
            map_ready=map_ready,
            map_loading=map_loading,
            outpost=outpost,
            map_id=map_id,
            party_loaded=party_loaded,
        )
    except Exception as error:
        _report_waiting(f"probe prerequisite read failed ({_error(error)})")
