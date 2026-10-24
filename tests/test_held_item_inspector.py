"""Exercise the actual temporary widget against read-only, process-local fixtures."""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGET = ROOT / "Widgets/Coding/Debug/Py4GW/Smart BiP Diagnostic.py"
KAOLAI, VORIZUN = 1219, 773


def effect(skill: int, instance: int = 1, **changes: Any) -> Any:
    values: dict[str, Any] = {
        "skill_id": skill,
        "effect_id": instance,
        "attribute_level": 12,
        "agent_id": 0,
        "duration": 51.0,
        "timestamp": 1000,
        "time_elapsed": 100,
        "time_remaining": 50900,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    reads: list[tuple[str, tuple[Any, ...]]] = []
    output: list[tuple[str, dict[str, Any]]] = []
    combat: list[str] = []
    world = SimpleNamespace(
        ready=True,
        loading=False,
        map_id=42,
        uptime=1000,
        aid=7,
        valid=True,
        dead=False,
        held=False,
        weapon=(1, "weapon"),
        hands=(11, 1, 12, 2),
        casting=False,
        casting_skill=0,
        effects=[],
        buffs=[],
        invalid_items=set(),
    )
    clock = SimpleNamespace(ns=0)
    ui = SimpleNamespace(clicked="", case=0, visible=True, ends=0, texts=[])

    def read(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any) -> Any:
            reads.append((name, args))
            return fn(*args)

        return call

    def read_field(name: str, field: str) -> Callable[..., Any]:
        def value(*_args: Any) -> Any:
            return getattr(world, field)

        return read(name, value)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Observer attempted a gameplay, shared-state or identity mutation/read")

    def item(item_id: int) -> Any:
        assert 0 < item_id <= 0xFFFF, ("unsafe item id", item_id)
        if item_id in world.invalid_items:

            class Invalid:
                def IsItemValid(self, _item_id: int) -> bool:
                    return False

                def __getattr__(self, name: str) -> Any:
                    pytest.fail(f"Invalid item fields accessed: {name}")

            return Invalid()

        def valid(candidate: int) -> bool:
            return candidate == item_id

        return SimpleNamespace(
            IsItemValid=read("Item.IsItemValid", valid),
            model_id=item_id + 100,
            model_file_id=item_id + 200,
            agent_item_id=item_id,
            item_type=SimpleNamespace(ToInt=lambda: 1),
        )

    core = ModuleType("Py4GWCoreLib")
    api = {
        "Player": SimpleNamespace(
            GetAgentID=read("Player.GetAgentID", lambda: world.aid),
            GetAccountEmail=forbidden,
            GetName=forbidden,
            ChangeTarget=forbidden,
            Move=forbidden,
        ),
        "Map": SimpleNamespace(
            IsMapReady=read("Map.IsMapReady", lambda: world.ready),
            IsMapLoading=read("Map.IsMapLoading", lambda: world.loading),
            GetMapID=read("Map.GetMapID", lambda: world.map_id),
            GetInstanceUptime=read("Map.GetInstanceUptime", lambda: world.uptime),
        ),
        "Agent": SimpleNamespace(
            IsValid=read_field("Agent.IsValid", "valid"),
            IsDead=read_field("Agent.IsDead", "dead"),
            IsHoldingItem=read_field("Agent.IsHoldingItem", "held"),
            GetWeaponType=read_field("Agent.GetWeaponType", "weapon"),
            GetWeaponExtraData=read_field("Agent.GetWeaponExtraData", "hands"),
            IsCasting=read_field("Agent.IsCasting", "casting"),
            GetCastingSkillID=read_field("Agent.GetCastingSkillID", "casting_skill"),
            GetModelID=forbidden,
        ),
        "Effects": SimpleNamespace(
            GetEffects=read_field("Effects.GetEffects", "effects"),
            GetBuffs=read_field("Effects.GetBuffs", "buffs"),
            DropBuff=forbidden,
        ),
        "Item": SimpleNamespace(item_instance=read("Item.item_instance", item)),
        "GLOBAL_CACHE": SimpleNamespace(ShMem=SimpleNamespace(GetAllAccountData=forbidden, SendMessage=forbidden)),
    }

    def log(sender: str, message: str, _level: int) -> None:
        assert sender == "KaolaiIdentity"
        prefix, kind, encoded = message.split(" ", 3)[1:]
        assert prefix == "IDENTITY"
        output.append((kind, json.loads(encoded)))

    def end() -> None:
        ui.ends += 1

    def skill_id(name: str) -> int:
        return KAOLAI if name == "Protective_Was_Kaolai" else VORIZUN

    def begin(_name: str) -> bool:
        return bool(ui.visible)

    def button(label: str) -> bool:
        return label == ui.clicked

    def combo(_label: str, _current: int, _cases: Any) -> int:
        return int(ui.case)

    def combat_callback(name: str) -> Callable[..., None]:
        def call(*_args: Any) -> None:
            combat.append(name)

        return call

    api["Skill"] = SimpleNamespace(GetID=read("Skill.GetID", skill_id))
    api["Console"] = SimpleNamespace(Log=log, MessageType=SimpleNamespace(Info=0))
    api["PyImGui"] = SimpleNamespace(
        begin=begin,
        end=end,
        text=ui.texts.append,
        button=button,
        same_line=lambda: None,
        separator=lambda: None,
        combo=combo,
    )
    for name, value in api.items():
        setattr(core, name, value)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", core)
    diagnostic = ModuleType("Py4GWCoreLib.Builds.Skills.BipDiagnostic")
    for name in ("arm_capture", "stop_capture", "update_capture", "inspect_account_evidence"):
        setattr(diagnostic, name, combat_callback(name))
    setattr(diagnostic, "capture_status", lambda: "Disarmed")
    monkeypatch.setitem(sys.modules, diagnostic.__name__, diagnostic)
    spec = importlib.util.spec_from_file_location("_identity_widget", WIDGET)
    assert spec is not None and spec.loader is not None
    widget: Any = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, widget)
    spec.loader.exec_module(widget)
    widget._clock = lambda: clock.ns

    def click(label: str) -> None:
        ui.clicked = label
        try:
            widget.draw()
        finally:
            ui.clicked = ""

    def tick(ms: float = 0) -> None:
        clock.ns += int(ms * 1_000_000)
        widget.update()

    def snapshot() -> dict[str, Any]:
        output.clear()
        click("Snapshot now")
        tick()
        return next(data for kind, data in output if kind == "SAMPLE")

    def record() -> None:
        output.clear()
        click("Record next manual transition")
        tick()

    def samples() -> list[dict[str, Any]]:
        return [data for kind, data in output if kind == "SAMPLE"]

    return SimpleNamespace(
        core=core,
        api=api,
        widget=widget,
        world=world,
        ui=ui,
        clock=clock,
        reads=reads,
        output=output,
        combat=combat,
        click=click,
        tick=tick,
        snapshot=snapshot,
        record=record,
        samples=samples,
        spec=spec,
    )


def done(env: Any) -> dict[str, Any]:
    return next(data for kind, data in env.output if kind == "DONE")


def test_startup_enable_draw_and_idle_updates_do_not_observe(env: Any) -> None:
    env.widget.on_enable()
    for _ in range(10):
        env.widget.draw()
        env.tick(50)
    assert env.reads == [] and env.output == []
    assert env.ui.ends == 10
    assert env.combat == ["update_capture"] * 10


def test_snapshot_one_observation_and_explicit_semantics(env: Any) -> None:
    sample = env.snapshot()
    assert [kind for kind, _ in env.output] == ["HEADER", "SAMPLE", "DONE"]
    assert sample["context"] == {
        "ready": True,
        "loading": False,
        "map_id": 42,
        "uptime_ms": 1000,
        "self_id": 7,
        "valid": True,
        "dead": False,
    }
    assert sample["held_generic"] is False and sample["hands"] == [11, 1, 12, 2]
    assert sample["effects"]["status"] == "empty_or_unavailable"
    assert sample["candidate_items"][0] == {
        "hand_item_id": 11,
        "valid": True,
        "model_id": 111,
        "model_file_id": 211,
        "agent_item_id": 11,
        "item_type": 1,
    }
    reads = list(env.reads)
    for _ in range(5):
        env.tick(1000)
    assert env.reads == reads
    assert not env.widget._comparison.active
    assert env.widget._comparison.samples == []


def test_controls_independent_of_combat_and_repeated_activation(env: Any) -> None:
    env.click("Arm one capture")
    env.record()
    session = env.widget._comparison
    started = session.started
    env.click("Snapshot now")
    env.click("Record next manual transition")
    assert env.widget._comparison is session and session.started == started
    env.click("Stop")
    assert session.active
    env.click("Stop comparison")
    assert env.combat == ["arm_capture", "update_capture", "stop_capture"]
    assert done(env)["reason"] == "MANUAL_STOP"
    assert len(env.output) == 3


def test_exact_sample_limit_and_no_duration_transition_spam(env: Any) -> None:
    env.world.held, env.world.weapon = True, (0, "unknown")
    env.world.effects = [effect(KAOLAI)]
    env.record()
    session = env.widget._comparison
    for i in range(1, 160):
        env.world.effects[0].time_elapsed = 100 + i * 50
        env.world.effects[0].time_remaining = 50900 - i * 50
        env.tick(50)
    assert done(env)["attempts"] == 160 and done(env)["transitions"] == 0, env.output
    assert done(env)["reason"] == "SAMPLE_LIMIT"
    assert len(env.output) == 4
    assert session.samples == [] and session.transitions == []
    count = len(env.reads)
    env.tick(10000)
    assert len(env.reads) == count


def test_interval_deadline_and_no_catchup(env: Any) -> None:
    env.record()
    count = len(env.reads)
    env.tick(49.999)
    assert len(env.reads) == count
    env.tick(0.001)
    assert env.widget._comparison.attempts == 2
    env.tick(1000)
    assert env.widget._comparison.attempts == 3
    env.tick()
    assert env.widget._comparison.attempts == 3
    count = len(env.reads)
    env.tick(6950)
    assert len(env.reads) == count
    assert done(env)["reason"] == "WINDOW_COMPLETE"
    assert done(env)["sampling_gaps"] == 2
    assert done(env)["unsampled_tail_ms"] == 6900
    assert done(env)["transitions"] == 0
    assert any("sampling_gap" in sample["issues"] for sample in env.samples())


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("ready", False, "INVALID_OR_UNAVAILABLE_CONTEXT"),
        ("loading", True, "INVALID_OR_UNAVAILABLE_CONTEXT"),
        ("valid", False, "INVALID_OR_UNAVAILABLE_CONTEXT"),
        ("dead", True, "DEAD"),
        ("aid", 8, "CHARACTER_OR_MAP_CHANGED"),
        ("map_id", 43, "CHARACTER_OR_MAP_CHANGED"),
        ("uptime", 999, "UPTIME_ROLLBACK"),
    ],
)
def test_context_invalidates_before_item_or_effect_reads(env: Any, field: str, value: Any, reason: str) -> None:
    env.record()
    count = sum(name == "Effects.GetEffects" for name, _ in env.reads)
    setattr(env.world, field, value)
    env.tick(50)
    assert done(env)["reason"] == reason
    assert sum(name == "Effects.GetEffects" for name, _ in env.reads) == count
    assert not env.widget._comparison.active


def test_mid_observation_context_change_is_explicit(env: Any) -> None:
    def effects(_aid: int) -> list[Any]:
        env.world.map_id = 99
        return []

    env.api["Effects"].GetEffects = effects
    sample = env.snapshot()
    assert sample["context"]["map_id"] == 42 and sample["context_after"]["map_id"] == 99
    assert done(env)["reason"] == "CHARACTER_OR_MAP_CHANGED"


@pytest.mark.parametrize("kind", ["missing", "exception", "wrong_type", "none"])
def test_unavailable_effects_are_not_an_empty_list(env: Any, kind: str) -> None:
    if kind == "missing":
        del env.api["Effects"].GetEffects
    elif kind == "exception":

        def bad(_aid: int) -> Any:
            raise RuntimeError("private-account@example.test C:/private/path")

        env.api["Effects"].GetEffects = bad
    else:
        env.world.effects = "private-account@example.test" if kind == "wrong_type" else None
    sample = env.snapshot()
    assert sample["effects"]["status"] == "unavailable"
    assert sample["buffs"]["status"] == "empty_or_unavailable"
    assert "private-account" not in json.dumps(env.output)


@pytest.mark.parametrize(
    "hands",
    [
        (0, 0, 0, 0),
        (-1, 0, 0, 0),
        (65536, 0, 0, 0),
        (None, 0, None, 0),
        (11, 1),
    ],
)
def test_unusable_hand_ids_do_not_construct_items(env: Any, hands: Any) -> None:
    env.world.hands = hands
    sample = env.snapshot()
    assert sample["candidate_items"] == []
    assert not any(name == "Item.item_instance" for name, _ in env.reads)


def test_failed_item_validity_never_reads_model_fields(env: Any) -> None:
    env.world.invalid_items = {11, 12}
    sample = env.snapshot()
    assert sample["candidate_items"] == [
        {"hand_item_id": 11, "valid": False},
        {"hand_item_id": 12, "valid": False},
    ]


def test_effect_fields_zero_agent_and_unsigned_remaining_preserved(env: Any) -> None:
    env.world.effects = [effect(KAOLAI, duration=15.0, time_elapsed=15001, time_remaining=4294967295)]
    env.world.buffs = [SimpleNamespace(skill_id=VORIZUN, buff_id=3, target_agent_id=0)]
    sample = env.snapshot()
    row = sample["effects"]["details"][0]
    assert row["agent_id"] == 0 and row["attribute_level"] == 12
    assert row["duration"] == 15.0 and row["time_remaining"] == 4294967295
    assert row["timing_status"] == "suspicious"
    assert sample["buffs"]["details"] == [{"skill_id": VORIZUN, "buff_id": 3, "target_agent_id": 0}]
    assert "both_comparison_skills_observed" in sample["issues"]


@pytest.mark.parametrize("first,second", [(KAOLAI, VORIZUN), (VORIZUN, KAOLAI)])
def test_replacement_overlap_and_followups_with_continuous_holding(env: Any, first: int, second: int) -> None:
    env.world.held, env.world.weapon = True, (0, "unknown")
    env.world.effects = [effect(first, 11)]
    env.record()
    env.world.effects = [effect(first, 11), effect(second, 22)]
    env.tick(50)
    env.world.effects = [effect(second, 22)]
    for _ in range(32):
        env.tick(50)
    env.click("Stop comparison")
    samples = env.samples()
    assert all(row["held_generic"] is True for row in samples)
    overlap = next(row for row in samples if "both_comparison_skills_observed" in row["issues"])
    assert overlap["effects"]["skill_ids"] == [first, second]
    selected = {reason: row["t_ms"] for row in samples for reason in row["selected_for"]}
    assert selected["first_observed_transition"] == 50
    assert [selected[f"followup_{delay}ms"] for delay in (100, 500, 1500)] == [150, 550, 1550]
    assert done(env)["missing_followups_ms"] == []


def test_cancelled_replacement_retains_old_effect_without_completion_claim(env: Any) -> None:
    env.world.held, env.world.weapon = True, (0, "unknown")
    env.world.effects = [effect(KAOLAI)]
    env.record()
    env.world.casting, env.world.casting_skill = True, VORIZUN
    env.tick(50)
    env.world.casting, env.world.casting_skill = False, 0
    env.tick(50)
    env.click("Stop comparison")
    samples = env.samples()
    assert any(row["casting_skill_id"] == VORIZUN for row in samples)
    assert all(row["effects"]["skill_ids"] == [KAOLAI] for row in samples)
    assert "CONFIRMED" not in json.dumps(env.output) and "success" not in json.dumps(env.output)
    assert done(env)["missing_followups_ms"] == [100, 500, 1500]


def test_memory_output_and_transition_truncation_bounds(env: Any) -> None:
    env.world.effects = [effect(KAOLAI, i) for i in range(40)]
    env.world.buffs = [SimpleNamespace(skill_id=VORIZUN, buff_id=i, target_agent_id=7) for i in range(40)]
    env.record()
    session = env.widget._comparison
    for i in range(1, 159):
        env.world.casting = bool(i % 2)
        env.tick(50)
        assert len(session.samples) <= 160 and len(session.transitions) <= 159
        assert all(len(row["effects"]["skill_ids"]) <= 32 for row in session.samples)
        assert all(len(row["effects"]["details"]) <= 8 for row in session.samples)
    env.click("Stop comparison")
    assert len(env.output) <= 18 and len(env.samples()) == 16
    assert done(env)["records_truncated"] is True and done(env)["omitted_transitions"] > 0
    assert "effects:rows_truncated" in env.samples()[0]["issues"]
    assert "buffs:details_truncated" in env.samples()[0]["issues"]
    assert session.samples == []


@pytest.mark.parametrize(
    "action,reason",
    [
        ("disable", "WIDGET_DISABLED"),
        ("enable", "ENABLED_IDLE"),
        ("reload", "RELOADED"),
    ],
)
def test_disable_enable_and_inplace_reload_terminate_without_rearming(env: Any, action: str, reason: str) -> None:
    env.record()
    session = env.widget._comparison
    reads = list(env.reads)
    if action == "reload":
        env.spec.loader.exec_module(env.widget)
    else:
        getattr(env.widget, "on_" + action)()
    assert not session.active and done(env)["reason"] == reason
    env.widget.update()
    assert env.reads == reads
    assert env.widget._comparison is None or not env.widget._comparison.active


def test_fixed_case_and_console_privacy(env: Any) -> None:
    env.ui.case = 3
    env.world.weapon = (0, "private-account@example.test")
    env.snapshot()
    assert all(row["case"] == "replacement" for _, row in env.output)
    assert "private-account" not in json.dumps(env.output)
    allowed = {
        "Map.IsMapReady",
        "Map.IsMapLoading",
        "Map.GetMapID",
        "Map.GetInstanceUptime",
        "Player.GetAgentID",
        "Agent.IsValid",
        "Agent.IsDead",
        "Agent.IsHoldingItem",
        "Agent.GetWeaponType",
        "Agent.GetWeaponExtraData",
        "Agent.IsCasting",
        "Agent.GetCastingSkillID",
        "Effects.GetEffects",
        "Effects.GetBuffs",
        "Item.item_instance",
        "Item.IsItemValid",
        "Skill.GetID",
    }
    assert {name for name, _ in env.reads} <= allowed
    assert env.combat == ["update_capture"]


@pytest.mark.parametrize(
    "owner,method,field",
    [
        ("Agent", "IsHoldingItem", "held_generic"),
        ("Agent", "GetWeaponType", "weapon_type"),
        ("Agent", "IsCasting", "casting"),
        ("Agent", "GetCastingSkillID", "casting_skill_id"),
    ],
)
def test_missing_scalar_api_remains_unknown(env: Any, owner: str, method: str, field: str) -> None:
    delattr(env.api[owner], method)
    sample = env.snapshot()
    assert sample[field] is None
    assert f"{owner}.{method}:unavailable_api" in sample["issues"]
    assert done(env)["reason"] == "SNAPSHOT_COMPLETE"


@pytest.mark.parametrize(
    "owner,method",
    [
        ("Map", "IsMapReady"),
        ("Map", "GetInstanceUptime"),
        ("Player", "GetAgentID"),
        ("Agent", "IsDead"),
    ],
)
def test_missing_context_api_aborts_without_reading_items(env: Any, owner: str, method: str) -> None:
    delattr(env.api[owner], method)
    env.snapshot()
    assert done(env)["reason"] == "INVALID_OR_UNAVAILABLE_CONTEXT"
    assert not any(name.startswith(("Effects.", "Item.")) for name, _ in env.reads)


def test_missing_effect_fields_and_nonfinite_duration_are_explicit(env: Any) -> None:
    row = effect(KAOLAI, duration=float("nan"))
    del row.attribute_level
    del row.time_remaining
    env.world.effects = [row]
    sample = env.snapshot()
    detail = sample["effects"]["details"][0]
    assert detail["duration"] is None and detail["attribute_level"] is None and detail["time_remaining"] is None
    assert detail["timing_status"] == "unavailable"
    assert any("attribute_level:missing" in issue for issue in sample["issues"])
    assert "NaN" not in json.dumps(env.output)


def test_plausible_mixed_units_are_preserved_without_bonus_or_identity_claim(env: Any) -> None:
    env.world.effects = [effect(KAOLAI, attribute_level=0, duration=15.0, time_elapsed=1000, time_remaining=14000)]
    detail = env.snapshot()["effects"]["details"][0]
    assert detail == {
        "skill_id": KAOLAI,
        "effect_id": 1,
        "attribute_level": 0,
        "agent_id": 0,
        "duration": 15.0,
        "timestamp": 1000,
        "time_elapsed": 1000,
        "time_remaining": 14000,
        "timing_status": "plausible",
    }


def test_gap_does_not_reconstruct_missed_followups(env: Any) -> None:
    env.record()
    env.world.held, env.world.weapon = True, (0, "unknown")
    env.world.effects = [effect(KAOLAI)]
    env.tick(50)
    env.tick(3000)
    env.click("Stop comparison")
    assert done(env)["missing_followups_ms"] == [100, 500, 1500]
    assert done(env)["sampling_gaps"] == 1
    assert done(env)["transitions"] == 1
    assert not any(label.startswith("followup") for row in env.samples() for label in row["selected_for"])
    assert env.samples()[-1]["t_ms"] == 3050


def test_same_spell_renewal_and_reordered_rows(env: Any) -> None:
    env.world.effects = [effect(KAOLAI, 5), effect(999, 7)]
    env.record()
    env.world.effects.reverse()
    env.tick(50)
    assert env.widget._comparison.transitions == []
    env.world.effects[1].timestamp += 1000
    env.tick(50)
    env.click("Stop comparison")
    assert done(env)["transitions"] == 1
    assert any(row["effects"]["details"][0]["timestamp"] == 2000 for row in env.samples())


def test_drop_with_lingering_effect_retains_both_observations(env: Any) -> None:
    env.world.held, env.world.weapon = True, (0, "unknown")
    env.world.effects = [effect(KAOLAI)]
    env.record()
    env.world.held, env.world.weapon = False, (1, "weapon")
    env.tick(50)
    env.click("Stop comparison")
    assert env.samples()[-1]["held_generic"] is False
    assert env.samples()[-1]["effects"]["skill_ids"] == [KAOLAI]
    assert "CONFIRMED" not in json.dumps(env.output)


def test_natural_expiration_records_suspicious_timer_then_effect_removal(env: Any) -> None:
    env.world.held, env.world.weapon = True, (0, "unknown")
    env.world.effects = [effect(KAOLAI, duration=15.0, time_elapsed=14900, time_remaining=100)]
    env.record()
    env.world.effects[0].time_elapsed = 15050
    env.world.effects[0].time_remaining = 0xFFFFFFCE
    env.tick(50)
    env.world.effects = []
    env.world.held, env.world.weapon = False, (1, "weapon")
    env.tick(50)
    env.click("Stop comparison")
    assert any(
        row["effects"]["details"] and row["effects"]["details"][0]["timing_status"] == "suspicious"
        for row in env.samples()
    )
    assert env.samples()[-1]["effects"]["status"] == "empty_or_unavailable"


def test_deadline_before_first_update_does_not_sample_and_reports_gap(env: Any) -> None:
    env.click("Record next manual transition")
    env.tick(8000)
    assert env.reads == []
    assert done(env)["attempts"] == 0 and done(env)["sampling_gaps"] == 1
    assert done(env)["reason"] == "WINDOW_COMPLETE"
    assert [kind for kind, _ in env.output] == ["HEADER", "DONE"]


def test_clock_rollback_stops_without_another_observation(env: Any) -> None:
    env.record()
    reads = list(env.reads)
    env.tick(-1)
    assert env.reads == reads and done(env)["reason"] == "CLOCK_ROLLBACK"


def test_output_failure_disarms_and_releases_retained_samples(env: Any) -> None:
    def broken_log(*_args: Any) -> None:
        raise RuntimeError("private-account@example.test")

    env.api["Console"].Log = broken_log
    env.click("Snapshot now")
    env.tick()
    assert env.widget._comparison.status == "OUTPUT_UNAVAILABLE"
    assert not env.widget._comparison.active and env.widget._comparison.samples == []
    assert env.output == []


def test_fresh_reload_starts_idle_after_disable(env: Any) -> None:
    env.record()
    old = env.widget._comparison
    env.widget.on_disable()
    reads = list(env.reads)
    fresh: Any = importlib.util.module_from_spec(env.spec)
    env.spec.loader.exec_module(fresh)
    fresh.on_enable()
    fresh.update()
    fresh.draw()
    assert not old.active and fresh._comparison is None and env.reads == reads


def test_pending_snapshot_manual_stop_and_rearm_are_bounded(env: Any) -> None:
    env.click("Snapshot now")
    env.click("Stop comparison")
    assert done(env)["attempts"] == 0 and env.reads == []
    env.ui.case = 2
    sample = env.snapshot()
    assert sample["case"] == "Vorizun" and done(env)["attempts"] == 1


def test_account_inspector_remains_available_during_comparison(env: Any) -> None:
    env.record()
    session = env.widget._comparison
    reads = list(env.reads)
    env.click("Inspect account evidence")
    assert env.combat == ["update_capture", "inspect_account_evidence"]
    assert env.widget._comparison is session and session.active
    assert session.attempts == 1 and env.reads == reads and env.output == []
    env.click("Stop comparison")
    assert done(env)["reason"] == "MANUAL_STOP"


@pytest.mark.parametrize("control", ["separator", "combo"])
def test_comparison_ui_failure_balances_window_without_starting_work(env: Any, control: str) -> None:
    def unavailable(*_args: Any) -> Any:
        raise RuntimeError("UI unavailable")

    setattr(env.api["PyImGui"], control, unavailable)
    with pytest.raises(RuntimeError, match="UI unavailable"):
        env.click("Snapshot now")
    assert env.ui.ends == 1
    assert env.widget._comparison is None
    assert env.reads == [] and env.output == [] and env.combat == []


def test_conflicting_held_and_effect_signals_remain_observations(env: Any) -> None:
    env.world.held = True
    env.world.weapon = (1, "weapon")
    env.world.effects = [effect(VORIZUN)]
    sample = env.snapshot()
    assert sample["held_generic"] is True and sample["weapon_type"] == 1
    assert sample["effects"]["skill_ids"] == [VORIZUN]
    assert sample["candidate_items"][0]["model_id"] == 111
    assert "held_weapon_signal_disagreement" in sample["issues"]
    assert "CONFIRMED" not in json.dumps(env.output)
    assert env.combat == ["update_capture"]


@pytest.mark.parametrize("raises", [False, True])
def test_unsupported_item_metadata_is_unknown_and_private(env: Any, raises: bool) -> None:
    class UnsupportedItem:
        def IsItemValid(self, _item_id: int) -> bool:
            return True

        def __getattr__(self, _name: str) -> Any:
            if raises:
                raise RuntimeError("private-account@example.test")
            return "private-account@example.test"

    def unsupported_item(_item_id: int) -> UnsupportedItem:
        return UnsupportedItem()

    env.api["Item"].item_instance = unsupported_item
    sample = env.snapshot()
    assert sample["candidate_items"] == [
        {
            "hand_item_id": item_id,
            "valid": True,
            "model_id": None,
            "model_file_id": None,
            "agent_item_id": None,
            "item_type": None,
        }
        for item_id in (11, 12)
    ]
    suffix = "exception" if raises else "missing_or_invalid_integer"
    assert "item.model_id:" + suffix in sample["issues"]
    assert "private-account" not in json.dumps(env.output)
    assert done(env)["reason"] == "SNAPSHOT_COMPLETE"
    assert env.combat == ["update_capture"]
