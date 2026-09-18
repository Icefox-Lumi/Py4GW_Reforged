"""Offline regression checks for Pycons built-in party MB/DP candidate gating.

The full Pycons widget requires the injected game runtime, so this harness
executes the real pure candidate helpers from Pycons.py with controlled state.

Run: python "Examples and tests/tests/test_pycons_mbdp_candidate_gating.py"
Exit code 1 on any failure.
"""

import ast
import pathlib
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[2]
PYCONS_PATH = ROOT / "Widgets" / "Automation" / "Helpers" / "Pycons.py"


def _assignment_value(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("assignment not found: %s" % name)


def _load_candidate_helpers():
    source = PYCONS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PYCONS_PATH))
    function_names = (
        "_fmt_effective",
        "_mbdp_party_projected_effective",
        "_mbdp_party_candidate_stats",
        "_mbdp_party_dp_trigger_count",
        "_mbdp_priority_required_members",
        "_mbdp_party_candidate_score",
    )
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in function_names if name not in functions]
    assert not missing, "missing Pycons helper(s): %s" % ", ".join(missing)

    namespace = {
        "TEAM_ITEM_PRIORITY_OPTIONS": _assignment_value(
            tree, "TEAM_ITEM_PRIORITY_OPTIONS"
        ),
        "TEAM_ITEM_PRIORITY_PRESETS": _assignment_value(
            tree, "TEAM_ITEM_PRIORITY_PRESETS"
        ),
        "TEAM_ITEM_PRIORITY_FORCE_TUNING": _assignment_value(
            tree, "TEAM_ITEM_PRIORITY_FORCE_TUNING"
        ),
        "TEAM_ITEM_PRIORITY_SCORING": _assignment_value(
            tree, "TEAM_ITEM_PRIORITY_SCORING"
        ),
        "TEAM_ITEM_PRIORITY_FORCE_INDEX": 5,
        "cfg": SimpleNamespace(
            mbdp_party_min_members=2,
            mbdp_party_target_effective=10,
            mbdp_party_min_total_gain_5=1,
            mbdp_party_min_total_gain_10=1,
        ),
    }
    module = ast.Module(
        body=[functions[name] for name in function_names],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    exec(compile(module, str(PYCONS_PATH), "exec"), namespace)
    return namespace, source


NAMESPACE, SOURCE = _load_candidate_helpers()
CFG = NAMESPACE["cfg"]
PRIORITY_PRESETS = NAMESPACE["TEAM_ITEM_PRIORITY_PRESETS"]
FORCE_TUNING = NAMESPACE["TEAM_ITEM_PRIORITY_FORCE_TUNING"]
PRIORITY_SCORING = NAMESPACE["TEAM_ITEM_PRIORITY_SCORING"]
REQUIRED_MEMBERS = NAMESPACE["_mbdp_priority_required_members"]
CANDIDATE_SCORE = NAMESPACE["_mbdp_party_candidate_score"]


def _party_context(dp_values, light_count, heavy_count, emergency_count):
    states = [
        {
            "effective": -int(dp) if int(dp) > 0 else 0,
            "dp": int(dp),
        }
        for dp in dp_values
    ]
    return {
        "states": states,
        "target_states": list(states),
        "light_cnt": int(light_count),
        "heavy_cnt": int(heavy_count),
        "emergency_cnt": int(emergency_count),
    }


def _set_priority(priority_index: int) -> None:
    tuning = FORCE_TUNING if priority_index == 5 else PRIORITY_PRESETS[priority_index]
    gain5, gain10, _light, _heavy, _emergency = tuning
    CFG.mbdp_party_min_total_gain_5 = int(gain5)
    CFG.mbdp_party_min_total_gain_10 = int(gain10)


def _check(label: str, expected, observed) -> int:
    passed = expected == observed
    print("[%s] %s" % ("PASS" if passed else "FAIL", label))
    if not passed:
        print("      expected: %r" % (expected,))
        print("      observed: %r" % (observed,))
    return 0 if passed else 1


def main() -> int:
    failures = 0

    helper_start = SOURCE.index("    def _mbdp_priority_required_members(")
    helper_end = SOURCE.index("    def _mbdp_party_candidate_score(", helper_start)
    helper_source = SOURCE[helper_start:helper_end]
    failures += _check(
        "built-in required-member helper no longer reads party minimum",
        False,
        "cfg.mbdp_party_min_members" in helper_source,
    )

    expected_presets = {
        0: (24, 40, -30, -45, -60),
        1: (12, 24, -25, -40, -55),
        2: (8, 12, -15, -30, -45),
        3: (4, 8, -10, -25, -40),
        4: (1, 6, -5, -20, -35),
    }
    expected_scoring = {
        0: (0.75, 1.00, 40, 90),
        1: (0.50, 0.75, 24, 70),
        2: (0.25, 0.50, 12, 45),
        3: (0.25, 0.40, 8, 35),
        4: (0.00, 0.25, 1, 20),
        5: (0.00, 0.25, 1, 10),
    }
    failures += _check(
        "built-in preset thresholds remain unchanged",
        expected_presets,
        PRIORITY_PRESETS,
    )
    observed_scoring = {
        index: (
            values["dp_member_ratio"],
            values["powerstone_member_ratio"],
            values["min_dp_target_gain"],
            values["min_powerstone_target_gain"],
        )
        for index, values in PRIORITY_SCORING.items()
    }
    failures += _check(
        "built-in ratios and minimum gains remain unchanged",
        expected_scoring,
        observed_scoring,
    )

    expected_two_member_counts = {
        "four_leaf_clover": [2, 1, 1, 1, 1, 1],
        "oath_of_purity": [2, 1, 1, 1, 1, 1],
        "powerstone_of_courage": [2, 2, 1, 1, 1, 1],
    }
    for key, expected in expected_two_member_counts.items():
        observed = []
        for priority_index in range(6):
            observed.append(
                REQUIRED_MEMBERS(
                    {"target_states": [{}, {}]},
                    priority_index,
                    key,
                )
            )
        failures += _check("two-member breadth for %s" % key, expected, observed)

    CFG.mbdp_party_min_members = 8
    high_party_minimum_counts = {
        key: REQUIRED_MEMBERS({"target_states": [{}, {}]}, 5, key)
        for key in expected_two_member_counts
    }
    failures += _check(
        "built-in breadth ignores party minimum after eligibility",
        {"four_leaf_clover": 1, "oath_of_purity": 1, "powerstone_of_courage": 1},
        high_party_minimum_counts,
    )
    CFG.mbdp_party_min_members = 2

    force_ctx = _party_context([0, 15], light_count=1, heavy_count=1, emergency_count=0)
    _set_priority(5)
    for key in ("four_leaf_clover", "oath_of_purity"):
        valid, _score, reason = CANDIDATE_SCORE(key, force_ctx, 5)
        failures += _check(
            "Force admits one qualifying member for %s" % key, True, valid
        )
        if not valid:
            print("      reason: %s" % reason)

    valid, _score, reason = CANDIDATE_SCORE("honeycomb", force_ctx, 5)
    failures += _check("Force morale candidate remains valid", True, valid)
    if not valid:
        print("      reason: %s" % reason)

    no_dp_ctx = _party_context([0, 0], light_count=0, heavy_count=0, emergency_count=0)
    valid, _score, reason = CANDIDATE_SCORE("four_leaf_clover", no_dp_ctx, 5)
    failures += _check("zero DP does not admit Clover", False, valid)
    failures += _check(
        "zero DP is rejected for the right reason", "no target gain", reason
    )

    _set_priority(2)
    balanced_ctx = _party_context(
        [0, 15], light_count=1, heavy_count=0, emergency_count=0
    )
    valid, _score, reason = CANDIDATE_SCORE("four_leaf_clover", balanced_ctx, 2)
    failures += _check("Balanced keeps its minimum projected DP gain", False, valid)
    failures += _check(
        "Balanced reports its projected-gain rejection",
        "target_gain=10 min_dp_gain=12",
        reason,
    )

    expected_clover_for_15_dp = [False, False, False, True, True, True]
    observed_clover_for_15_dp = []
    for priority_index in range(6):
        _set_priority(priority_index)
        tuning = (
            FORCE_TUNING if priority_index == 5 else PRIORITY_PRESETS[priority_index]
        )
        light_threshold = max(0, -int(tuning[2]))
        light_count = 1 if 15 >= light_threshold else 0
        context = _party_context([0, 15], light_count, heavy_count=0, emergency_count=0)
        valid, _score, _reason = CANDIDATE_SCORE(
            "four_leaf_clover", context, priority_index
        )
        observed_clover_for_15_dp.append(valid)
    failures += _check(
        "Clover mode matrix preserves six built-in thresholds and ratios",
        expected_clover_for_15_dp,
        observed_clover_for_15_dp,
    )

    force_severe_ctx = _party_context(
        [0, 45], light_count=1, heavy_count=1, emergency_count=1
    )
    _set_priority(5)
    valid, _score, reason = CANDIDATE_SCORE(
        "powerstone_of_courage", force_severe_ctx, 5
    )
    failures += _check("Force keeps Powerstone's separate rules", True, valid)
    if not valid:
        print("      reason: %s" % reason)

    preserve_severe_ctx = _party_context(
        [0, 45], light_count=1, heavy_count=1, emergency_count=1
    )
    _set_priority(0)
    valid, _score, reason = CANDIDATE_SCORE(
        "powerstone_of_courage", preserve_severe_ctx, 0
    )
    failures += _check("Preserve still requires broad Powerstone impact", False, valid)
    failures += _check(
        "Preserve rejects Powerstone on member breadth first",
        "dp_members=1 need=2",
        reason,
    )

    party_gate_markers = (
        "eligible_total < int(cfg.mbdp_party_min_members)",
        "len(states) < int(cfg.mbdp_party_min_members)",
    )
    failures += _check(
        "party-size eligibility gates remain present",
        True,
        all(marker in SOURCE for marker in party_gate_markers),
    )

    legacy_start = SOURCE.index("    def _mbdp_build_legacy_party_candidates(")
    legacy_end = SOURCE.index("    def _mbdp_party_projected_effective(", legacy_start)
    legacy_source = SOURCE[legacy_start:legacy_end]
    legacy_markers = (
        'int(ctx["emergency_cnt"]) >= int(cfg.mbdp_party_min_members)',
        'int(ctx["heavy_cnt"]) >= int(cfg.mbdp_party_min_members)',
        'int(ctx["light_cnt"]) >= int(cfg.mbdp_party_min_members)',
    )
    failures += _check(
        "Custom legacy DP gates remain unchanged",
        True,
        all(marker in legacy_source for marker in legacy_markers),
    )

    print("=" * 68)
    print("%d case(s) failed" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
