Nicholas Farm Manager v1.4 - Collector Conversion
================================================

Collector-backed Nicholas farms
-------------------------------
AUTOMATIC:
- Bog Skale Fin -> Herring
  5 Bog Skale Fins -> 1 Herring
  Collector is encountered inline on BubbleTea's Herring exchange route.

- Chunk of Drake Flesh -> Drake Kabob
  1 Chunk of Drake Flesh -> 1 Drake Kabob
  Collector route: Yohlon Haven.

- Sentient Spore -> Bottle of Vabbian Wine
  5 Sentient Spores -> 1 Bottle of Vabbian Wine
  Collector is encountered inline on BubbleTea's Vabbian Wine route.

- Skale Fin -> Bowl of Skalefin Soup
  2 Skale Fins -> 1 Bowl of Skalefin Soup
  Collector route: The Astralarium.

MANUAL FOR NOW:
- Mandragor Root -> Mandragor Root Cake
  3 Mandragor Roots -> 1 Mandragor Root Cake
  BubbleTea's AutoIt explicitly pauses and asks the user to move to Yajide
  manually. No reliable Yajide coordinates are present in the source, so v1.4
  does not invent them.

Multibox behavior
-----------------
Collector conversion is executed locally on EACH active Guild Wars client.
The Manager opens the collector on all accounts, then dispatches the new
SharedCommandType.CollectorExchange command.

Each client exchanges until it owns 5 converted items or no longer has enough
input trophies.

Core patch REQUIRED
-------------------
Copy these two files from "Core Patch" into the matching Py4GW_Reforged paths:

Py4GWCoreLib/enums_src/Multiboxing_enums.py
Widgets/System/Messaging.py

CollectorExchange was APPENDED to SharedCommandType so the numeric values of
all existing shared commands remain unchanged.

Credits
-------
Farm paths, collector paths and Nicholas exchange paths:
BubbleTea - migrated/adapted from his original AutoIt Nicholas the Traveler scripts.

Manager / BottingTree / multibox integration:
Sky.

v1.4.1 - Widget Catalog tooltip
-------------------------------
The Nicholas Manager tooltip now:
- uses a 580 px window,
- pushes a 550 px text wrap position,
- uses shorter feature/credit labels,
- prevents long bullet_text lines from overflowing the tooltip window.

v1.4.2 - Gift account based target
----------------------------------
The manual per-farm "Target Item Count" setting has been removed.

Config now uses one global setting:

    Accounts to receive 5 Gifts

The farming target is calculated automatically:

    target = farm.items_for_5_gifts * gift_account_count

Example with Forgotten Seal:
    10 seals are required per account for all 5 Gifts.
    4 gift accounts -> target = 40 Forgotten Seals.

The combined multibox inventory counter is compared against this calculated
target. Changing the selected farm automatically recalculates the target using
that farm's Nicholas set requirement.
