"""Loot persistence split by lifetime: global policy and session-only live state.

The global Loot Policy, including the selected Factory filter set, is shared by every account.
``LootFilters.live`` remains in memory and is never written here.
"""

from datetime import date

from .nicholas import NicholasSelection
from .model import LootConfig


_POLICY_INI = "Widgets/System/LootFilters.ini"
_POLICY_SELECTIONS = "Widgets/System/LootFiltersSelections.json"

_QA_SEPARATOR = "|"
DEFAULT_QUICK_ACCESS: tuple[str, ...] = ("Rarities", "Materials", "Dyes", "Nicholas")


def _log(message: str) -> None:
    try:
        from Py4GWCoreLib.Py4GWcorelib import ConsoleLog

        ConsoleLog("Loot Filters", message)
    except Exception:
        pass


def _settings(scope: str):
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        return Settings(_POLICY_INI, scope)
    except Exception:
        return None


def _json(scope: str):
    try:
        from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

        return JsonFactory(_POLICY_SELECTIONS, scope)
    except Exception:
        return None


def _load_policy(settings, doc) -> LootConfig:
    config = LootConfig()
    if settings is not None:
        config.enabled = settings.get_bool("general", "enabled", True)
        config.respect_loot_lock = settings.get_bool("general", "respect_loot_lock", True)
        # The persisted key has always been ``general/profile`` and it stays: only the VALUE
        # moved from a filter-set NAME to its id. Names are still read and adopted by load().
        config.filter_set_id = settings.get_str("general", "profile", "")
        for key in ("white", "blue", "purple", "gold", "green", "gold_coins"):
            config.set_rarity(key, settings.get_bool("rarity", key, False))
    if doc is not None:
        config.enabled_model_ids = {int(v) for v in doc.get_json("enabled_model_ids", []) or []}
        config.enabled_dye_colors = {int(v) for v in doc.get_json("enabled_dye_colors", []) or []}
        config.salvage_target_ids = {int(v) for v in doc.get_json("salvage_target_ids", []) or []}
        config.added_model_ids = {int(v) for v in doc.get_json("added_model_ids", []) or []}
        config.blacklist_model_ids = {int(v) for v in doc.get_json("blacklist_model_ids", []) or []}
        config.blacklist_item_types = {int(v) for v in doc.get_json("blacklist_item_types", []) or []}
        selections: list[NicholasSelection] = []
        for entry in doc.get_json("nicholas", []) or []:
            if entry in (None, ""):
                selections.append(NicholasSelection(None))
                continue
            try:
                selections.append(NicholasSelection(date.fromisoformat(str(entry))))
            except ValueError:
                continue
        config.nicholas = tuple(selections)
    return config


def _save_policy(config: LootConfig, settings, doc) -> None:
    if settings is not None:
        settings.set("general", "enabled", bool(config.enabled))
        settings.set("general", "respect_loot_lock", bool(config.respect_loot_lock))
        settings.set("general", "profile", str(config.filter_set_id))
        for key in ("white", "blue", "purple", "gold", "green", "gold_coins"):
            settings.set("rarity", key, bool(config.rarity_enabled(key)))
    if doc is not None:
        doc.set_json("enabled_model_ids", sorted(config.enabled_model_ids))
        doc.set_json("enabled_dye_colors", sorted(config.enabled_dye_colors))
        doc.set_json("salvage_target_ids", sorted(config.salvage_target_ids))
        doc.set_json("added_model_ids", sorted(config.added_model_ids))
        doc.set_json("blacklist_model_ids", sorted(config.blacklist_model_ids))
        doc.set_json("blacklist_item_types", sorted(config.blacklist_item_types))
        doc.set_json("nicholas", ["" if s.week is None else s.week.isoformat() for s in config.nicholas])


def _has_configured_policy(config: LootConfig) -> bool:
    """Whether a policy has an intentional choice beyond the empty enabled defaults."""
    return bool(
        not config.enabled
        or not config.respect_loot_lock
        or config.filter_set_id
        or config.loot_whites
        or config.loot_blues
        or config.loot_purples
        or config.loot_golds
        or config.loot_greens
        or config.loot_gold_coins
        or config.enabled_model_ids
        or config.enabled_dye_colors
        or config.salvage_target_ids
        or config.added_model_ids
        or config.blacklist_model_ids
        or config.blacklist_item_types
        or config.nicholas
    )


def _load_legacy_account_policy() -> LootConfig:
    """Read the pre-global account document for a one-way migration only."""
    return _load_policy(_settings("account"), _json("account"))


def _migrate_account_policy(policy_settings, policy_doc) -> None:
    """Copy a legacy account policy into an otherwise untouched global policy."""
    if policy_settings is None:
        return

    global_policy = _load_policy(policy_settings, policy_doc)
    if _has_configured_policy(global_policy):
        return

    account_policy = _load_legacy_account_policy()
    if not _has_configured_policy(account_policy):
        return

    _save_policy(account_policy, policy_settings, policy_doc)
    policy_settings.set("migration", "from_account", True)


def _resolve_filter_set(config: LootConfig, settings) -> None:
    """Adopt a legacy filter-set NAME into its id, in place, once and silently.

    The key does not move: ``general/profile`` still holds the selection, only
    the VALUE changes from a name to the set's id -- which is what makes a
    rename survive. A stored id is kept; a stored name is resolved and written
    back as its id (idempotent: the value being an id is its own migration
    state); a value matching no set falls back to none **in memory** -- the
    document is not rewritten, so a transiently unreadable filter pool cannot
    destroy a valid selection. The console message appears at most once per
    load.
    """
    if not config.filter_set_id:
        return
    from ..loot_filter_factory import store as factory_store

    stored = config.filter_set_id
    selection, message = factory_store.resolve_filter_set_selection(
        stored, factory_store.load_filter_sets())
    config.filter_set_id = selection
    if message:
        _log(message)
    if selection and selection != stored and settings is not None:
        settings.set("general", "profile", selection)


def load() -> LootConfig:
    """Load the global loot policy, copying one legacy account policy when needed."""
    policy_settings, policy_doc = _settings("global"), _json("global")
    _migrate_account_policy(policy_settings, policy_doc)
    config = _load_policy(policy_settings, policy_doc)
    _resolve_filter_set(config, policy_settings)
    return config


def save(config: LootConfig) -> None:
    """Persist the global policy; never persist live state."""
    _save_policy(config, _settings("global"), _json("global"))


# ---------------------------------------------------------------- quick access and layouts (global presentation policy)


def load_quick_access() -> tuple[list[str], str, bool]:
    settings = _settings("global")
    if settings is None:
        return list(DEFAULT_QUICK_ACCESS), "checkbox_list", False
    raw = settings.get_str("quick access", "surfaces", "")
    surfaces = [part for part in raw.split(_QA_SEPARATOR) if part] or list(DEFAULT_QUICK_ACCESS)
    return (surfaces,
            settings.get_str("quick access", "layout", "checkbox_list"),
            settings.get_bool("quick access", "window_open", False))


def save_quick_access(surfaces, layout: str, window_open: bool) -> None:
    settings = _settings("global")
    if settings is not None:
        settings.set("quick access", "surfaces", _QA_SEPARATOR.join(str(surface) for surface in surfaces))
        settings.set("quick access", "layout", str(layout))
        settings.set("quick access", "window_open", bool(window_open))


def load_layout_for(surface: str, default: str) -> str:
    settings = _settings("global")
    return settings.get_str("layouts", surface, default) if settings is not None else default


def save_layout_for(surface: str, layout: str) -> None:
    settings = _settings("global")
    if settings is not None:
        settings.set("layouts", surface, str(layout))
