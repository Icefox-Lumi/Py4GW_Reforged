"""Pure presentation wording for Merchant Rules preview reasons."""

import re


def _normalize_protected_preview_reason_display_text(reason: str) -> str:
    display_reason = str(reason or "").strip()
    if not display_reason:
        return ""
    display_reason = re.sub(
        r"^Protected by Protected Items:\s*exact model\.?$",
        "Protected by exact Protected Items.",
        display_reason,
    )
    display_reason = re.sub(
        r"^((?:Blocked by|Kept by|Matched by) [^:]+): Protected by Protected Items:\s*exact model\.?$",
        r"\1: protected by exact Protected Items.",
        display_reason,
    )
    return display_reason


def _normalize_preview_reason_display_text(reason: str) -> str:
    display_reason = str(reason or "").strip()
    if not display_reason:
        return ""
    display_reason = re.sub(r"\bHard-protected by\b", "Protected by", display_reason)
    display_reason = _normalize_protected_preview_reason_display_text(display_reason)
    display_reason = re.sub(
        r":\s+Protected by\s+((?:all-weapons|model|requirement range|all-weapons requirement range)\b)",
        r": \1",
        display_reason,
    )
    display_reason = re.sub(
        r"^((?:Blocked by|Kept by|Matched by) [^:]+): Protected by ([^:]+): (.+)$",
        r"\1: protected by \2, \3",
        display_reason,
    )
    display_reason = re.sub(
        r"\b((?:all-weapons|model) perfect-base range):\s+",
        r"\1, ",
        display_reason,
    )
    display_reason = display_reason.replace(
        "all-weapons perfect-base range",
        "requirement range for all weapon types with maximum base stats",
    )
    display_reason = display_reason.replace(
        "model perfect-base range",
        "requirement range for this model with maximum base stats",
    )
    display_reason = display_reason.replace(
        "all-weapons requirement range",
        "requirement range for all weapon types",
    )
    display_reason = display_reason.replace("all-weapons", "all weapon types")
    display_reason = display_reason.replace("perfect-base", "maximum base stats")
    return display_reason


def normalize_preview_entry_reason_display_text(
    reason: str,
    *,
    action_type: str,
    is_skipped: bool,
    will_execute: bool,
    is_consumable_crafter: bool,
) -> str:
    """Format text using a normalized action and widget-derived state facts."""
    display_reason = _normalize_preview_reason_display_text(reason)
    if not display_reason:
        return ""

    display_reason = display_reason.replace("rune / insignia", "rune or insignia")
    display_reason = display_reason.replace("unit(s)", "items")
    display_reason = display_reason.replace("batch(es)", "lots")
    display_reason = display_reason.replace("trade(s)", "trades")
    display_reason = display_reason.replace("free slot(s)", "free inventory slots")
    display_reason = re.sub(
        r"\bNo material model whitelist configured\.?",
        "This rule has no material targets configured.",
        display_reason,
    )
    display_reason = re.sub(
        r"\bNo explicit model whitelist configured\.?",
        "This rule has no exact item targets configured.",
        display_reason,
    )
    display_reason = re.sub(
        r"\bModel ID is required\.?",
        "Choose an item for this rule.",
        display_reason,
    )
    display_reason = re.sub(
        r"\bcould not be found in the current map\.?",
        "is not available here.",
        display_reason,
    )
    display_reason = display_reason.replace(
        "Map is not ready.",
        "Cannot evaluate Merchant Rules because the map is not ready.",
    )
    display_reason = display_reason.replace(
        "Current map is not an outpost or Guild Hall.",
        "Cannot use merchant services because the current map is not an outpost or Guild Hall.",
    )
    display_reason = re.sub(
        r"^(?:Outpost|Guild Hall) ready: .+?\. Using (?:specific|generic) merchant selectors\. "
        r"No merchant or trader NPCs were found\.$",
        "No matching merchant or trader service is available here.",
        display_reason,
    )

    if action_type == "travel":
        display_reason = re.sub(
            r"Travel first, then rebuild the merchant plan in (?:specific|generic) selectors\.?",
            ("After arrival, Merchant Rules will recheck current items and available services before " "executing."),
            display_reason,
        )
        display_reason = display_reason.replace(
            "Travel to Embark Beach first for Consumable Crafter buys.",
            "First stop: travel to Embark Beach to craft the selected consumables.",
        )
        display_reason = display_reason.replace(
            "Travel to the selected Auto Travel destination for remaining Merchant Rules work.",
            "After crafting, travel here and recheck current items and available services.",
        )

    if action_type == "identify":
        display_reason = re.sub(
            r"^selected exact rarity (.+)$",
            r"Matched exact rarity: \1.",
            display_reason,
            flags=re.IGNORECASE,
        )
        display_reason = display_reason.replace(
            "No unidentified items found for the selected exact rarities.",
            "No matching unidentified inventory items were found for the selected rarities.",
        )
        display_reason = display_reason.replace(
            "No ID kit found.",
            "Cannot identify this item because no Identification Kit with uses remaining is available.",
        )

    if action_type == "buy":
        display_reason = display_reason.replace(
            "No consumable crafter items selected.",
            "This rule has no Consumable Crafter items selected.",
        )
        display_reason = display_reason.replace(
            "Selected item is not a supported Embark Beach consumable crafter recipe.",
            "This item has no supported Consumable Crafter recipe.",
        )
        display_reason = display_reason.replace(
            "Consumable crafters are currently supported at Embark Beach only.",
            "Cannot craft this item because its Consumable Crafter is available only at Embark Beach.",
        )
        display_reason = display_reason.replace(
            "Needs exact Xunlai/material-storage scan before crafting.",
            (
                "Xunlai Storage has not been scanned; crafting will be confirmed after stored items and "
                "materials are checked."
            ),
        )
        display_reason = display_reason.replace(
            "Will attempt this buy only if the currently opened merchant offers the item.",
            "Live check: buy only if the Merchant offers this item with a usable price.",
        )
        display_reason = display_reason.replace(
            "Will request a Scroll Trader quote and buy only if the trader currently offers the item.",
            "Live check: buy only if the available Scroll Trader offers this item and returns a valid quote.",
        )
        display_reason = display_reason.replace(
            (
                "Will attempt this exact Rune Trader buy after any storage withdrawals if the trader currently "
                "offers the item."
            ),
            (
                "Live check: after planned withdrawals, buy the remaining quantity only if the Rune Trader "
                "still offers it."
            ),
        )
        if is_consumable_crafter and not is_skipped:
            if not re.search(r"\bcraft", display_reason, flags=re.IGNORECASE):
                display_reason = f"Craft the quantity shown. {display_reason}"

    if action_type == "withdraw":
        display_reason = display_reason.replace(
            "Withdraw from Xunlai before buying.",
            "Move the quantity shown from Xunlai Storage to inventory before any remaining purchase.",
        )

    if action_type == "deposit":
        display_reason = display_reason.replace(
            "No matching inventory items found for this deposit target.",
            "No matching items are expected to remain in inventory when deposits run.",
        )
        display_reason = display_reason.replace(
            "Skipped by deposit keep-out.",
            "Will remain in inventory because this target is in Deposit Keep-outs.",
        )
        display_reason = re.sub(
            r"Deposit reserve keeps (\d+) on character\.",
            r"Will remain in inventory because this target keeps \1.",
            display_reason,
        )
        display_reason = re.sub(
            r"Deposit target keeps (\d+) on character\.",
            r"Move the quantity shown from inventory to Xunlai Storage; keep \1 in inventory.",
            display_reason,
        )
        display_reason = display_reason.replace(
            "Deposit reserve left nothing eligible to move.",
            "All matching items are reserved to remain in inventory.",
        )
        display_reason = display_reason.replace(
            "Linked sell rule no longer exists.",
            "Cannot deposit from this protection link because its Sell rule was deleted.",
        )
        display_reason = display_reason.replace(
            "Linked deposit sources only support weapon or armor sell protections.",
            "Cannot use this link because protected-item deposits support only Weapons and Armor Sell rules.",
        )
        display_reason = display_reason.replace(
            "No protected inventory items matched this linked deposit source.",
            "No inventory items match this linked Weapons or Armor protection rule.",
        )
        if not is_skipped and display_reason.startswith("Protected by "):
            protection_detail = display_reason[len("Protected by ") :]
            display_reason = (
                "Move this item from inventory to Xunlai Storage; it is protected from sale by " f"{protection_detail}"
            )

    if action_type == "sell":
        display_reason = display_reason.replace(
            "Standalone rune or insignia item.",
            "Sell this standalone rune or insignia.",
        )
        display_reason = display_reason.replace(
            "Standalone weapon upgrade component.",
            "Sell this standalone weapon upgrade component.",
        )
        display_reason = re.sub(
            r"^Kept by ([^:]+): reserved to satisfy keep count (\d+)\.?$",
            r"Will remain in inventory because \1 keeps at least \2.",
            display_reason,
        )

    if action_type == "salvage":
        display_reason = re.sub(r"^selected model ", "Matched exact item target: ", display_reason)
        display_reason = re.sub(r"^selected rarity ", "Matched rarity ", display_reason)
        aggregate_match = re.match(r"^Skipped (\d+) (.+)\.$", display_reason)
        if aggregate_match:
            count = int(aggregate_match.group(1))
            blocker = aggregate_match.group(2).replace("no normal salvage kit", "no Salvage Kit is available")
            blocker = blocker.replace("no upgrade salvage kit", "no compatible upgrade Salvage Kit is available")
            display_reason = (
                f"{count} inventory {'entry was' if count == 1 else 'entries were'} not salvaged: {blocker}."
            )

    if action_type == "destroy":
        display_reason = display_reason.replace("selected for MR Salvage", "reserved for Salvage")
        display_reason = display_reason.replace(
            "; salvage wins over destroy.",
            (
                "; Destroy is suppressed because Salvage has priority. The item remains untouched if "
                "Salvage cannot run."
            ),
        )
        display_reason = re.sub(r"^Matched by ([^.]+)\.", r"Matched \1.", display_reason)
        display_reason = display_reason.replace(
            "Included protected item:",
            "Protected-item override is active; this item will be permanently destroyed despite:",
        )
        display_reason = display_reason.replace(
            "Keep count requires splitting a stack",
            "Cannot safely split this stack",
        )
        if will_execute and "permanent" not in display_reason.lower():
            display_reason = f"{display_reason} Permanently destroy the quantity shown.".strip()

    return display_reason
