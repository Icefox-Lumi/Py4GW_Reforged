"""Pure data for one named ID Filter Profile."""

from dataclasses import dataclass, field


@dataclass
class IdentificationFilterProfile:
    name: str = ""
    #: Matching rules are automatic-ID inclusion overrides over the selected rarity set.
    always_filter_ids: list[str] = field(default_factory=list)
    #: Matching rules are a hard veto for automatic and manual identification.
    never_filter_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "always_filter_ids": list(self.always_filter_ids),
            "never_filter_ids": list(self.never_filter_ids),
        }

    @staticmethod
    def from_dict(raw: dict) -> "IdentificationFilterProfile":
        raw_always = raw.get("always_filter_ids", [])
        # The first ID slice had one negative list. Preserve it as ``never`` during migration.
        raw_never = raw.get("never_filter_ids", raw.get("filter_ids", []))
        always = [str(value) for value in raw_always] if isinstance(raw_always, list) else []
        never = [str(value) for value in raw_never] if isinstance(raw_never, list) else []
        never_set = set(never)
        return IdentificationFilterProfile(
            name=str(raw.get("name", "")).strip(),
            always_filter_ids=[rule_id for rule_id in always if rule_id not in never_set],
            never_filter_ids=never,
        )
