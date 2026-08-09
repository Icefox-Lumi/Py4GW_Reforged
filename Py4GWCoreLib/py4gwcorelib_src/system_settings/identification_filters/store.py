"""Global persistence for independent ID filter definitions and profiles."""

from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.model import Rule

from .model import IdentificationFilterProfile


_DOC = "Widgets/System/IdentificationFilterProfiles.json"


def _doc():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

        return JsonFactory(_DOC, "global")
    except Exception:
        return None


def load_profiles() -> list[IdentificationFilterProfile]:
    doc = _doc()
    raw = doc.get_json("profiles", []) if doc is not None else []
    return [IdentificationFilterProfile.from_dict(value) for value in raw
            if isinstance(value, dict) and str(value.get("name", "")).strip()]


def save_profiles(profiles: list[IdentificationFilterProfile]) -> None:
    doc = _doc()
    if doc is not None:
        doc.set_json("profiles", [profile.to_dict() for profile in profiles])


def load_rules() -> list[Rule]:
    """Load ID-owned rule definitions. These are deliberately not Loot Factory rules."""
    doc = _doc()
    raw = doc.get_json("filters", []) if doc is not None else []
    if not isinstance(raw, list):
        return []
    rules: list[Rule] = []
    for value in raw:
        if not isinstance(value, dict):
            continue
        try:
            rules.append(Rule.from_dict(value))
        except Exception:
            continue
    return rules


def save_rules(rules: list[Rule]) -> None:
    doc = _doc()
    if doc is not None:
        doc.set_json("filters", [rule.to_dict() for rule in rules])


def next_rule_id(rules: list[Rule]) -> str:
    taken = {rule.id for rule in rules}
    index = 1
    while "id_filter_%d" % index in taken:
        index += 1
    return "id_filter_%d" % index


def migrate_factory_references() -> bool:
    """Copy the previous slice's Factory-owned references into this independent ID rule store once."""
    doc = _doc()
    if doc is None:
        return False
    migration = doc.get_json("migration", {})
    if isinstance(migration, dict) and migration.get("independent_rules", False):
        return False
    raw_profiles = doc.get_json("profiles", [])
    if not isinstance(raw_profiles, list):
        raw_profiles = []
    profiles = [IdentificationFilterProfile.from_dict(raw) for raw in raw_profiles if isinstance(raw, dict)]
    try:
        from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory import store as factory_store

        factory_rules = {rule.id: rule for rule in factory_store.load_rules()}
    except Exception:
        factory_rules = {}
    rules = load_rules()
    copied: dict[str, str] = {}
    changed = False
    for profile in profiles:
        for attribute in ("always_filter_ids", "never_filter_ids"):
            migrated_ids: list[str] = []
            for old_id in list(getattr(profile, attribute)):
                if old_id not in copied:
                    source = factory_rules.get(old_id)
                    if source is None:
                        # It may already be an ID-owned rule from an interrupted migration.
                        copied[old_id] = old_id if any(rule.id == old_id for rule in rules) else ""
                    else:
                        new_id = next_rule_id(rules)
                        rules.append(Rule.from_dict({
                            **source.to_dict(),
                            "id": new_id,
                            "name": "ID: " + source.name,
                        }))
                        copied[old_id] = new_id
                        changed = True
                new_id = copied[old_id]
                if new_id:
                    migrated_ids.append(new_id)
                if new_id != old_id:
                    changed = True
            setattr(profile, attribute, migrated_ids)
    if changed:
        save_rules(rules)
        save_profiles(profiles)
    doc.set_json("migration", {"independent_rules": True})
    return changed


def profile_by_name(profiles: list[IdentificationFilterProfile], name: str) -> IdentificationFilterProfile | None:
    return next((profile for profile in profiles if profile.name == name), None)


def _rules_for_ids(rules, rule_ids: list[str]):
    by_id = {rule.id: rule for rule in rules}
    return [by_id[rule_id] for rule_id in rule_ids if rule_id in by_id]


def rule_sets_in_profile(rules, profile: IdentificationFilterProfile | None):
    """Return ``(always, never)`` rules; never is the caller's hard veto."""
    if profile is None:
        return [], []
    return (
        _rules_for_ids(rules, profile.always_filter_ids),
        _rules_for_ids(rules, profile.never_filter_ids),
    )


def rules_in_profile(rules, profile: IdentificationFilterProfile | None):
    """Compatibility name for consumers that only need the negative/veto rule set."""
    return rule_sets_in_profile(rules, profile)[1]
