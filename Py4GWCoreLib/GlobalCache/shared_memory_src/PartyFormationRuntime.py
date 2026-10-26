"""Injected-runtime boundary for the formation service; never imports Actions."""

from __future__ import annotations

import json
from hashlib import sha256
from itertools import islice
from typing import Callable, TYPE_CHECKING, cast

from .AllAccounts import AllAccounts
from .IntentSync import get_uncached_tick_count64, publication_is_live
from .PartyFormation import Consent, Identity, MAX_ACCOUNTS, Snapshot, validate_location

if TYPE_CHECKING:
    from Py4GWCoreLib.native_src.context.PartyContext import PartyContextStruct


def _other_occupants(context: "PartyContextStruct", party_id: int, roster: tuple[int, ...]) -> int | None:
    # PyParty.others is unpopulated. Read the existing owning PartyInfo array,
    # cross-checked against the native party snapshot; never infer absence from it.
    current = context.player_party
    if current is None or int(current.party_id) != party_id:
        return None
    for array in (current.players_array, current.heroes_array, current.henchmen_array, current.others_array):
        size, capacity = int(array.m_size), int(array.m_capacity)
        if size > MAX_ACCOUNTS or size > capacity or (capacity and not array.m_buffer):
            return None
    if tuple(int(player.login_number) for player in current.players) != roster:
        return None
    return int(current.others_array.m_size)


def read_consent() -> Consent:
    from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

    document = Settings("HeroAI/PartyFormation.ini", "account")
    if not document.is_ready():
        return Consent()
    try:
        value: object = json.loads(document.get_str("Formation", "leaders", "[]"))
        if not isinstance(value, list):
            return Consent()
        items = cast(list[object], value)
        names: list[str] = []
        if len(items) > 32:
            return Consent()
        for item in items:
            if (
                not isinstance(item, str)
                or not item
                or item != item.strip().casefold()
                or len(item) > 127
                or "@" not in item
            ):
                return Consent()
            names.append(item)
        return Consent(
            document.get_bool("Formation", "enabled", False), tuple(names), document.get_int("Formation", "revision", 0)
        )
    except (ValueError, TypeError):
        return Consent()


def save_consent(enabled: bool, leaders: str) -> None:
    """Local UI only. This document is deliberately absent from settings-copy catalogs."""
    from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

    names = tuple(sorted(set(item.strip().casefold() for item in leaders.split(";") if item.strip())))
    if len(names) > 32 or any(len(item) > 127 or "@" not in item or "\n" in item for item in names):
        raise ValueError("Enter exact leader account emails separated by semicolons (maximum 32).")
    document = Settings("HeroAI/PartyFormation.ini", "account")
    if not document.is_ready():
        raise RuntimeError("Local account settings are not ready")
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

    GLOBAL_CACHE.ShMem.GetPartyFormation().invalidate_consent()
    # Disable first so interruption during configuration cannot widen permission.
    document.set_bool("Formation", "enabled", False)
    document.set_int("Formation", "revision", document.get_int("Formation", "revision", 0) + 1)
    document.set_str("Formation", "leaders", json.dumps(names))
    document.set_bool("Formation", "enabled", bool(enabled))


class FormationRuntime:
    def __init__(self, accounts: Callable[[], AllAccounts]) -> None:
        self._accounts = accounts

    def now(self) -> int:
        return get_uncached_tick_count64()

    def consent(self) -> Consent:
        return read_consent()

    def pending_attempt(self) -> str:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        document = Settings("HeroAI/PartyFormation.ini", "account")
        if not document.is_ready():
            raise RuntimeError("Formation recovery state unavailable")
        value = document.get_str("FormationSafety", "pending_attempt", "")
        if value and (len(value) != 32 or any(char not in "0123456789abcdef" for char in value)):
            raise RuntimeError("Unrecognized formation recovery state; refusing new attempts")
        return value

    def set_pending_attempt(self, expected: str, request: str) -> None:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        previous = self.pending_attempt()
        if previous != expected:
            raise RuntimeError("Formation attempt already owned")
        document = Settings("HeroAI/PartyFormation.ini", "account")
        document.set_str("FormationSafety", "pending_attempt", request)
        # This is write-ahead safety evidence, not a debounced UI preference.
        # No grant/native invitation is permitted until the owning save succeeds.
        try:
            if not document.save():
                raise RuntimeError("Unable to persist formation recovery state")
        except Exception:
            # Failed acquisition remains blocked; failed clearing restores evidence.
            document.set_str("FormationSafety", "pending_attempt", previous or request)
            raise

    def identities(self) -> tuple[Identity, ...]:
        accounts = self._accounts()
        now = self.now()
        result: list[Identity] = []
        live_emails: list[str] = []
        live_windows: list[int] = []
        for slot in range(MAX_ACCOUNTS):
            account = accounts.AccountData[slot]
            if not account.IsAccount or not account.IsSlotActive:
                continue
            stamp = int(account.LastUpdated)
            if not publication_is_live(now, stamp):
                continue
            agent = account.AgentData
            location = agent.Map
            email = str(account.AccountEmail).strip().casefold()
            live_emails.append(email)
            live_windows.append(int(account.Key.HWND))
            try:
                instance_location = validate_location(
                    [int(location.MapID), int(location.Region), int(location.District), int(location.Language)]
                )
            except ValueError:
                continue
            identity = Identity(
                slot,
                email,
                str(agent.CharacterName),
                int(agent.AgentID),
                int(agent.LoginNumber),
                int(account.Key.HWND),
                instance_location,
            )
            if (
                not email
                or not identity.character
                or min(identity.agent, identity.login, identity.hwnd) <= 0
                or int(account.LastUpdated) != stamp
                or str(account.AccountEmail).strip().casefold() != email
            ):
                continue
            result.append(identity)
        # Never choose the newest of two live identities for an email or window.
        return tuple(row for row in result if live_emails.count(row.email) == 1 and live_windows.count(row.hwnd) == 1)

    def snapshot(self) -> Snapshot | None:
        import PyMap
        import PyParty
        import PySystem
        from Py4GWCoreLib.Context import GWContext
        from Py4GWCoreLib.enums_src.Map_enums import InstanceType
        from Py4GWCoreLib.py4gwcorelib_src.WidgetManager import get_widget_handler

        if not get_widget_handler().is_widget_enabled("Messaging"):
            return None
        if (
            not PyMap.get_is_map_loaded()
            or PyMap.get_instance_type() != InstanceType.Outpost.value
            or PyMap.get_is_in_cinematic()
            or PyMap.get_is_observing()
        ):
            return None
        char = GWContext.Char.GetContext()
        info = GWContext.InstanceInfo().GetMapInfo()
        if char is None or info is None or not char.token1 or not any(char.host):
            return None
        # Guild-hall instance identity has not been runtime-validated for this path.
        from Py4GWCoreLib.Map import Map

        if Map.IsGuildHall():
            return None
        email = str(char.player_email_str or "").strip().casefold()
        hwnd = int(PySystem.Console.get_gw_window_handle())
        identities = self.identities()
        local = [row for row in identities if row.email == email and row.hwnd == hwnd]
        if len(local) != 1:
            return None
        me = local[0]
        location = (PyMap.get_map_id(), PyMap.get_region(), PyMap.get_district(), PyMap.get_language())
        if me.location != location:
            return None
        party = PyParty.PyParty()
        party.GetContext()
        if not party.is_party_loaded:
            return None
        roster = tuple(int(player.login_number) for player in party.players)
        if (
            not roster
            or me.login not in roster
            or len(set(roster)) != len(roster)
            or not all(player.is_connected for player in party.players)
            or len(roster) != party.party_player_count
            or len(party.heroes) != party.party_hero_count
            or len(party.henchmen) != party.party_henchman_count
            or party.party_size != len(roster) + len(party.heroes) + len(party.henchmen)
        ):
            return None
        seen = tuple(
            row.key
            for row in identities
            if row.location == location
            and party.GetAgentIDByLoginNumber(row.login) == row.agent
            and party.GetPlayerNameByLoginNumber(row.login) == row.character
        )
        if me.key not in seen:
            return None
        context = GWContext.Party.GetContext()
        if context is None or int(context.requests_count) > MAX_ACCOUNTS:
            return None
        others = _other_occupants(context, int(party.party_id), roster)
        if others is None:
            return None
        from Py4GWCoreLib.native_src.context.PartyContext import PartyInfoStruct
        from Py4GWCoreLib.native_src.internals.gw_list import GW_TList_View

        requests = (
            tuple(islice(GW_TList_View(context.request_list, PartyInfoStruct), MAX_ACCOUNTS + 1))
            if context.requests_count
            else ()
        )
        incoming = tuple(tuple(int(player.login_number) for player in request.players) for request in requests)
        if len(incoming) != int(context.requests_count):
            return None
        instance = sha256(int(char.token1).to_bytes(4, "little") + bytes(char.host)).hexdigest()
        return Snapshot(
            me,
            instance,
            PyMap.get_instance_time(),
            roster,
            len(party.heroes),
            len(party.henchmen),
            others,
            int(info.max_party_size),
            seen,
            incoming,
            int(self._accounts().AccountData[me.slot].AgentData.Profession[0]),
        )

    def queue(self, dispatch: Callable[[Callable[[int], bool]], None]) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        GLOBAL_CACHE.Party.Players.QueueFormationInvite(dispatch)
