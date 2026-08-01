# Quest Data Request Pipeline

## Scope

This note records the current reverse-engineering findings behind the Reforged
quest bindings and the Party Quest Log's data-loading behavior.

## What is already cached

The quest log/context already exposes the basic record for each quest:

- quest ID and log state;
- location and map-from/map-to IDs;
- marker coordinates;
- completion, primary, and mission-quest flags;
- pointers to encoded name, description, objectives, location, and NPC strings.

Reading the record is therefore different from obtaining readable text. The
text fields are encoded Guild Wars strings and must pass through the native UI
decoder before Python can consume them.

## Legacy request sequence

The legacy GWCA `QuestMgr` resolved three nearby functions from a quest request
anchor:

```text
RequestQuestInfo_Func(quest_id)
RequestQuestData_Func(quest_id, update_markers)
SetActiveQuest_Func(quest_id)
```

`RequestQuestInfoId` called the first two functions in sequence. The old Python
workflow then requested each text field and waited for its ready flag. The
active quest was changed temporarily because the old workflow treated the
request as an active-quest/UI operation, then restored the original quest.

## Reforged binding path

The Reforged native binding exposes the same logical operations through
`PyQuest` and `GLOBAL_CACHE.Quest`:

```text
RequestQuestInfo
RequestQuestName / Description / Objectives / Location / NPC
IsQuest*Ready
GetQuest*
```

The actual native request must run on `GW::game_thread`. The Python action
queue is only a serializer; it is not the native game-thread boundary.

The crash investigation showed the old direct binding path reached
`GW::quest::RequestQuestInfoId` from the Python callback stack. That request
then entered the active-quest hook while Guild Wars was rendering, producing
the `Model closed while in render queue` assertion. The request binding was
subsequently moved behind `GW::game_thread::Enqueue`.

## WASM findings

The WASM retains named quest/challenge cache functions that expose the more
direct internal model:

- `CharCliChallengeGetData` at `ram:80c426ed`;
- `CharCliChallengeGetDescription` at `ram:80c42b22`;
- `CharCliChallengeGetSelected` at `ram:80c42fab`;
- `CharCliChallengeRequestDescription` at `ram:80c437c3`.

These functions demonstrate that Guild Wars has a keyed challenge/quest cache
and direct request/getter operations. They are evidence for a future native
snapshot API, but they are not yet a complete x86 mapping for every quest-log
field in the Reforged module.

## Current Party Quest Log behavior

The loader now requests each quest by ID without changing the player's active
quest. The sequence is:

```text
read quest-log IDs
→ request quest info for that ID
→ read cached metadata
→ request/decode text fields by ID
→ poll ready flags
```

It no longer requires the primary quest to be fetched first, and it no longer
sets/restores the active quest for every node. Mission-map quest ID `-1` skips
the normal quest-info request because its data comes from mission-objective
context instead.

## Remaining limitation

Text acquisition is still serialized and polling-based. The proper long-term
native design is a game-thread quest-request queue plus a native decoded
snapshot/cache, exposed to Python as one ready snapshot per quest. That would
remove the per-field polling and make the Party Quest Log a read-only consumer
of stable data.
