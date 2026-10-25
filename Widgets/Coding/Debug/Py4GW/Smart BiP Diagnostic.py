"""Temporary, independent controls for combat capture and manual item comparison."""

import json
from importlib import import_module
from math import isfinite
from time import monotonic_ns
from typing import Any
from typing import cast

from Py4GWCoreLib import PyImGui
from Py4GWCoreLib.Builds.Skills.BipDiagnostic import arm_capture
from Py4GWCoreLib.Builds.Skills.BipDiagnostic import capture_status
from Py4GWCoreLib.Builds.Skills.BipDiagnostic import inspect_account_evidence
from Py4GWCoreLib.Builds.Skills.BipDiagnostic import stop_capture
from Py4GWCoreLib.Builds.Skills.BipDiagnostic import update_capture

MODULE_NAME = "Smart BiP Diagnostic"
MODULE_CATEGORY = "Coding"
MODULE_TAGS = ["debug", "BiP", "energy", "diagnostic"]
OPTIONAL = True

_CASES = ("baseline", "Kaolai", "Vorizun", "replacement", "expiration", "cancelled_cast", "same_spell_recast")
_INTERVAL_NS = 50_000_000
_WINDOW_NS = 8_000_000_000
_MAX_SAMPLES = 160
_MAX_ROWS = 32
_MAX_DETAILS = 8
_MAX_RECORDS = 16
_clock = monotonic_ns
_case_index = 0


class _Reads:
    """Only fixed read APIs and numeric fields cross this diagnostic boundary."""

    def __init__(self) -> None:
        self.core = import_module("Py4GWCoreLib")
        self.issues: list[str] = []

    def flag(self, issue: str) -> None:
        if issue not in self.issues and len(self.issues) < 128:
            self.issues.append(issue)
        elif len(self.issues) == 128:
            self.issues.append("issues_truncated")

    def call(self, owner: object, method: str, label: str, *args: object) -> object:
        try:
            fn = getattr(owner, method, None)
            if not callable(fn):
                self.flag(label + ":unavailable_api")
                return None
            return fn(*args)
        except Exception:
            # Runtime exception strings can contain account names or filesystem paths.
            self.flag(label + ":exception")
            return None

    def api(self, owner: str, method: str, *args: object) -> object:
        try:
            target: object = getattr(self.core, owner, None)
        except Exception:
            self.flag(owner + ":exception")
            return None
        return self.call(target, method, owner + "." + method, *args)

    def integer(self, value: object, label: str) -> int | None:
        if type(value) is int and 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            return value
        self.flag(label + ":missing_or_invalid_integer")
        return None

    def boolean(self, value: object, label: str) -> bool | None:
        if type(value) is bool:
            return value
        self.flag(label + ":missing_or_invalid_bool")
        return None

    def field(self, row: object, name: str, label: str) -> int | float | None:
        try:
            value: object = getattr(row, name, None)
        except Exception:
            self.flag(label + "." + name + ":exception")
            return None
        if name == "duration":
            if type(value) in (int, float):
                number = float(cast(float, value))
                if isfinite(number) and abs(number) <= 1e12:
                    return number
            self.flag(label + "." + name + ":missing_or_invalid_seconds")
            return None
        return self.integer(value, label + "." + name)

    def context(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ready": self.boolean(self.api("Map", "IsMapReady"), "ready"),
            "loading": self.boolean(self.api("Map", "IsMapLoading"), "loading"),
            "map_id": self.integer(self.api("Map", "GetMapID"), "map_id"),
            "uptime_ms": self.integer(self.api("Map", "GetInstanceUptime"), "uptime_ms"),
            "self_id": None,
            "valid": None,
            "dead": None,
        }
        if result["ready"] is True and result["loading"] is False:
            aid = self.integer(self.api("Player", "GetAgentID"), "self_id")
            result["self_id"] = aid
            if aid:
                result["valid"] = self.boolean(self.api("Agent", "IsValid", aid), "valid")
                if result["valid"] is True:
                    result["dead"] = self.boolean(self.api("Agent", "IsDead", aid), "dead")
        return result

    def effects(self, aid: int, ids: tuple[int | None, int | None], *, buffs: bool) -> dict[str, Any]:
        label, method = ("buffs", "GetBuffs") if buffs else ("effects", "GetEffects")
        raw = self.api("Effects", method, aid)
        result: dict[str, Any] = {"status": "unavailable", "skill_ids": [], "identities": [], "details": []}
        if not isinstance(raw, (list, tuple)):
            self.flag(label + ":unavailable_or_incompatible_list")
            return result
        rows = cast(list[object], raw)
        result["status"] = "read_nonempty" if rows else "empty_or_unavailable"
        result["returned_count"] = len(rows)
        if not rows:
            self.flag(label + ":empty_or_unavailable")
        if len(rows) > _MAX_ROWS:
            self.flag(label + ":rows_truncated")
        fields = (
            ("skill_id", "buff_id", "target_agent_id")
            if buffs
            else (
                "skill_id",
                "effect_id",
                "attribute_level",
                "agent_id",
                "duration",
                "timestamp",
                "time_elapsed",
                "time_remaining",
            )
        )
        for index, row in enumerate(rows[:_MAX_ROWS]):
            prefix = f"{label}[{index}]"
            skill = self.field(row, "skill_id", prefix)
            identity = self.field(row, "buff_id" if buffs else "effect_id", prefix)
            result["skill_ids"].append(skill)
            result["identities"].append((skill, identity))
            if skill is None or skill not in ids:
                continue
            if len(result["details"]) >= _MAX_DETAILS:
                self.flag(label + ":details_truncated")
                continue
            detail: dict[str, Any] = {name: self.field(row, name, prefix) for name in fields}
            if not buffs:
                duration, elapsed, remaining = detail["duration"], detail["time_elapsed"], detail["time_remaining"]
                timing = "unavailable"
                if duration is not None and elapsed is not None and remaining is not None:
                    timing = "no_duration" if duration == 0 else "plausible"
                    if duration < 0 or (
                        duration > 0 and (elapsed > duration * 1000 or remaining > duration * 1000 + 100)
                    ):
                        timing = "suspicious"
                        self.flag(label + ":suspicious_time_possible_underflow_or_stale_entry")
                detail["timing_status"] = timing
            result["details"].append(detail)
        return result

    def items(self, hands: list[int | None]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item_id in dict.fromkeys((hands[0], hands[2])):
            if item_id is None or not 0 < item_id <= 0xFFFF:
                if item_id != 0:
                    self.flag("hand_item_id:unavailable_or_out_of_range")
                continue
            item = self.api("Item", "item_instance", item_id)
            # The supported constructor guards failed lookups itself. Never read
            # its default/model fields until the explicit validity query succeeds.
            valid = self.boolean(self.call(item, "IsItemValid", "item.valid", item_id), "item.valid")
            detail: dict[str, Any] = {"hand_item_id": item_id, "valid": valid}
            if valid is True:
                for name in ("model_id", "model_file_id", "agent_item_id"):
                    detail[name] = self.field(item, name, "item")
                try:
                    item_type: object = getattr(item, "item_type", None)
                except Exception:
                    item_type = None
                    self.flag("item.item_type:exception")
                detail["item_type"] = self.integer(self.call(item_type, "ToInt", "item.item_type"), "item.item_type")
            result.append(detail)
        return result


def _context_failure(context: dict[str, Any], previous: dict[str, Any] | None) -> str | None:
    if context["dead"] is True:
        return "DEAD"
    if (
        context["ready"] is not True
        or context["loading"] is not False
        or context["valid"] is not True
        or context["dead"] is not False
        or not context["self_id"]
        or not context["map_id"]
        or context["uptime_ms"] is None
    ):
        return "INVALID_OR_UNAVAILABLE_CONTEXT"
    if previous is not None:
        if (context["self_id"], context["map_id"]) != (previous["self_id"], previous["map_id"]):
            return "CHARACTER_OR_MAP_CHANGED"
        if context["uptime_ms"] < previous["uptime_ms"]:
            return "UPTIME_ROLLBACK"
    return None


def _observe(reads: _Reads, ids: tuple[int | None, int | None], previous: dict[str, Any] | None) -> dict[str, Any]:
    context = reads.context()
    observation: dict[str, Any] = {"context": context, "issues": reads.issues}
    failure = _context_failure(context, previous)
    if failure is not None:
        observation["abort"] = failure
        return observation
    aid: int = context["self_id"]
    observation["held_generic"] = reads.boolean(reads.api("Agent", "IsHoldingItem", aid), "held")
    weapon = reads.api("Agent", "GetWeaponType", aid)
    observation["weapon_type"] = reads.integer(
        (
            cast(tuple[object, ...], weapon)[0]
            if isinstance(weapon, (list, tuple)) and len(cast(tuple[object, ...], weapon)) == 2
            else None
        ),
        "weapon_type",
    )
    raw_hands = reads.api("Agent", "GetWeaponExtraData", aid)
    hands: list[int | None] = [None, None, None, None]
    if isinstance(raw_hands, (list, tuple)) and len(cast(tuple[object, ...], raw_hands)) == 4:
        hands = [reads.integer(value, f"hands[{i}]") for i, value in enumerate(cast(tuple[object, ...], raw_hands))]
    else:
        reads.flag("hands:unavailable_or_incompatible_tuple")
    observation["hands"] = hands
    observation["candidate_items"] = reads.items(hands)
    observation["casting"] = reads.boolean(reads.api("Agent", "IsCasting", aid), "casting")
    observation["casting_skill_id"] = reads.integer(reads.api("Agent", "GetCastingSkillID", aid), "casting_skill_id")
    observation["effects"] = reads.effects(aid, ids, buffs=False)
    observation["buffs"] = reads.effects(aid, ids, buffs=True)
    present = set(observation["effects"]["skill_ids"] + observation["buffs"]["skill_ids"])
    if None not in ids and len(set(ids)) == 2 and all(skill in present for skill in ids):
        reads.flag("both_comparison_skills_observed")
    for kind in ("effects", "buffs"):
        skills = observation[kind]["skill_ids"]
        if any(skill is not None and skills.count(skill) > 1 for skill in ids):
            reads.flag(kind + ":multiple_entries_for_comparison_skill")
    held, weapon_type = observation["held_generic"], observation["weapon_type"]
    if held is not None and weapon_type is not None and held != (weapon_type == 0):
        reads.flag("held_weapon_signal_disagreement")
    after = reads.context()
    observation["context_after"] = after
    failure = _context_failure(after, context)
    if failure is not None:
        observation["abort"] = failure
    return observation


def _signature(sample: dict[str, Any]) -> str:
    # Timing ticks are deliberately excluded. Instance timestamps distinguish
    # renewals if the runtime happens to reuse an effect id.
    signature: dict[str, Any] = {
        key: sample.get(key)
        for key in (
            "held_generic",
            "weapon_type",
            "hands",
            "candidate_items",
            "casting",
            "casting_skill_id",
            "issues",
            "abort",
        )
    }
    signature["issues"] = [issue for issue in sample.get("issues", []) if issue != "sampling_gap"]
    for kind in ("effects", "buffs"):
        data = sample.get(kind, {})
        details = [
            {key: value for key, value in row.items() if key not in ("duration", "time_elapsed", "time_remaining")}
            for row in data.get("details", [])
        ]
        signature[kind] = {
            "status": data.get("status"),
            "identities": sorted(data.get("identities", []), key=repr),
            "details": sorted(details, key=lambda row: json.dumps(row, sort_keys=True)),
        }
    return json.dumps(signature, sort_keys=True, allow_nan=False)


def _emit(kind: str, data: dict[str, Any]) -> None:
    from Py4GWCoreLib import Console

    Console.Log(
        "KaolaiIdentity",
        "KAOLAI IDENTITY " + kind + " " + json.dumps(data, sort_keys=True, allow_nan=False),
        Console.MessageType.Info,
    )


class _Comparison:
    def __init__(self, case: str, recording: bool) -> None:
        self.case = case
        self.recording = recording
        self.started = _clock()
        self.last_clock = self.started
        self.next_sample = self.started
        self.active = True
        self.status = "Recording" if recording else "Snapshot pending"
        self.ids: tuple[int | None, int | None] = (None, None)
        self.samples: list[dict[str, Any]] = []
        self.transitions: list[int] = []
        self.previous_context: dict[str, Any] | None = None
        self.previous_signature: str | None = None
        self.attempts = 0
        self.gaps = 0

    def advance(self) -> None:
        if not self.active:
            return
        now = _clock()
        if now < self.last_clock:
            self.finish("CLOCK_ROLLBACK")
            return
        self.last_clock = now
        if now >= self.started + _WINDOW_NS:
            self.finish("WINDOW_COMPLETE")
            return
        if now < self.next_sample:
            return
        gap_ms = (now - self.next_sample) / 1_000_000 if self.attempts else (now - self.started) / 1_000_000
        self.next_sample = now + _INTERVAL_NS
        self.attempts += 1
        reads = _Reads()
        if self.attempts == 1:
            self.ids = (
                reads.integer(reads.api("Skill", "GetID", "Protective_Was_Kaolai"), "Kaolai_skill_id"),
                reads.integer(reads.api("Skill", "GetID", "Mighty_Was_Vorizun"), "Vorizun_skill_id"),
            )
            if not all(self.ids) or self.ids[0] == self.ids[1]:
                reads.flag("comparison_skill_ids:unavailable_or_conflicting")
                self.ids = (self.ids[0] or None, self.ids[1] or None)
        if gap_ms >= 50:
            self.gaps += 1
            reads.flag("sampling_gap")
        sample: dict[str, Any]
        try:
            sample = _observe(reads, self.ids, self.previous_context)
        except Exception:
            reads.flag("observation:exception")
            sample = {"context": {}, "issues": reads.issues, "abort": "OBSERVER_EXCEPTION"}
        sample["t_ms"] = (now - self.started) / 1_000_000
        sample["late_by_ms"] = gap_ms
        signature = _signature(sample)
        if self.previous_signature is not None and signature != self.previous_signature:
            self.transitions.append(len(self.samples))
        self.previous_signature = signature
        self.previous_context = sample.get("context_after", sample["context"])
        self.samples.append(sample)
        if "abort" in sample:
            self.finish(sample["abort"])
        elif not self.recording:
            self.finish("SNAPSHOT_COMPLETE")
        elif self.attempts >= _MAX_SAMPLES:
            self.finish("SAMPLE_LIMIT")

    def finish(self, reason: str) -> None:
        if not self.active:
            return
        self.active = False
        self.status = reason
        ended = _clock()
        tail_gap_ms = max(0, min(ended, self.started + _WINDOW_NS) - self.next_sample) / 1_000_000
        selected: dict[int, list[str]] = {}

        def select(index: int, label: str) -> None:
            if index in selected:
                selected[index].append(label)
            elif len(selected) < _MAX_RECORDS:
                selected[index] = [label]

        missing_followups: list[int] = []
        if self.samples:
            select(0, "initial")
            select(len(self.samples) - 1, "final")
        if self.transitions:
            first = self.transitions[0]
            select(first - 1, "before_first_transition")
            select(first, "first_observed_transition")
            anchor: float = self.samples[first]["t_ms"]
            for delay in (100, 500, 1500):
                index = next(
                    (i for i in range(first + 1, len(self.samples)) if self.samples[i]["t_ms"] >= anchor + delay), None
                )
                if index is None or self.samples[index]["t_ms"] > anchor + delay + 100:
                    missing_followups.append(delay)
                else:
                    select(index, f"followup_{delay}ms")
            for index in self.transitions:
                select(index, "transition")
        omitted = sum(index not in selected for index in self.transitions)
        try:
            _emit(
                "HEADER",
                {
                    "case": self.case,
                    "mode": "record" if self.recording else "snapshot",
                    "skill_ids": {"Kaolai": self.ids[0], "Vorizun": self.ids[1]},
                    "semantics": (
                        "observations_only; sequential_nonatomic; held_and_weapon_type_share_one_signal; "
                        "hand_ids_may_be_equipment"
                    ),
                    "duration_unit": "seconds",
                    "elapsed_remaining_unit": "milliseconds",
                    "followup_late_tolerance_ms": 100,
                    "limits": "cast_state_is_not_completion; effect_rank_is_not_healing_proof; world_bundles_deferred",
                },
            )
            for index in sorted(selected):
                _emit("SAMPLE", {"case": self.case, "selected_for": selected[index], **self.samples[index]})
            _emit(
                "DONE",
                {
                    "reason": reason,
                    "case": self.case,
                    "attempts": self.attempts,
                    "records": len(selected),
                    "transitions": len(self.transitions),
                    "omitted_transitions": omitted,
                    "records_truncated": omitted > 0,
                    "sampling_gaps": self.gaps + int(tail_gap_ms >= 50),
                    "unsampled_tail_ms": tail_gap_ms,
                    "elapsed_ms": max(0, ended - self.started) / 1_000_000,
                    "missing_followups_ms": missing_followups,
                },
            )
        except Exception:
            self.status = "OUTPUT_UNAVAILABLE"
        finally:
            self.samples.clear()
            self.transitions.clear()
            self.previous_context = None
            self.previous_signature = None


# Normal WidgetManager reload calls on_disable first. Also terminate an in-place
# module reload, without putting inspector state in the combat capture module.
_previous_stop = globals().get("_stop_comparison")
if callable(_previous_stop):
    _previous_stop("RELOADED")
    stop_capture("ABORTED_RELOADED")
_comparison: _Comparison | None = None


def _start_comparison(recording: bool) -> None:
    global _comparison
    if _comparison is None or not _comparison.active:
        _comparison = _Comparison(_CASES[_case_index], recording)


def _stop_comparison(reason: str = "MANUAL_STOP") -> None:
    if _comparison is not None:
        _comparison.finish(reason)


def on_enable() -> None:
    # WidgetManager also calls this when restoring a persisted enabled preference.
    _stop_comparison("ENABLED_IDLE")


def on_disable() -> None:
    try:
        _stop_comparison("WIDGET_DISABLED")
    finally:
        stop_capture("ABORTED_WIDGET_DISABLED")


def update() -> None:
    update_capture()
    if _comparison is not None:
        _comparison.advance()


def draw() -> None:
    global _case_index
    visible = PyImGui.begin(MODULE_NAME)
    try:
        if not visible:
            return
        PyImGui.text(capture_status())
        PyImGui.text("One 60-second capture; starts in explorable aggro.")
        PyImGui.text("Owner: My Blood is Power (exact PvE bar).")
        if PyImGui.button("Arm one capture"):
            arm_capture(mbas=True)
        PyImGui.same_line()
        if PyImGui.button("Stop"):
            stop_capture()
        if PyImGui.button("Inspect account evidence"):
            inspect_account_evidence()
        PyImGui.text("Results: SmartBiP3B in the Py4GW console.")
        PyImGui.text("Includes MBASV2: healthy remote condition-only admission and queued return.")
        PyImGui.text("Queued return does not prove execution or condition removal.")
        PyImGui.separator()
        PyImGui.text("Held-item comparison (temporary, local observations only)")
        PyImGui.text("Pause automatic skill use yourself; cast and drop manually.")
        PyImGui.text("Independent of the build matcher and combat capture.")
        _case_index = PyImGui.combo("Comparison case", _case_index, _CASES)
        PyImGui.text(_comparison.status if _comparison is not None else "Comparison idle")
        PyImGui.text("While recording, Snapshot/Record do not restart or extend it.")
        if PyImGui.button("Snapshot now"):
            _start_comparison(False)
        if PyImGui.button("Record next manual transition"):
            _start_comparison(True)
        if PyImGui.button("Stop comparison"):
            _stop_comparison()
        PyImGui.text("8 seconds, at most 160 attempts; results: KAOLAI IDENTITY.")
    finally:
        PyImGui.end()
