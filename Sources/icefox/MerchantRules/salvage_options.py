"""Keep persisted salvage modes distinct from internal operations and upgrade slots."""

SALVAGE_OPTION_DEFAULT = "default"
SALVAGE_OPTION_MATERIALS = "materials"
SALVAGE_OPTION_AUTO_UPGRADE = "auto_upgrade"
SALVAGE_OPTION_PREFIX = "prefix"
SALVAGE_OPTION_SUFFIX = "suffix"
SALVAGE_OPTION_INSCRIPTION = "inscription"
# Rule modes are the only values accepted from persisted SalvageRule records.
# Prefix/suffix/inscription remain internal extraction-operation tokens used by
# the current Specific upgrade resolver and execution path.
SALVAGE_RULE_MODE_ORDER: tuple[tuple[str, str], ...] = (
    (SALVAGE_OPTION_MATERIALS, "Materials"),
    (SALVAGE_OPTION_AUTO_UPGRADE, "Specific upgrade"),
)
SALVAGE_RULE_MODE_VALUES: frozenset[str] = frozenset(option for option, _label in SALVAGE_RULE_MODE_ORDER)
SALVAGE_OPERATION_ORDER: tuple[tuple[str, str], ...] = (
    (SALVAGE_OPTION_MATERIALS, "Salvage materials"),
    (SALVAGE_OPTION_AUTO_UPGRADE, "Specific upgrade"),
    (SALVAGE_OPTION_PREFIX, "Salvage prefix"),
    (SALVAGE_OPTION_SUFFIX, "Salvage suffix"),
    (SALVAGE_OPTION_INSCRIPTION, "Salvage inscription"),
)
SALVAGE_OPERATION_VALUES: frozenset[str] = frozenset(option for option, _label in SALVAGE_OPERATION_ORDER)
SALVAGE_OPTION_DROPDOWN_ORDER: tuple[tuple[str, str], ...] = SALVAGE_RULE_MODE_ORDER
SALVAGE_UPGRADE_OPTIONS: frozenset[str] = frozenset(
    {
        SALVAGE_OPTION_PREFIX,
        SALVAGE_OPTION_SUFFIX,
        SALVAGE_OPTION_INSCRIPTION,
    }
)


def canonicalize_salvage_option(raw_option: object) -> str:
    safe_option = str(raw_option or "").strip().lower()
    aliases = {
        "": SALVAGE_OPTION_MATERIALS,
        "current": SALVAGE_OPTION_MATERIALS,
        "default": SALVAGE_OPTION_MATERIALS,
        "default/current behavior": SALVAGE_OPTION_MATERIALS,
        "salvage materials": SALVAGE_OPTION_MATERIALS,
        "material": SALVAGE_OPTION_MATERIALS,
        "auto": SALVAGE_OPTION_AUTO_UPGRADE,
        "auto upgrade": SALVAGE_OPTION_AUTO_UPGRADE,
        "auto exact upgrade": SALVAGE_OPTION_AUTO_UPGRADE,
        "auto exact upgrade slot": SALVAGE_OPTION_AUTO_UPGRADE,
        "automatic exact upgrade slot": SALVAGE_OPTION_AUTO_UPGRADE,
        "specific upgrade": SALVAGE_OPTION_AUTO_UPGRADE,
        "prefix": SALVAGE_OPTION_PREFIX,
        "salvage prefix": SALVAGE_OPTION_PREFIX,
        "suffix": SALVAGE_OPTION_SUFFIX,
        "salvage suffix": SALVAGE_OPTION_SUFFIX,
        "inscription": SALVAGE_OPTION_INSCRIPTION,
        "salvage inscription": SALVAGE_OPTION_INSCRIPTION,
    }
    return aliases.get(safe_option, safe_option)


def normalize_salvage_operation(raw_option: object) -> str:
    safe_option = canonicalize_salvage_option(raw_option)
    return safe_option if safe_option in SALVAGE_OPERATION_VALUES else SALVAGE_OPTION_MATERIALS


def normalize_salvage_rule_mode(raw_option: object) -> str:
    safe_option = canonicalize_salvage_option(raw_option)
    if safe_option in SALVAGE_RULE_MODE_VALUES:
        return safe_option
    raise ValueError(
        f"Unsupported Merchant Rules persisted Salvage rule mode {str(raw_option or '').strip()!r}. "
        "Use Materials or Specific upgrade."
    )


def resolve_salvage_operation(raw_option: object) -> str:
    safe_option = normalize_salvage_operation(raw_option)
    if safe_option == SALVAGE_OPTION_DEFAULT:
        return SALVAGE_OPTION_MATERIALS
    return safe_option


def get_salvage_option_label(raw_option: object) -> str:
    safe_option = normalize_salvage_operation(raw_option)
    for option, label in SALVAGE_OPERATION_ORDER:
        if option == safe_option:
            return label
    return "Salvage materials"


def get_salvage_option_dropdown_label(raw_option: object) -> str:
    safe_option = normalize_salvage_rule_mode(raw_option)
    for option, label in SALVAGE_OPTION_DROPDOWN_ORDER:
        if option == safe_option:
            return label
    raise ValueError(f"Unsupported Merchant Rules persisted Salvage rule mode {safe_option!r}.")


def is_auto_exact_upgrade_salvage_option(raw_option: object) -> bool:
    return normalize_salvage_operation(raw_option) == SALVAGE_OPTION_AUTO_UPGRADE
