"""Temporary console probe; the native getter can clear v2 data on recovery."""

from __future__ import annotations

import ctypes

import PyAgent
import PyParty
import PySkillbar
import PySystem

from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountPublication import AccountPublicationResult
from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountPublication import NativeAccountEvidence
from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountPublication import read_native_account_snapshot
from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct import AccountStruct
from Py4GWCoreLib.GlobalCache.shared_memory_src.AllAccounts import AllAccounts
from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_MAX_PLAYERS
from Py4GWCoreLib.GlobalCache.shared_memory_src.KeyStruct import KeyStruct

MODULE_NAME = "Native Account Snapshot v2 Probe"
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

_PREFIX = "NATIVE_ACCOUNT_SNAPSHOT_V2_PROBE_V3"
_SAMPLE_COUNT = 3
_SAMPLE_INTERVAL_MS = 5000
_MAX_RECORDS = 8
_MAX_ROSTER_HEROES = 2
_MAX_CHILD_AGENT_IDS = 8
_MAX_SKILL_IDS = 8
_MAX_REASON_LENGTH = 120

_samples_taken = 0
_next_sample_tick64: int | None = None


def _safe_text(value: object, limit: int = _MAX_REASON_LENGTH) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _role(account: AccountStruct) -> str:
    if account.IsAccount:
        return "owner/player"
    if account.IsHero:
        return "hero"
    if account.IsPet:
        return "pet"
    return "unknown"


def _record_sane(evidence: NativeAccountEvidence, account: AccountStruct) -> bool:
    flags = (bool(account.IsAccount), bool(account.IsHero), bool(account.IsPet))
    if not account.IsSlotActive or sum(flags) != 1 or account.IsNPC:
        return False

    role = _role(account)
    expected_entity_type = {"owner/player": 0, "hero": 1, "pet": 2}.get(role)
    if expected_entity_type is None or int(account.Key.EntityType) != expected_entity_type:
        return False

    if (
        int(evidence.slot_index) != int(account.SlotNumber)
        or int(account.Key.HWND) <= 0
        or int(account.AgentData.AgentID) <= 0
        or int(account.AgentData.Map.MapID) <= 0
        or int(account.AgentPartyData.PartyID) <= 0
    ):
        return False

    if account.IsAccount:
        return int(account.Key.LocalIndex) == 0 and int(account.AgentData.OwnerAgentID) == 0
    if account.IsHero:
        return (
            int(account.AgentData.OwnerAgentID) > 0
            and int(account.AgentData.HeroID) > 0
            and int(account.Key.LocalIndex) == int(account.AgentData.HeroID)
        )
    return (
        int(account.AgentData.OwnerAgentID) > 0
        and int(account.AgentData.HeroID) == 0
        and int(account.Key.LocalIndex) == 0
    )


def _links_sane(records: list[tuple[NativeAccountEvidence, AccountStruct]]) -> bool:
    owners = [account for _evidence, account in records if account.IsAccount]
    for _evidence, child in records:
        if child.IsAccount:
            continue
        parents = [
            owner
            for owner in owners
            if int(owner.Key.HWND) == int(child.Key.HWND)
            and int(owner.AgentData.AgentID) == int(child.AgentData.OwnerAgentID)
        ]
        if len(parents) != 1:
            return False
        owner = parents[0]
        owner_map = owner.AgentData.Map
        child_map = child.AgentData.Map
        if (
            int(child.LastUpdated) != int(owner.LastUpdated)
            or int(child.AgentPartyData.PartyID) != int(owner.AgentPartyData.PartyID)
            or int(child_map.MapID) != int(owner_map.MapID)
            or int(child_map.Region) != int(owner_map.Region)
            or int(child_map.District) != int(owner_map.District)
            or int(child_map.Language) != int(owner_map.Language)
        ):
            return False
    return True


def _print_associations(records: list[tuple[NativeAccountEvidence, AccountStruct]]) -> None:
    owners = [(evidence, account) for evidence, account in records if account.IsAccount]
    if not owners:
        print(f"{_PREFIX} associations=none")
        return

    for evidence, owner in owners[:_MAX_RECORDS]:
        children = [
            account
            for _child_evidence, account in records
            if not account.IsAccount
            and int(account.Key.HWND) == int(owner.Key.HWND)
            and int(account.AgentData.OwnerAgentID) == int(owner.AgentData.AgentID)
        ]
        hero_count = sum(1 for account in children if account.IsHero)
        pet_count = sum(1 for account in children if account.IsPet)
        child_agent_ids = [str(int(account.AgentData.AgentID)) for account in children[:_MAX_CHILD_AGENT_IDS]]
        if len(children) > _MAX_CHILD_AGENT_IDS:
            child_agent_ids.append(f"+{len(children) - _MAX_CHILD_AGENT_IDS}")
        rendered_ids = ",".join(child_agent_ids) if child_agent_ids else "-"
        print(
            f"{_PREFIX} association owner_slot={int(evidence.slot_index)} "
            f"owner_agent_id={int(owner.AgentData.AgentID)} heroes={hero_count} pets={pet_count} "
            f"child_agent_ids=[{rendered_ids}]"
        )


def _print_raw_snapshot(native_tuple: tuple[str, int, bytes, int, int, int, int], local_hwnd: int) -> None:
    native_status = "unavailable"
    try:
        (
            status_text,
            captured_tick64,
            payload,
            prefix_size,
            total_size,
            native_span,
            timestamp_offset,
        ) = native_tuple
        native_status = _safe_text(status_text, 40)
        if native_status != "success":
            print(
                f"{_PREFIX} raw_summary native_status={native_status} raw_parse=unavailable "
                "active_raw=unavailable local_active_raw=unavailable"
            )
            return

        if type(payload) is not bytes:
            raise TypeError("detached payload is not bytes")

        key_offset = int(getattr(AllAccounts, "Keys").offset)
        account_offset = int(getattr(AllAccounts, "AccountData").offset)
        key_size = ctypes.sizeof(KeyStruct)
        account_size = ctypes.sizeof(AccountStruct)
        keys_end = key_offset + key_size * SHMEM_MAX_PLAYERS
        accounts_end = account_offset + account_size * SHMEM_MAX_PLAYERS
        expected_prefix = int(getattr(AllAccounts, "Inbox").offset)
        expected_total = ctypes.sizeof(AllAccounts)
        expected_native_span = int(getattr(AccountStruct, "IsIsolated").offset)
        expected_timestamp_offset = int(getattr(AccountStruct, "LastUpdated").offset)
        if key_offset < 0 or account_offset < keys_end or len(payload) < max(keys_end, accounts_end):
            raise ValueError("detached payload does not contain complete key/account tables")
        layout_meta_match = (
            key_offset == 0
            and account_offset == keys_end
            and prefix_size == expected_prefix == accounts_end
            and total_size == expected_total
            and native_span == expected_native_span
            and timestamp_offset == expected_timestamp_offset
            and len(payload) == prefix_size
        )

        active_records: list[tuple[int, AccountStruct, KeyStruct]] = []
        local_records: list[tuple[int, AccountStruct, KeyStruct]] = []
        for raw_slot in range(SHMEM_MAX_PLAYERS):
            account = AccountStruct.from_buffer_copy(payload, account_offset + raw_slot * account_size)
            if not account.IsSlotActive:
                continue
            external_key = KeyStruct.from_buffer_copy(payload, key_offset + raw_slot * key_size)
            item = (raw_slot, account, external_key)
            active_records.append(item)
            if local_hwnd > 0 and (int(account.Key.HWND) == local_hwnd or int(external_key.HWND) == local_hwnd):
                local_records.append(item)

        local_count = str(len(local_records)) if local_hwnd > 0 else "unavailable"
        local_shown = min(len(local_records), _MAX_RECORDS)
        print(
            f"{_PREFIX} raw_summary native_status={native_status} raw_parse=ok "
            f"capture_tick64={int(captured_tick64)} active_raw={len(active_records)} "
            f"local_active_raw={local_count} local_shown={local_shown}/{_MAX_RECORDS} "
            f"local_match=internal_or_external_hwnd local_hwnd={local_hwnd if local_hwnd > 0 else 'unavailable'} "
            f"layout_meta_match={'yes' if layout_meta_match else 'no'} "
            f"tuple_layout=prefix:{int(prefix_size)},total:{int(total_size)},span:{int(native_span)},"
            f"timestamp:{int(timestamp_offset)}"
        )

        for raw_slot, account, external_key in local_records[:_MAX_RECORDS]:
            internal_key = account.Key
            map_data = account.AgentData.Map
            modular_age = ((int(captured_tick64) & 0xFFFFFFFF) - int(account.LastUpdated)) & 0xFFFFFFFF
            keys_agree = (
                int(internal_key.HWND) == int(external_key.HWND)
                and int(internal_key.EntityType) == int(external_key.EntityType)
                and int(internal_key.LocalIndex) == int(external_key.LocalIndex)
            )
            print(
                f"{_PREFIX} raw_record slot={raw_slot} active=yes stored_slot={int(account.SlotNumber)} "
                f"flags=account:{int(bool(account.IsAccount))},hero:{int(bool(account.IsHero))},"
                f"pet:{int(bool(account.IsPet))},npc:{int(bool(account.IsNPC))} "
                f"internal_key=(hwnd:{int(internal_key.HWND)},type:{int(internal_key.EntityType)},"
                f"local:{int(internal_key.LocalIndex)}) "
                f"external_key=(hwnd:{int(external_key.HWND)},type:{int(external_key.EntityType)},"
                f"local:{int(external_key.LocalIndex)}) key_agree={'yes' if keys_agree else 'no'} "
                f"agent_id={int(account.AgentData.AgentID)} "
                f"owner_agent_id={int(account.AgentData.OwnerAgentID)} "
                f"hero_id={int(account.AgentData.HeroID)} login_number={int(account.AgentData.LoginNumber)} "
                f"map_id={int(map_data.MapID)} region={int(map_data.Region)} "
                f"district={int(map_data.District)} language={int(map_data.Language)} "
                f"party_id={int(account.AgentPartyData.PartyID)} last_updated={int(account.LastUpdated)} "
                f"modular_age_ms={modular_age}"
            )
    except Exception as error:
        print(
            f"{_PREFIX} raw_summary native_status={native_status} raw_parse=error "
            "active_raw=unavailable local_active_raw=unavailable "
            f"details={_safe_text(f'{type(error).__name__}: {error}')}"
        )


def _roster_int(hero: object, field: str) -> int | None:
    try:
        return int(getattr(hero, field))
    except Exception:
        return None


def _print_roster(records: list[tuple[NativeAccountEvidence, AccountStruct]]) -> None:
    try:
        heroes = tuple(PyParty.PyParty().heroes)
    except Exception as error:
        print(f"{_PREFIX} roster status=error error_type={type(error).__name__} atomic_with_native=no")
        return

    print(
        f"{_PREFIX} roster status=ok hero_count={len(heroes)} "
        f"shown={min(len(heroes), _MAX_ROSTER_HEROES)}/{_MAX_ROSTER_HEROES} atomic_with_native=no"
    )

    skillbar_reader = None
    skillbar_reader_error = ""
    if heroes:
        try:
            skillbar_reader = PySkillbar.Skillbar()
        except Exception as error:
            skillbar_reader_error = f"error:{type(error).__name__}"

    for roster_index, hero in enumerate(heroes):
        if roster_index >= _MAX_ROSTER_HEROES:
            break

        agent_id = _roster_int(hero, "agent_id")
        hero_id = _roster_int(hero, "hero_id")
        owner_player_id = _roster_int(hero, "owner_player_id")
        resolved_owner = "unavailable"
        if owner_player_id is not None:
            try:
                resolved_owner = str(int(PyAgent.get_agent_id_by_login_number(owner_player_id)))
            except Exception as error:
                resolved_owner = f"error:{type(error).__name__}"

        living = "unavailable"
        if agent_id is not None and agent_id > 0:
            try:
                living = "yes" if PyAgent.PyAgent(agent_id).GetIsLiving() else "no"
            except Exception as error:
                living = f"error:{type(error).__name__}"

        print(
            f"{_PREFIX} roster_hero roster_index={roster_index} "
            f"agent_id={agent_id if agent_id is not None else 'unavailable'} "
            f"hero_id={hero_id if hero_id is not None else 'unavailable'} "
            f"owner_player_id={owner_player_id if owner_player_id is not None else 'unavailable'} "
            f"resolved_owner_agent_id={resolved_owner} living={living}"
        )

        # The Native publisher calls GetHeroSkillbar with zero-based roster index + 1.
        native_skillbar_position = roster_index + 1
        position_agent_id: int | None = None
        position_agent_error = ""
        try:
            position_agent_id = int(PyAgent.get_hero_agent_id(native_skillbar_position))
        except Exception as error:
            position_agent_error = f"error:{type(error).__name__}"

        direct_skill_ids: list[int] | None = None
        direct_skill_count = "unavailable"
        direct_error = skillbar_reader_error or ""
        if skillbar_reader is not None:
            try:
                direct_skills = tuple(skillbar_reader.GetHeroSkillbar(native_skillbar_position))
                direct_skill_count = str(len(direct_skills))
                direct_skill_ids = [int(skill.id.id) for skill in direct_skills[:_MAX_SKILL_IDS]]
            except Exception as error:
                direct_error = f"error:{type(error).__name__}"

        matching_children = [
            account
            for _evidence, account in records
            if account.IsHero
            and agent_id is not None
            and agent_id > 0
            and hero_id is not None
            and hero_id > 0
            and int(account.AgentData.AgentID) == agent_id
            and int(account.AgentData.HeroID) == hero_id
        ]
        published_skill_ids: list[int] | None = None
        if len(matching_children) == 1:
            try:
                published_skill_ids = [
                    int(skill.Id) for skill in matching_children[0].AgentData.Skillbar.Skills[:_MAX_SKILL_IDS]
                ]
            except Exception:
                published_skill_ids = None

        if position_agent_id is None or agent_id is None or agent_id <= 0:
            position_matches_roster = "unavailable"
        else:
            position_matches_roster = "yes" if position_agent_id == agent_id else "no"

        if (
            len(matching_children) == 1
            and len(direct_skill_ids or ()) == _MAX_SKILL_IDS
            and direct_skill_count == str(_MAX_SKILL_IDS)
            and len(published_skill_ids or ()) == _MAX_SKILL_IDS
            and position_agent_id is not None
            and agent_id is not None
            and agent_id > 0
            and hero_id is not None
            and hero_id > 0
        ):
            comparison = "yes" if position_agent_id == agent_id and direct_skill_ids == published_skill_ids else "no"
        else:
            comparison = "unavailable"

        direct_text = (
            f"[{','.join(str(skill_id) for skill_id in direct_skill_ids)}]"
            if direct_skill_ids is not None
            else "unavailable"
        )
        published_text = (
            f"[{','.join(str(skill_id) for skill_id in published_skill_ids)}]"
            if published_skill_ids is not None
            else "unavailable"
        )
        position_agent_text = str(position_agent_id) if position_agent_id is not None else position_agent_error
        print(
            f"{_PREFIX} hero_skillbar roster_index={roster_index} "
            f"hero_id={hero_id if hero_id is not None else 'unavailable'} "
            f"agent_id={agent_id if agent_id is not None else 'unavailable'} "
            f"native_skillbar_position={native_skillbar_position} position_agent_id={position_agent_text} "
            f"position_matches_roster={position_matches_roster} "
            f"direct_skill_count={direct_skill_count} direct_skill_ids={direct_text} "
            f"published_child_matches={len(matching_children)} published_skill_ids={published_text} "
            f"match={comparison} atomic_with_snapshot=no "
            f"direct_error={direct_error or 'none'}"
        )


def _sample(sample_number: int, sample_tick64: int) -> None:
    try:
        local_hwnd = int(PySystem.Console.get_gw_window_handle() or 0)
    except Exception:
        local_hwnd = 0

    try:
        native_tuple = PySystem.get_account_publication_snapshot()
    except Exception as error:
        print(
            f"{_PREFIX} BEGIN sample={sample_number}/{_SAMPLE_COUNT} "
            f"api=PySystem.get_account_publication_snapshot/v2 getter_calls=1 "
            f"sample_tick64={sample_tick64} local_hwnd={local_hwnd if local_hwnd > 0 else 'unavailable'}"
        )
        print(
            f"{_PREFIX} raw_summary native_status=exception raw_parse=unavailable "
            "active_raw=unavailable local_active_raw=unavailable"
        )
        print(
            f"{_PREFIX} status=unavailable reason={_safe_text(f'{type(error).__name__}: {error}')} "
            "snapshot_present=no usable_records=0 local_owner=unknown "
            "record_checks=no-snapshot owner_child_checks=no-snapshot"
        )
        _print_roster([])
        print(f"{_PREFIX} END sample={sample_number}/{_SAMPLE_COUNT}")
        return

    print(
        f"{_PREFIX} BEGIN sample={sample_number}/{_SAMPLE_COUNT} "
        f"api=PySystem.get_account_publication_snapshot/v2 getter_calls=1 "
        "decoder_input=same_tuple "
        f"sample_tick64={sample_tick64} local_hwnd={local_hwnd if local_hwnd > 0 else 'unavailable'}"
    )
    _print_raw_snapshot(native_tuple, local_hwnd)

    decoded: AccountPublicationResult | None = None
    decoder_error = ""
    captured_tuple = native_tuple
    try:
        decoded = read_native_account_snapshot(lambda: captured_tuple)
    except Exception as error:
        decoder_error = f"{type(error).__name__}: {error}"

    if decoded is None:
        status = "exception"
        reason = _safe_text(decoder_error) if decoder_error else "decoder unavailable"
        snapshot = None
    else:
        status = _safe_text(getattr(decoded.status, "value", decoded.status), 40)
        reason = _safe_text(decoded.reason) if decoded.reason else "none"
        snapshot = decoded.snapshot

    records: list[tuple[NativeAccountEvidence, AccountStruct]] = []
    if snapshot is not None:
        # GetAccountData decodes a new Python-owned copy of each detached record.
        records = [(evidence, evidence.GetAccountData()) for evidence in snapshot.accounts]

    if local_hwnd > 0 and snapshot is not None:
        local_owner_present = any(
            account.IsAccount and int(account.Key.HWND) == local_hwnd for _evidence, account in records
        )
        local_owner = "yes" if local_owner_present else "no"
        local_hwnd_text = str(local_hwnd)
    else:
        local_owner = "unknown"
        local_hwnd_text = "unavailable"

    if records:
        record_checks = "pass" if all(_record_sane(evidence, account) for evidence, account in records) else "fail"
        link_checks = "pass" if _links_sane(records) else "fail"
    else:
        record_checks = "no-records" if snapshot is not None else "no-snapshot"
        link_checks = record_checks
    usable_count = len(snapshot.accounts) if snapshot is not None else 0
    shown_count = min(usable_count, _MAX_RECORDS)
    captured_tick64 = snapshot.captured_at_tick64 if snapshot is not None else "unavailable"

    print(
        f"{_PREFIX} status={status} "
        f"snapshot_present={'yes' if snapshot is not None else 'no'} captured_tick64={captured_tick64} "
        f"usable_records={usable_count} shown={shown_count}/{_MAX_RECORDS} "
        f"local_owner={local_owner} local_hwnd={local_hwnd_text} "
        f"record_checks={record_checks} owner_child_checks={link_checks}"
    )
    print(f"{_PREFIX} reason={reason}")

    # AccountEmail is a private cohort key and is deliberately never printed.
    if snapshot is not None:
        for evidence, account in records[:_MAX_RECORDS]:
            skills = ",".join(str(int(skill.Id)) for skill in account.AgentData.Skillbar.Skills[:_MAX_SKILL_IDS])
            print(
                f"{_PREFIX} record slot={int(evidence.slot_index)} identity=slot:{int(evidence.slot_index)} "
                f"role={_role(account)} entity_type={int(account.Key.EntityType)} hwnd={int(account.Key.HWND)} "
                f"local_index={int(account.Key.LocalIndex)} agent_id={int(account.AgentData.AgentID)} "
                f"owner_agent_id={int(account.AgentData.OwnerAgentID)} map_id={int(account.AgentData.Map.MapID)} "
                f"party_id={int(account.AgentPartyData.PartyID)} last_updated={int(account.LastUpdated)} "
                f"skillbar_agent_id=not-exposed skill_ids=[{skills}] "
                f"record_sane={'pass' if _record_sane(evidence, account) else 'fail'}"
            )
        _print_associations(records)

    _print_roster(records)
    print(f"{_PREFIX} END sample={sample_number}/{_SAMPLE_COUNT}")


def update() -> None:
    """Take three console-only snapshots, five seconds apart, then stop."""
    global _next_sample_tick64, _samples_taken

    if _samples_taken >= _SAMPLE_COUNT:
        return

    now = int(PySystem.get_tick_count64())
    if _next_sample_tick64 is not None and now < _next_sample_tick64:
        return

    _sample(_samples_taken + 1, now)
    _samples_taken += 1
    _next_sample_tick64 = now + _SAMPLE_INTERVAL_MS
