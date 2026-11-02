"""Canonical inventory records, modifier interpretation, and per-widget observations.

InventoryEvidence owns modifier caching, cache hit/miss statistics, snapshot-duration
state, and the transferred collection operations. The widget supplies dependencies
and retains its remaining runtime responsibilities and bounded delegate methods.
"""

import re
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Protocol

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Py4GWCoreLib.mods_types import ItemUpgrade
from Py4GWCoreLib.mods_types import ItemUpgradeId
from Py4GWCoreLib.mods_types import ModifierIdentifier
from Sources.icefox.MerchantRules.item_values import dedupe_identifiers as _dedupe_identifiers
from Sources.icefox.MerchantRules.item_values import (
    normalize_weapon_requirement_level as _normalize_weapon_requirement_level,
)
from Sources.icefox.MerchantRules.item_values import safe_int as _safe_int
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_PREFIX
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_SUFFIX
from Sources.icefox.MerchantRules.weapon_mod_normalization import ParsedUpgradeMatch
from Sources.icefox.MerchantRules.weapon_mod_normalization import build_parsed_weapon_mod_match

if TYPE_CHECKING:
    from Sources.marks_sources.mods_parser import ModDatabase
    from Sources.marks_sources.mods_parser import ParsedModifierResult


class ModifierParser(Protocol):
    def __call__(
        self,
        modifiers: list[tuple[int, int, int]],
        item_type: ItemType,
        model_id: int,
        db: "ModDatabase",
        /,
    ) -> "ParsedModifierResult": ...


MODIFIER_IDENTIFIER_ATTRIBUTE_REQUIREMENT = 0x279
MODIFIER_IDENTIFIER_DAMAGE = 0x27A
MODIFIER_IDENTIFIER_DAMAGE_NO_REQ = 0x248
MODIFIER_IDENTIFIER_ARMOR1 = 0x27B
MODIFIER_IDENTIFIER_ARMOR2 = 0x23C
MODIFIER_IDENTIFIER_ENERGY = 0x27C
MODIFIER_IDENTIFIER_ENERGY2 = 0x22C
MODIFIER_IDENTIFIER_RUNE_HEALTH_LOSS = 8408
MODIFIER_IDENTIFIER_TOOLTIP_DESCRIPTION = int(ModifierIdentifier.TooltipDescription)
MODIFIER_IDENTIFIER_UPGRADE = int(ModifierIdentifier.Upgrade)
MODIFIER_IDENTIFIER_ATTRIBUTE_RUNE = int(ModifierIdentifier.AttributeRune)
ARMOR_UPGRADE_ALT_MINOR_VIGOR_SIGNATURE = (9224, 0, 0x00C2)
SUPERIOR_SPAWNING_RUNE_CATALOG_IDENTIFIER = "Ritualist Rune of Superior Spawning Power"
ARMOR_UPGRADE_RUNE_CARRIER_IDS = frozenset(int(upgrade_id) for upgrade_id in ItemUpgrade.UpgradeRune.upgrade_ids)
SUPERIOR_RITUALIST_RUNE_CARRIER_ID = int(ItemUpgradeId.SuperiorRitualistRune)
ARMOR_UPGRADE_HOLDING_NAMES = frozenset(
    {
        "rune of holding",
        "superior rune of holding",
        "rune of belt holding",
    }
)


@dataclass
class InventoryItemInfo:
    """Capture the normalized live item facts used by matching, protection, and planning.

    Instances are snapshots. Execution must reacquire the item and revalidate relevant state
    before performing a destructive, sale, salvage, deposit, or withdrawal action.
    """

    item_id: int
    model_id: int
    name: str
    quantity: int
    value: int
    item_type_id: int
    item_type_name: str
    rarity: str
    identified: bool
    salvageable: bool
    is_customized: bool
    is_inscribable: bool
    is_material: bool
    is_rare_material: bool
    is_weapon_like: bool
    is_armor_piece: bool
    is_id_kit: bool = False
    is_salvage_kit: bool = False
    is_stackable: bool = False
    is_tome: bool = False
    requirement: int = 0
    requirement_attribute_id: int = 0
    requirement_attribute_name: str = ""
    damage_min: int = 0
    damage_max: int = 0
    energy: int = 0
    armor: int = 0
    standalone_kind: str = ""
    rune_identifiers: list[str] = field(default_factory=list)
    weapon_mod_identifiers: list[str] = field(default_factory=list)
    weapon_mod_matches: list["ParsedUpgradeMatch"] = field(default_factory=list)
    raw_modifiers: tuple[tuple[int, int, int], ...] = field(default_factory=tuple)
    armor_upgrade_identifiers: list[str] = field(default_factory=list)
    armor_upgrade_matches: list["ArmorUpgradeIdentity"] = field(default_factory=list)
    armor_upgrade_parse_error: str = ""


@dataclass(frozen=True)
class ArmorUpgradeIdentity:
    """Bind one exact runes.json armor identity to its named salvage-option control."""

    identifier: str
    name: str
    semantic_kind: str
    option: str
    signature: tuple[tuple[int, int, int], ...]
    generic_carrier_upgrade_id: int | None = None


@dataclass(frozen=True)
class ArmorUpgradeLinkage:
    """Bind one ordered auxiliary UpgradeRune carrier to its exact Rune identity."""

    upgrade_identifier: str
    option: str
    carrier: tuple[int, int, int]
    attribute_property: tuple[int, int, int]


@dataclass(frozen=True)
class ArmorUpgradeParseState:
    """Cache strict semantic armor identities together with a fail-closed parse reason."""

    upgrades: tuple[ArmorUpgradeIdentity, ...] = ()
    linkages: tuple[ArmorUpgradeLinkage, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class ArmorUpgradeSnapshot:
    """Hold one revalidatable carried-armor identity for a permanent extraction transaction."""

    item_id: int
    model_id: int
    item_type_id: int
    name: str
    raw_modifiers: tuple[tuple[int, int, int], ...]
    upgrades: tuple[ArmorUpgradeIdentity, ...]
    linkages: tuple[ArmorUpgradeLinkage, ...] = ()


@dataclass(frozen=True)
class ParsedInventoryModifiers:
    """Cache normalized equipment requirements, base stats, runes, and exact upgrade matches."""

    requirement: int = 0
    requirement_attribute_id: int = 0
    requirement_attribute_name: str = ""
    damage_min: int = 0
    damage_max: int = 0
    energy: int = 0
    armor: int = 0
    standalone_kind: str = ""
    rune_identifiers: tuple[str, ...] = field(default_factory=tuple)
    weapon_mod_identifiers: tuple[str, ...] = field(default_factory=tuple)
    weapon_mod_matches: tuple[ParsedUpgradeMatch, ...] = field(default_factory=tuple)
    raw_modifiers: tuple[tuple[int, int, int], ...] = field(default_factory=tuple)
    armor_upgrade_identifiers: tuple[str, ...] = field(default_factory=tuple)
    armor_upgrade_matches: tuple[ArmorUpgradeIdentity, ...] = field(default_factory=tuple)
    armor_upgrade_parse_error: str = ""


@dataclass
class InventoryModifierCacheEntry:
    signature: tuple[object, ...]
    parsed: ParsedInventoryModifiers


def _get_stripped_modifier_identifier(raw_identifier: object) -> int:
    return (_safe_int(raw_identifier, 0) >> 4) & 0x3FF


def extract_base_stats_from_raw_modifiers(raw_modifiers: object) -> tuple[int, int, str, int, int, int, int]:
    requirement = 0
    requirement_attribute_id = 0
    requirement_attribute_name = ""
    damage_min = 0
    damage_max = 0
    energy = 0
    armor = 0

    for raw_modifier in raw_modifiers or ():
        try:
            identifier, arg1, arg2 = raw_modifier
        except Exception:
            continue
        stripped_identifier = _get_stripped_modifier_identifier(identifier)
        safe_arg1 = _safe_int(arg1, 0)
        safe_arg2 = _safe_int(arg2, 0)
        if stripped_identifier == MODIFIER_IDENTIFIER_ATTRIBUTE_REQUIREMENT:
            requirement_attribute_id = safe_arg1
            requirement = _normalize_weapon_requirement_level(safe_arg2)
        elif stripped_identifier in (MODIFIER_IDENTIFIER_DAMAGE, MODIFIER_IDENTIFIER_DAMAGE_NO_REQ):
            damage_min = max(0, safe_arg2)
            damage_max = max(0, safe_arg1)
        elif stripped_identifier in (MODIFIER_IDENTIFIER_ARMOR1, MODIFIER_IDENTIFIER_ARMOR2):
            armor = max(0, safe_arg1)
        elif stripped_identifier in (MODIFIER_IDENTIFIER_ENERGY, MODIFIER_IDENTIFIER_ENERGY2):
            energy = max(0, safe_arg1)

    return (
        requirement,
        requirement_attribute_id,
        requirement_attribute_name,
        damage_min,
        damage_max,
        energy,
        armor,
    )


def format_requirement_attribute_value(attribute: object, *, attribute_labels: Mapping[str, str]) -> tuple[int, str]:
    if attribute is None:
        return 0, ""
    try:
        attribute_id = int(attribute)
    except Exception:
        attribute_id = _safe_int(getattr(attribute, "value", 0), 0)
    raw_name = str(getattr(attribute, "name", "") or "").strip()
    if raw_name in ("", "None_"):
        return attribute_id, "" if raw_name != "None_" else "None"

    label = attribute_labels.get(raw_name, raw_name)
    if label == raw_name:
        label = re.sub(r"(?<!^)(?=[A-Z])", " ", raw_name).replace("_", " ").strip()
    return attribute_id, label


def get_armor_upgrade_catalog_identity(
    identifier: object, *, mod_db: "ModDatabase"
) -> tuple[ArmorUpgradeIdentity | None, str]:
    """Return one validated fixed runes.json identity without consulting Item.Mods UIDs."""

    safe_identifier = str(identifier or "").strip()
    if not safe_identifier:
        return None, "empty armor-upgrade catalog identifier"
    if safe_identifier.casefold() in ARMOR_UPGRADE_HOLDING_NAMES:
        return None, f"{safe_identifier} is a container upgrade"

    rune = getattr(mod_db, "runes", {}).get(safe_identifier)
    if rune is None:
        return None, f"unknown runes.json identifier {safe_identifier}"
    name = str(getattr(rune, "name", "") or safe_identifier).strip()
    if not name:
        return None, f"{safe_identifier} has an empty catalog name"
    if name.casefold() in ARMOR_UPGRADE_HOLDING_NAMES:
        return None, f"{name} is a container upgrade"

    mod_type = getattr(rune, "mod_type", None)
    mod_type_name = str(getattr(mod_type, "name", mod_type) or "")
    if mod_type_name == "Prefix":
        semantic_kind = "Insignia"
        option = SALVAGE_OPTION_PREFIX
    elif mod_type_name == "Suffix":
        semantic_kind = "Rune"
        option = SALVAGE_OPTION_SUFFIX
    else:
        return None, f"{name} has unsupported catalog type {mod_type_name or 'unknown'}"
    if semantic_kind.casefold() not in name.casefold():
        return None, f"{name} conflicts with its catalog semantic type {semantic_kind}"

    signature: list[tuple[int, int, int]] = []
    for modifier in list(getattr(rune, "modifiers", []) or []):
        value_arg = getattr(modifier, "modifier_value_arg", None)
        value_arg_name = str(getattr(value_arg, "name", value_arg) or "")
        if value_arg_name != "Fixed":
            return None, f"{name} has a non-fixed or malformed catalog signature"
        triple = (
            int(getattr(modifier, "identifier", 0)),
            int(getattr(modifier, "arg1", 0)),
            int(getattr(modifier, "arg2", 0)),
        )
        if triple in signature:
            return None, f"{name} has a duplicate catalog signature triple"
        signature.append(triple)
    if not signature:
        return None, f"{name} has an empty catalog signature"

    generic_carrier_upgrade_id: int | None = None
    if (
        semantic_kind == "Rune"
        and safe_identifier.casefold() != SUPERIOR_SPAWNING_RUNE_CATALOG_IDENTIFIER.casefold()
        and name.casefold() != SUPERIOR_SPAWNING_RUNE_CATALOG_IDENTIFIER.casefold()
        and not any(_get_stripped_modifier_identifier(triple[0]) == MODIFIER_IDENTIFIER_UPGRADE for triple in signature)
    ):
        generic_carrier_upgrade_id, carrier_error = _get_armor_rune_generic_carrier_upgrade_id(
            safe_identifier,
            name,
        )
        if carrier_error:
            return None, carrier_error

    return (
        ArmorUpgradeIdentity(
            identifier=safe_identifier,
            name=name,
            semantic_kind=semantic_kind,
            option=option,
            signature=tuple(signature),
            generic_carrier_upgrade_id=generic_carrier_upgrade_id,
        ),
        "",
    )


def _is_tooltip_description_modifier(triple: tuple[int, int, int]) -> bool:
    return _get_stripped_modifier_identifier(triple[0]) == MODIFIER_IDENTIFIER_TOOLTIP_DESCRIPTION


def _get_modifier_upgrade_id(triple: tuple[int, int, int]) -> int:
    return (int(triple[1]) << 8) | int(triple[2])


def get_armor_upgrade_generic_carrier_triples(
    raw_modifiers: tuple[tuple[int, int, int], ...],
    upgrade_id: int | None,
) -> tuple[tuple[int, int, int], ...]:
    if upgrade_id is None:
        return ()
    return tuple(
        triple
        for triple in raw_modifiers
        if _get_stripped_modifier_identifier(triple[0]) == MODIFIER_IDENTIFIER_UPGRADE
        and _get_modifier_upgrade_id(triple) == int(upgrade_id)
    )


def _is_armor_upgrade_carrier_triple(triple: tuple[int, int, int]) -> bool:
    stripped_identifier = _get_stripped_modifier_identifier(triple[0])
    return bool(
        stripped_identifier
        in {
            MODIFIER_IDENTIFIER_UPGRADE,
            MODIFIER_IDENTIFIER_ATTRIBUTE_RUNE,
        }
        or int(triple[0]) == MODIFIER_IDENTIFIER_RUNE_HEALTH_LOSS
    )


def has_superior_ritualist_rune_carrier(
    raw_modifiers: tuple[tuple[int, int, int], ...],
) -> bool:
    if SUPERIOR_RITUALIST_RUNE_CARRIER_ID not in ARMOR_UPGRADE_RUNE_CARRIER_IDS:
        return False
    return any(
        _get_stripped_modifier_identifier(triple[0]) == MODIFIER_IDENTIFIER_UPGRADE
        and _get_modifier_upgrade_id(triple) == SUPERIOR_RITUALIST_RUNE_CARRIER_ID
        for triple in raw_modifiers
    )


def _normalize_shared_upgrade_name(value: object) -> str:
    without_profession_suffix = re.sub(r"\[[^\]]+\]", "", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", without_profession_suffix.casefold())


def _iter_item_upgrade_metadata_members() -> tuple[tuple[str, object], ...]:
    members = getattr(ItemUpgrade, "__members__", None)
    if members is not None and callable(getattr(members, "items", None)):
        return tuple((str(name), member) for name, member in members.items())
    return tuple(
        (name, getattr(ItemUpgrade, name))
        for name in dir(ItemUpgrade)
        if not name.startswith("_")
        and name not in {"UpgradeRune", "AppliesToRune"}
        and getattr(ItemUpgrade, name, None) is not None
    )


def _get_armor_rune_generic_carrier_upgrade_id(
    identifier: str,
    name: str,
) -> tuple[int | None, str]:
    """Resolve a class Rune's generic armor carrier from existing upgrade metadata."""

    normalized_candidates = {
        _normalize_shared_upgrade_name(identifier),
        _normalize_shared_upgrade_name(name),
    }
    normalized_candidates.discard("")
    metadata_matches: dict[str, object] = {}
    for metadata_name, metadata_member in _iter_item_upgrade_metadata_members():
        if _normalize_shared_upgrade_name(metadata_name) in normalized_candidates:
            metadata_matches[metadata_name] = metadata_member

    normalized_name = _normalize_shared_upgrade_name(name)
    if not metadata_matches:
        if "runeof" in normalized_name and not normalized_name.startswith("runeof"):
            return None, f"{name} has no exact ItemUpgrade Rune metadata"
        return None, ""
    if len(metadata_matches) != 1:
        return None, f"{name} has ambiguous exact ItemUpgrade Rune metadata"

    metadata_name = next(iter(metadata_matches))
    rune_of_index = metadata_name.find("RuneOf")
    if rune_of_index <= 0:
        return None, f"{name} has no class Rune carrier metadata"
    profession = metadata_name[:rune_of_index]
    effect_name = metadata_name[rune_of_index + len("RuneOf") :]
    tiers = tuple(tier for tier in ("Minor", "Major", "Superior") if effect_name.startswith(tier))
    if len(tiers) != 1:
        return None, f"{name} has no unique Rune tier in ItemUpgrade metadata"

    generic_name = f"{tiers[0]}{profession}Rune"
    generic_member = getattr(ItemUpgradeId, generic_name, None)
    if generic_member is None:
        return None, f"{name} has no ItemUpgradeId.{generic_name} carrier metadata"
    try:
        generic_carrier_upgrade_id = int(generic_member)
    except (TypeError, ValueError):
        return None, f"{name} has a malformed ItemUpgradeId.{generic_name} carrier"
    if generic_carrier_upgrade_id not in ARMOR_UPGRADE_RUNE_CARRIER_IDS:
        return None, f"{name} has an unsupported ItemUpgradeId.{generic_name} carrier"
    return generic_carrier_upgrade_id, ""


def _shared_upgrades_corroborate_named_suffix(
    shared_upgrades: object | None,
    identity: ArmorUpgradeIdentity,
    *,
    read_error: str = "",
) -> tuple[bool, str]:
    if shared_upgrades is None:
        return False, f"Item.Mods.GetUpgrades corroboration unavailable: {read_error or 'no result'}"

    suffix_names: list[str] = []
    try:
        rows = list(shared_upgrades)
    except Exception as exc:
        return False, f"Item.Mods.GetUpgrades corroboration is malformed: {exc}"
    for row in rows:
        try:
            name, slot = row
        except Exception:
            return False, "Item.Mods.GetUpgrades returned a malformed upgrade entry"
        slot_name = str(getattr(slot, "name", slot) or "").strip().casefold()
        if slot_name == "suffix":
            suffix_names.append(_normalize_shared_upgrade_name(name))

    expected_name = _normalize_shared_upgrade_name(identity.name)
    if suffix_names != [expected_name]:
        return (
            False,
            "Item.Mods.GetUpgrades did not corroborate exactly one expected named Suffix "
            f"({identity.name}); observed={suffix_names!r}",
        )
    return True, ""


def read_item_mods_upgrades(item_id: int) -> tuple[tuple[object, ...] | None, str]:
    try:
        from Py4GWCoreLib.Item import Item

        return tuple(Item.Mods.GetUpgrades(int(item_id)) or ()), ""
    except Exception as exc:
        return None, str(exc)


def parse_exact_armor_upgrade_state(
    raw_modifiers: tuple[tuple[int, int, int], ...],
    parse_item_type: ItemType,
    model_id: int,
    *,
    mod_db: "ModDatabase",
    mod_db_load_error: str,
    parser: ModifierParser,
    parsed_modifiers: object | None = None,
    corroborating_upgrades: object | None = None,
    corroborating_upgrades_error: str = "",
) -> ArmorUpgradeParseState:
    """Parse installed armor upgrades by exact full runes.json signatures and fail closed."""

    try:
        safe_raw_modifiers = tuple((int(identifier), int(arg1), int(arg2)) for identifier, arg1, arg2 in raw_modifiers)
    except (TypeError, ValueError):
        return ArmorUpgradeParseState(error="malformed raw modifier tuple is unsupported")
    if mod_db_load_error or not getattr(mod_db, "runes", None):
        return ArmorUpgradeParseState(error=mod_db_load_error or "runes.json catalog is unavailable")
    raw_modifier_counts = Counter(safe_raw_modifiers)
    unsupported_duplicates = [
        (triple, count)
        for triple, count in raw_modifier_counts.items()
        if count > 1 and not _is_tooltip_description_modifier(triple)
    ]
    if unsupported_duplicates:
        formatted = ", ".join(
            f"({identifier},{arg1},{arg2}) x{count}" for (identifier, arg1, arg2), count in unsupported_duplicates
        )
        return ArmorUpgradeParseState(error=f"duplicate non-Tooltip raw modifier triples are unsupported: {formatted}")
    if ARMOR_UPGRADE_ALT_MINOR_VIGOR_SIGNATURE in safe_raw_modifiers:
        return ArmorUpgradeParseState(error="alternate Minor Vigor carrier 0x00C2 is intentionally unsupported")

    if parsed_modifiers is None:
        try:
            parsed_modifiers = parser(
                list(safe_raw_modifiers),
                parse_item_type,
                int(model_id),
                mod_db,
            )
        except Exception as exc:
            return ArmorUpgradeParseState(error=f"runes.json modifier parsing failed: {exc}")

    upgrades: list[ArmorUpgradeIdentity] = []
    linkages: list[ArmorUpgradeLinkage] = []
    consumed_carriers: Counter[tuple[int, int, int]] = Counter()
    seen_identifiers: set[str] = set()
    seen_options: set[str] = set()
    for match in list(getattr(parsed_modifiers, "runes", []) or []):
        rune = getattr(match, "rune", None)
        identifier = str(getattr(rune, "identifier", "") or "").strip()
        identity, identity_error = get_armor_upgrade_catalog_identity(identifier, mod_db=mod_db)
        if identity is None:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error=identity_error or "runes.json returned an invalid armor-upgrade identity",
            )

        match_mod_type = getattr(match, "mod_type", getattr(rune, "mod_type", None))
        match_mod_type_name = str(getattr(match_mod_type, "name", match_mod_type) or "")
        expected_mod_type_name = "Prefix" if identity.option == SALVAGE_OPTION_PREFIX else "Suffix"
        if match_mod_type_name != expected_mod_type_name:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error=f"{identity.name} parser type conflicts with its catalog identity",
            )
        for triple in identity.signature:
            if raw_modifier_counts[triple] != 1:
                return ArmorUpgradeParseState(
                    upgrades=tuple(upgrades),
                    error=f"{identity.name} does not have one exact full signature on the armor",
                )
            if consumed_carriers[triple] > 0:
                return ArmorUpgradeParseState(
                    upgrades=tuple(upgrades),
                    error=f"{identity.name} shares a signature carrier with another armor upgrade",
                )
        generic_carrier_triples = get_armor_upgrade_generic_carrier_triples(
            safe_raw_modifiers,
            identity.generic_carrier_upgrade_id,
        )
        if identity.generic_carrier_upgrade_id is not None:
            if len(generic_carrier_triples) != 1:
                return ArmorUpgradeParseState(
                    upgrades=tuple(upgrades),
                    error=(
                        f"{identity.name} does not have exactly one authoritative generic Rune carrier "
                        f"for ItemUpgradeId {identity.generic_carrier_upgrade_id}"
                    ),
                )
            generic_carrier = generic_carrier_triples[0]
            if consumed_carriers[generic_carrier] > 0:
                return ArmorUpgradeParseState(
                    upgrades=tuple(upgrades),
                    error=f"{identity.name} shares a signature carrier with another armor upgrade",
                )
        if identity.identifier in seen_identifiers:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error=f"duplicate catalog identity {identity.identifier} is unsupported",
            )
        if identity.option in seen_options:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error=f"multiple conflicting {identity.semantic_kind} identities are unsupported",
            )

        seen_identifiers.add(identity.identifier)
        seen_options.add(identity.option)
        consumed_carriers.update(identity.signature)
        if generic_carrier_triples:
            consumed_carriers[generic_carrier_triples[0]] += 1
        upgrades.append(identity)

    superior_ritualist_carrier_positions = [
        index
        for index, triple in enumerate(safe_raw_modifiers)
        if _get_stripped_modifier_identifier(triple[0]) == MODIFIER_IDENTIFIER_UPGRADE
        and _get_modifier_upgrade_id(triple) == SUPERIOR_RITUALIST_RUNE_CARRIER_ID
    ]
    if superior_ritualist_carrier_positions:
        if SUPERIOR_RITUALIST_RUNE_CARRIER_ID not in ARMOR_UPGRADE_RUNE_CARRIER_IDS:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error="Superior Ritualist Rune carrier is unavailable in ItemUpgrade.UpgradeRune",
            )
        if len(superior_ritualist_carrier_positions) != 1:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error="multiple Superior Ritualist Rune linkage carriers are unsupported",
            )

        spawning_identities = [
            identity
            for identity in upgrades
            if identity.identifier == SUPERIOR_SPAWNING_RUNE_CATALOG_IDENTIFIER
            and identity.option == SALVAGE_OPTION_SUFFIX
        ]
        if len(spawning_identities) != 1:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error="Superior Ritualist Rune carrier is orphaned or mismatched",
            )
        spawning_identity = spawning_identities[0]
        attribute_properties = [
            triple
            for triple in spawning_identity.signature
            if _get_stripped_modifier_identifier(triple[0]) == MODIFIER_IDENTIFIER_ATTRIBUTE_RUNE
        ]
        if len(attribute_properties) != 1:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error="Superior Spawning Rune catalog identity has an invalid AttributeRune property",
            )

        carrier_index = superior_ritualist_carrier_positions[0]
        carrier = safe_raw_modifiers[carrier_index]
        if raw_modifier_counts[carrier] != 1:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error="Superior Ritualist Rune linkage carrier is not singular",
            )
        linked_property: tuple[int, int, int] | None = None
        for following in safe_raw_modifiers[carrier_index + 1 :]:
            if _is_tooltip_description_modifier(following):
                continue
            linked_property = following
            break
        expected_property = attribute_properties[0]
        if linked_property != expected_property:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error=(
                    "Superior Ritualist Rune linkage carrier is reordered, interrupted, "
                    "or does not precede Superior Spawning"
                ),
            )
        corroborated, corroboration_error = _shared_upgrades_corroborate_named_suffix(
            corroborating_upgrades,
            spawning_identity,
            read_error=corroborating_upgrades_error,
        )
        if not corroborated:
            return ArmorUpgradeParseState(
                upgrades=tuple(upgrades),
                error=corroboration_error,
            )

        consumed_carriers[carrier] += 1
        linkages.append(
            ArmorUpgradeLinkage(
                upgrade_identifier=spawning_identity.identifier,
                option=spawning_identity.option,
                carrier=carrier,
                attribute_property=expected_property,
            )
        )

    remaining_carriers = consumed_carriers.copy()
    unknown_rune_triples: list[tuple[int, int, int]] = []
    for triple in safe_raw_modifiers:
        if not _is_armor_upgrade_carrier_triple(triple):
            continue
        if remaining_carriers[triple] > 0:
            remaining_carriers[triple] -= 1
            continue
        unknown_rune_triples.append(triple)
    if unknown_rune_triples:
        formatted = ", ".join(f"({identifier},{arg1},{arg2})" for identifier, arg1, arg2 in unknown_rune_triples)
        return ArmorUpgradeParseState(
            upgrades=tuple(upgrades),
            error=f"unknown or malformed Rune/Insignia carrier signature: {formatted}",
        )
    if len(upgrades) > 2:
        return ArmorUpgradeParseState(
            upgrades=tuple(upgrades),
            error="more than two armor-upgrade identities were parsed",
        )

    upgrades.sort(key=lambda upgrade: (upgrade.option, upgrade.identifier.casefold()))
    linkages.sort(key=lambda linkage: (linkage.option, linkage.upgrade_identifier.casefold()))
    return ArmorUpgradeParseState(upgrades=tuple(upgrades), linkages=tuple(linkages))


def armor_upgrade_signature_is_exactly_present(
    raw_modifiers: tuple[tuple[int, int, int], ...],
    identity: ArmorUpgradeIdentity,
    *,
    require_generic_carrier: bool = False,
) -> bool:
    """Recognize an exact selected target even when another armor identity forces a safe block."""

    if not bool(identity.signature and all(raw_modifiers.count(triple) == 1 for triple in identity.signature)):
        return False
    if not require_generic_carrier or identity.generic_carrier_upgrade_id is None:
        return True
    return (
        len(
            get_armor_upgrade_generic_carrier_triples(
                raw_modifiers,
                identity.generic_carrier_upgrade_id,
            )
        )
        == 1
    )


class InventoryEvidence:
    """Own one widget's observations, modifier cache, and snapshot statistics."""

    def __init__(
        self,
        *,
        mod_db: "ModDatabase",
        mod_db_load_error: str,
        parse_modifiers: ModifierParser,
        inventory_bag_ids: tuple[int, ...],
        material_storage_bag_id: int,
        weapon_like_item_types: frozenset[ItemType],
        armor_piece_types: frozenset[ItemType],
        id_kit_model_ids: tuple[int, ...],
        salvage_kit_model_ids: tuple[int, ...],
        rune_standalone_kind: str,
        weapon_mod_standalone_kind: str,
        attribute_labels: Mapping[str, str],
    ) -> None:
        self._mod_db = mod_db
        self._mod_db_load_error = mod_db_load_error
        self._parse_modifiers = parse_modifiers
        self._inventory_bag_ids = inventory_bag_ids
        self._material_storage_bag_id = material_storage_bag_id
        self._weapon_like_item_types = weapon_like_item_types
        self._armor_piece_types = armor_piece_types
        self._id_kit_model_ids = id_kit_model_ids
        self._salvage_kit_model_ids = salvage_kit_model_ids
        self._rune_standalone_kind = rune_standalone_kind
        self._weapon_mod_standalone_kind = weapon_mod_standalone_kind
        self._attribute_labels = attribute_labels
        self._modifier_cache: dict[int, InventoryModifierCacheEntry] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._last_inventory_snapshot_duration_ms = 0.0

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses

    @property
    def cache_entry_count(self) -> int:
        return len(self._modifier_cache)

    @property
    def cache_hit_rate(self) -> float:
        total_lookups = max(0, int(self._cache_hits) + int(self._cache_misses))
        if total_lookups <= 0:
            return 0.0
        return (float(self._cache_hits) / float(total_lookups)) * 100.0

    @property
    def last_inventory_snapshot_duration_ms(self) -> float:
        return self._last_inventory_snapshot_duration_ms

    def invalidate(self, item_id: int) -> None:
        self._modifier_cache.pop(item_id, None)

    def clear_entries(self) -> None:
        self._modifier_cache.clear()

    def reset_statistics(self) -> None:
        self._cache_hits = 0
        self._cache_misses = 0
        self._last_inventory_snapshot_duration_ms = 0.0

    def get_bag_item_ids(self, bag_ids: tuple[int, ...] | list[int]) -> list[int]:
        normalized_bag_ids = tuple(int(bag_id) for bag_id in bag_ids if max(0, _safe_int(bag_id, 0)) > 0)
        if not normalized_bag_ids:
            return []
        bag_list = GLOBAL_CACHE.ItemArray.CreateBagList(*normalized_bag_ids)
        return [int(item_id) for item_id in GLOBAL_CACHE.ItemArray.GetItemArray(bag_list)]

    def get_inventory_item_ids(self) -> list[int]:
        return self.get_bag_item_ids(list(self._inventory_bag_ids))

    def is_storage_open(self) -> bool:
        storage_api = getattr(GLOBAL_CACHE, "Inventory", None)
        if storage_api is None:
            return False
        try:
            return bool(getattr(storage_api, "IsStorageOpen", lambda: False)())
        except Exception:
            return False

    def _get_storage_item_ids(self) -> list[int]:
        if not self.is_storage_open():
            return []
        return self.get_bag_item_ids(list(range(8, 22)))

    def get_item_modifier_values(self, item_id: int) -> tuple[tuple[int, int, int], ...]:
        return tuple(
            (int(modifier.GetIdentifier()), int(modifier.GetArg1()), int(modifier.GetArg2()))
            for modifier in GLOBAL_CACHE.Item.Mods.GetModifiers(item_id)
            if modifier is not None
        )

    def classify_inventory_item_type(self, item_id: int, item_type_enum: ItemType) -> tuple[bool, bool, ItemType]:
        is_weapon_like = bool(item_type_enum in self._weapon_like_item_types)
        is_armor_piece = bool(GLOBAL_CACHE.Item.Type.IsArmor(item_id) or item_type_enum in self._armor_piece_types)
        parse_item_type = item_type_enum
        if is_armor_piece and parse_item_type not in self._armor_piece_types:
            parse_item_type = ItemType.Chestpiece
        return is_weapon_like, is_armor_piece, parse_item_type

    def _get_cached_inventory_modifiers(
        self,
        item_id: int,
        model_id: int,
        item_type_enum: ItemType,
        parse_item_type: ItemType,
        *,
        is_weapon_like: bool,
        is_armor_piece: bool,
    ) -> ParsedInventoryModifiers:
        if not (is_weapon_like or is_armor_piece or item_type_enum == ItemType.Rune_Mod):
            return ParsedInventoryModifiers()

        raw_modifiers = self.get_item_modifier_values(item_id)
        signature = (
            int(model_id),
            int(getattr(item_type_enum, "value", 0)),
            int(getattr(parse_item_type, "value", 0)),
            raw_modifiers,
        )
        cached_entry = self._modifier_cache.get(item_id)
        if cached_entry is not None and cached_entry.signature == signature:
            self._cache_hits += 1
            return cached_entry.parsed

        self._cache_misses += 1
        parsed_state = ParsedInventoryModifiers()
        (
            raw_requirement,
            raw_requirement_attribute_id,
            raw_requirement_attribute_name,
            raw_damage_min,
            raw_damage_max,
            raw_energy,
            raw_armor,
        ) = extract_base_stats_from_raw_modifiers(raw_modifiers)
        if raw_modifiers:
            try:
                parsed_modifiers = self._parse_modifiers(
                    list(raw_modifiers),
                    parse_item_type,
                    model_id,
                    self._mod_db,
                )
            except Exception as exc:
                if not is_armor_piece:
                    raise
                parsed_state = ParsedInventoryModifiers(
                    requirement=raw_requirement,
                    requirement_attribute_id=raw_requirement_attribute_id,
                    requirement_attribute_name=raw_requirement_attribute_name,
                    damage_min=raw_damage_min,
                    damage_max=raw_damage_max,
                    energy=raw_energy,
                    armor=raw_armor,
                    raw_modifiers=raw_modifiers,
                    armor_upgrade_parse_error=f"runes.json modifier parsing failed: {exc}",
                )
                self._modifier_cache[item_id] = InventoryModifierCacheEntry(
                    signature=signature,
                    parsed=parsed_state,
                )
                return parsed_state
            corroborating_upgrades: tuple[object, ...] | None = None
            corroborating_upgrades_error = ""
            if is_armor_piece and has_superior_ritualist_rune_carrier(raw_modifiers):
                corroborating_upgrades, corroborating_upgrades_error = read_item_mods_upgrades(item_id)
            armor_upgrade_state = (
                parse_exact_armor_upgrade_state(
                    raw_modifiers,
                    parse_item_type,
                    model_id,
                    mod_db=self._mod_db,
                    mod_db_load_error=self._mod_db_load_error,
                    parser=self._parse_modifiers,
                    parsed_modifiers=parsed_modifiers,
                    corroborating_upgrades=corroborating_upgrades,
                    corroborating_upgrades_error=corroborating_upgrades_error,
                )
                if is_armor_piece
                else ArmorUpgradeParseState()
            )
            rune_identifiers = tuple(_dedupe_identifiers([match.rune.identifier for match in parsed_modifiers.runes]))
            weapon_mod_identifier_values = [match.weapon_mod.identifier for match in parsed_modifiers.weapon_mods]
            if getattr(parsed_modifiers, "has_increased_value", False):
                weapon_mod_identifier_values.append('"Show me the money!"')
            if getattr(parsed_modifiers, "is_highly_salvageable", False):
                weapon_mod_identifier_values.append('"Measure for Measure"')
            weapon_mod_identifiers = tuple(_dedupe_identifiers(weapon_mod_identifier_values))
            weapon_mod_matches = tuple(
                parsed_match
                for parsed_match in (
                    build_parsed_weapon_mod_match(
                        match,
                        raw_modifiers=raw_modifiers,
                        item_type_enum=item_type_enum,
                        parse_item_type=parse_item_type,
                    )
                    for match in parsed_modifiers.weapon_mods
                )
                if parsed_match is not None
            )
            standalone_kind = ""
            if item_type_enum == ItemType.Rune_Mod:
                if parsed_modifiers.is_rune or rune_identifiers:
                    standalone_kind = self._rune_standalone_kind
                elif weapon_mod_identifiers:
                    standalone_kind = self._weapon_mod_standalone_kind
            damage = getattr(parsed_modifiers, "damage", (0, 0)) or (0, 0)
            try:
                parsed_damage_min, parsed_damage_max = damage
            except Exception:
                parsed_damage_min, parsed_damage_max = 0, 0
            shield_armor = getattr(parsed_modifiers, "shield_armor", (0, 0)) or (0, 0)
            try:
                parsed_armor, _parsed_armor_secondary = shield_armor
            except Exception:
                parsed_armor = 0
            parsed_requirement = _normalize_weapon_requirement_level(getattr(parsed_modifiers, "requirements", 0))
            parsed_attribute_id, parsed_attribute_name = format_requirement_attribute_value(
                getattr(parsed_modifiers, "attribute", None),
                attribute_labels=self._attribute_labels,
            )
            parsed_state = ParsedInventoryModifiers(
                requirement=parsed_requirement or raw_requirement,
                requirement_attribute_id=parsed_attribute_id or raw_requirement_attribute_id,
                requirement_attribute_name=parsed_attribute_name or raw_requirement_attribute_name,
                damage_min=max(0, _safe_int(parsed_damage_min, 0) or raw_damage_min),
                damage_max=max(0, _safe_int(parsed_damage_max, 0) or raw_damage_max),
                energy=max(0, raw_energy),
                armor=max(0, _safe_int(parsed_armor, 0) or raw_armor),
                standalone_kind=standalone_kind,
                rune_identifiers=rune_identifiers,
                weapon_mod_identifiers=weapon_mod_identifiers,
                weapon_mod_matches=weapon_mod_matches,
                raw_modifiers=raw_modifiers,
                armor_upgrade_identifiers=tuple(upgrade.identifier for upgrade in armor_upgrade_state.upgrades),
                armor_upgrade_matches=armor_upgrade_state.upgrades,
                armor_upgrade_parse_error=str(armor_upgrade_state.error or ""),
            )
        elif any((raw_requirement, raw_damage_min, raw_damage_max, raw_energy, raw_armor)):
            parsed_state = ParsedInventoryModifiers(
                requirement=raw_requirement,
                requirement_attribute_id=raw_requirement_attribute_id,
                requirement_attribute_name=raw_requirement_attribute_name,
                damage_min=raw_damage_min,
                damage_max=raw_damage_max,
                energy=raw_energy,
                armor=raw_armor,
                raw_modifiers=raw_modifiers,
            )

        self._modifier_cache[item_id] = InventoryModifierCacheEntry(
            signature=signature,
            parsed=parsed_state,
        )
        return parsed_state

    def build_inventory_item_info(
        self,
        item_id: int,
        *,
        include_runtime_name: bool = True,
    ) -> InventoryItemInfo | None:
        """Read and normalize one live inventory item for rule matching.

        Missing native data or parsing failures return ``None`` so callers cannot plan from a
        partial item record.
        """

        try:
            safe_item_id = int(item_id)
            model_id = int(GLOBAL_CACHE.Item.GetModelID(safe_item_id))
            quantity = max(1, int(GLOBAL_CACHE.Item.Properties.GetQuantity(safe_item_id)))
            value = max(0, int(GLOBAL_CACHE.Item.Properties.GetValue(safe_item_id)))
            item_type_id, item_type_name = GLOBAL_CACHE.Item.GetItemType(safe_item_id)
            try:
                item_type_enum = ItemType(int(item_type_id))
            except Exception:
                item_type_enum = ItemType.Unknown
            _, rarity = GLOBAL_CACHE.Item.Rarity.GetRarity(safe_item_id)
            is_weapon_like, is_armor_piece, parse_item_type = self.classify_inventory_item_type(
                safe_item_id, item_type_enum
            )
            parsed_modifiers = self._get_cached_inventory_modifiers(
                safe_item_id,
                model_id,
                item_type_enum,
                parse_item_type,
                is_weapon_like=is_weapon_like,
                is_armor_piece=is_armor_piece,
            )
            runtime_name = (
                str(GLOBAL_CACHE.Item.GetName(safe_item_id) or f"Model {model_id}")
                if include_runtime_name
                else f"Model {model_id}"
            )
            return InventoryItemInfo(
                item_id=safe_item_id,
                model_id=model_id,
                name=runtime_name,
                quantity=quantity,
                value=value,
                item_type_id=int(item_type_id),
                item_type_name=str(item_type_name or ""),
                rarity=str(rarity or ""),
                identified=bool(GLOBAL_CACHE.Item.Usage.IsIdentified(safe_item_id)),
                salvageable=bool(GLOBAL_CACHE.Item.Usage.IsSalvageable(safe_item_id)),
                is_customized=bool(GLOBAL_CACHE.Item.Properties.IsCustomized(safe_item_id)),
                is_inscribable=bool(GLOBAL_CACHE.Item.Properties.IsInscribable(safe_item_id)),
                is_material=bool(GLOBAL_CACHE.Item.Type.IsMaterial(safe_item_id)),
                is_rare_material=bool(GLOBAL_CACHE.Item.Type.IsRareMaterial(safe_item_id)),
                is_weapon_like=is_weapon_like,
                is_armor_piece=is_armor_piece,
                is_id_kit=bool(
                    getattr(
                        getattr(GLOBAL_CACHE.Item, "Usage", None),
                        "IsIDKit",
                        lambda _item_id: model_id in self._id_kit_model_ids,
                    )(safe_item_id)
                ),
                is_salvage_kit=bool(
                    getattr(
                        getattr(GLOBAL_CACHE.Item, "Usage", None),
                        "IsSalvageKit",
                        lambda _item_id: model_id in self._salvage_kit_model_ids,
                    )(safe_item_id)
                ),
                is_stackable=bool(
                    getattr(
                        getattr(GLOBAL_CACHE.Item, "Customization", None),
                        "IsStackable",
                        lambda _item_id: quantity > 1,
                    )(safe_item_id)
                ),
                is_tome=bool(
                    getattr(
                        getattr(GLOBAL_CACHE.Item, "Type", None),
                        "IsTome",
                        lambda _item_id: False,
                    )(safe_item_id)
                ),
                requirement=int(parsed_modifiers.requirement),
                requirement_attribute_id=int(parsed_modifiers.requirement_attribute_id),
                requirement_attribute_name=str(parsed_modifiers.requirement_attribute_name or ""),
                damage_min=int(parsed_modifiers.damage_min),
                damage_max=int(parsed_modifiers.damage_max),
                energy=int(parsed_modifiers.energy),
                armor=int(parsed_modifiers.armor),
                standalone_kind=str(parsed_modifiers.standalone_kind or ""),
                rune_identifiers=list(parsed_modifiers.rune_identifiers),
                weapon_mod_identifiers=list(parsed_modifiers.weapon_mod_identifiers),
                weapon_mod_matches=list(parsed_modifiers.weapon_mod_matches),
                raw_modifiers=tuple(parsed_modifiers.raw_modifiers),
                armor_upgrade_identifiers=list(parsed_modifiers.armor_upgrade_identifiers),
                armor_upgrade_matches=list(parsed_modifiers.armor_upgrade_matches),
                armor_upgrade_parse_error=str(parsed_modifiers.armor_upgrade_parse_error or ""),
            )
        except Exception:
            return None

    def prune(self, active_item_ids: set[int]) -> None:
        stale_item_ids = [item_id for item_id in self._modifier_cache.keys() if item_id not in active_item_ids]
        for stale_item_id in stale_item_ids:
            self._modifier_cache.pop(stale_item_id, None)

    def _collect_item_infos_from_ids(self, item_ids: list[int]) -> list[InventoryItemInfo]:
        items: list[InventoryItemInfo] = []
        for item_id in item_ids:
            item_info = self.build_inventory_item_info(item_id)
            if item_info is None:
                continue
            items.append(item_info)
        return items

    def collect_inventory_items(self) -> list[InventoryItemInfo]:
        started_at = time.perf_counter()
        items = self._collect_item_infos_from_ids(self.get_inventory_item_ids())
        active_item_ids = {int(item.item_id) for item in items if int(item.item_id) > 0}
        self.prune(active_item_ids)
        self._last_inventory_snapshot_duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        return items

    def collect_storage_items(self) -> list[InventoryItemInfo]:
        if not self.is_storage_open():
            return []
        return self._collect_item_infos_from_ids(self._get_storage_item_ids())

    def collect_storage_items_with_reliability(self) -> tuple[list[InventoryItemInfo], bool]:
        """Collect regular Xunlai panes and report whether every listed item was readable."""

        if not self.is_storage_open():
            return [], False
        item_ids = self._get_storage_item_ids()
        items = self._collect_item_infos_from_ids(item_ids)
        return items, len(items) == len(item_ids)

    def collect_material_storage_items(self) -> list[InventoryItemInfo]:
        if not self.is_storage_open():
            return []
        return self._collect_item_infos_from_ids(self.get_bag_item_ids((self._material_storage_bag_id,)))
