"""Pure data for travel-on-character-load settings."""

from dataclasses import dataclass


DESTINATION_GUILD_HALL = "guild_hall"
DESTINATION_OUTPOST = "outpost"
DEFAULT_OUTPOST_ID = 55  # Lion's Arch


@dataclass
class TravelOnCharacterLoadConfig:
    """Account-local travel triggers and their destination."""

    travel_on_first_load: bool = False
    travel_on_character_switch: bool = False
    destination: str = DESTINATION_OUTPOST
    outpost_id: int = DEFAULT_OUTPOST_ID
