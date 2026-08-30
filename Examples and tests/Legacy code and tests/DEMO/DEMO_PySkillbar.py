# Necessary Imports
import json

import Py4GW        #Miscelanious functions and classes
import PyImGui     #ImGui wrapper
import PySkill      #Skill functions and classes
import PySkillbar   #Skillbar functions and classes
import PySystem     #Target-local diagnostic logging and timing

from Py4GWCoreLib import Agent, Map, Player

# End Necessary Imports


Module_Name = "Skillbar_DEMO"

input_skillbar_index = 0  # Input field to select a skill index
skillbar_instance = PySkillbar.Skillbar()  # Create an instance of Skillbar
skill_template = ""
input_skill_slot = 1
target_agentID = 0


# Probe 1 is deliberately local to this demo. It must not use GLOBAL_CACHE.SkillBar,
# shared memory, or the action queue: those surfaces hide the native return value.
PROBE1_TIMEOUT_MS = 2000
PROBE1_STABLE_MS = 100
PROBE1_LOG_MODULE = "Skillbar_DEMO.Probe1"
PROBE2_ARM_TIMEOUT_MS = 30000
PROBE2_CONVERGENCE_TIMEOUT_MS = 2000
PROBE2_STABLE_MS = 100
PROBE2_LOG_MODULE = "Skillbar_DEMO.Probe2Observer"
PROBE1_STATUS_IDLE = "IDLE"
PROBE1_STATUS_RUNNING = "RUNNING"
PROBE1_STATUS_SUCCEEDED = "SUCCEEDED"
PROBE1_STATUS_TIMED_OUT = "TIMED OUT"
PROBE1_STATUS_FAILED = "FAILED"
PROBE2_PHASE_IDLE = "IDLE"
PROBE2_PHASE_ARMED = "ARMED"
PROBE2_PHASE_CONVERGING = "CONVERGING"


def _new_probe1_state(run_id=0):
    observable_names = (
        "skills",
        "professions",
        "attributes_base",
        "attributes_level",
        "encoded_available",
        "encoded_normalized",
        "requested_base",
        "requested_level",
    )
    return {
        "run_id": run_id,
        "status": PROBE1_STATUS_IDLE,
        "requested_code": "",
        "expected": None,
        "expected_decoder": "",
        "before": None,
        "last_state": None,
        "last_normalized_state": None,
        "final_state": None,
        "invoke_tick": None,
        "return_tick": None,
        "finished_tick": None,
        "native_return_type": None,
        "native_return_value": None,
        "native_exception": None,
        "poll_samples": 0,
        "first_change_ms": None,
        "last_change_ms": None,
        "first_requested_match_ms": None,
        "first_requested_match_modes": [],
        "observable_first_match_ms": {name: None for name in observable_names},
        "observable_match_since_tick": {name: None for name in observable_names},
        "observable_stable_match_ms": {name: None for name in observable_names},
        "stable_logged": set(),
        "runtime_errors": [],
        "transient_decode_errors": [],
        "transient_decode_first_ms": None,
        "transient_decode_resolved_ms": None,
        "failure_reason": None,
    }


probe1_state = _new_probe1_state()


def _new_probe2_state(run_id=0):
    state = _new_probe1_state(run_id)
    state["phase"] = PROBE2_PHASE_IDLE
    state["armed_tick"] = None
    state["first_change_tick"] = None
    state["waiting_for_change_ms"] = None
    state["convergence_elapsed_ms"] = None
    return state


probe2_state = _new_probe2_state()


def _probe1_error_text(error):
    return f"{type(error).__name__}: {error}"[:240]


def _probe1_log_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _probe1_log(event, **details):
    payload = {
        "probe": "Probe1",
        "run": probe1_state["run_id"],
        "event": event,
    }
    payload.update(details)
    try:
        PySystem.Console.Log(
            PROBE1_LOG_MODULE,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        # Diagnostics must never turn a target-side observation into a demo crash.
        pass


def _probe2_log(event, **details):
    payload = {
        "probe": "Probe2Observer",
        "run": probe2_state["run_id"],
        "event": event,
    }
    payload.update(details)
    try:
        PySystem.Console.Log(
            PROBE2_LOG_MODULE,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        # Diagnostics must never turn a target-side observation into a demo crash.
        pass


def _probe1_tick():
    return int(PySystem.get_tick_count64())


def _probe1_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _probe1_normalize_decoded(decoded):
    """Normalize either native decode output or the repository fallback parser."""
    if not isinstance(decoded, dict):
        return None

    primary = _probe1_int(decoded.get("profession", decoded.get("primary_profession")))
    secondary = _probe1_int(decoded.get("secondary_profession"))
    skills_raw = decoded.get("skills")
    if primary is None or secondary is None or not isinstance(skills_raw, (list, tuple)):
        return None
    if len(skills_raw) != 8:
        return None

    skills = []
    for skill_id in skills_raw:
        normalized_skill_id = _probe1_int(skill_id)
        if normalized_skill_id is None:
            return None
        skills.append(normalized_skill_id)

    attributes_raw = decoded.get("attributes")
    attributes = {}
    if attributes_raw is None:
        attributes_raw = []
    if isinstance(attributes_raw, dict):
        attribute_entries = attributes_raw.items()
        for attribute_id, level in attribute_entries:
            normalized_id = _probe1_int(attribute_id)
            normalized_level = _probe1_int(level)
            if normalized_id is None or normalized_level is None:
                return None
            attributes[normalized_id] = normalized_level
    elif isinstance(attributes_raw, (list, tuple)):
        for entry in attributes_raw:
            if entry is None:
                continue
            if not isinstance(entry, dict):
                return None
            normalized_id = _probe1_int(entry.get("id", entry.get("attribute_id")))
            normalized_level = _probe1_int(entry.get("level", entry.get("value")))
            if normalized_id is None or normalized_level is None:
                return None
            attributes[normalized_id] = normalized_level
    else:
        return None

    return {
        "profession": primary,
        "secondary_profession": secondary,
        "skills": skills,
        "attributes": [
            {"id": attribute_id, "value": attributes[attribute_id]}
            for attribute_id in sorted(attributes)
        ],
    }


def _probe1_decode_template(template):
    """Prefer the native decoder and retain a clearly labelled Python fallback."""
    errors = []
    native_decoder = getattr(PySkillbar, "decode_skill_template", None)
    if callable(native_decoder):
        try:
            normalized = _probe1_normalize_decoded(native_decoder(template))
            if normalized is not None:
                return normalized, "PySkillbar.decode_skill_template", errors
            errors.append("native decoder returned an invalid shape")
        except Exception as error:
            errors.append(f"native decoder: {_probe1_error_text(error)}")
    else:
        errors.append("PySkillbar.decode_skill_template is unavailable")

    try:
        from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils

        primary, secondary, attributes, skills = Utils.ParseSkillbarTemplate(template)
        normalized = _probe1_normalize_decoded(
            {
                "profession": primary,
                "secondary_profession": secondary,
                "attributes": attributes,
                "skills": skills,
            }
        )
        if normalized is not None:
            return normalized, "Utils.ParseSkillbarTemplate", errors
        errors.append("fallback parser returned an invalid shape")
    except Exception as error:
        errors.append(f"fallback parser: {_probe1_error_text(error)}")

    return None, "unavailable", errors


def _probe1_is_transient_decode_error(error):
    return error == "native decoder returned an invalid shape"


def _probe1_capture_target_state():
    """Capture only direct target-client state; never read the shared-memory cache."""
    errors = []
    transient_errors = []

    try:
        skillbar_instance.GetContext()
    except Exception as error:
        errors.append(f"skillbar context: {_probe1_error_text(error)}")

    skills = []
    for slot in range(1, 9):
        try:
            skill = skillbar_instance.GetSkill(slot)
            skill_id = _probe1_int(skill.id.id)
            if skill_id is None:
                raise ValueError("skill id was unavailable")
            skills.append(skill_id)
        except Exception as error:
            skills.append(None)
            errors.append(f"skill slot {slot}: {_probe1_error_text(error)}")

    try:
        agent_id = _probe1_int(Player.GetAgentID(), 0)
    except Exception as error:
        agent_id = 0
        errors.append(f"player agent: {_probe1_error_text(error)}")

    professions = None
    if agent_id:
        try:
            primary, secondary = Agent.GetProfessionIDs(agent_id)
            primary = _probe1_int(primary)
            secondary = _probe1_int(secondary)
            if primary is None or secondary is None:
                raise ValueError("profession id was unavailable")
            professions = [primary, secondary]
        except Exception as error:
            errors.append(f"professions: {_probe1_error_text(error)}")

    attributes = None
    if agent_id:
        try:
            raw_attributes = Agent.GetAttributes(agent_id)
            if raw_attributes is None:
                raise ValueError("attribute collection was unavailable")

            parsed_attributes = []
            attributes_complete = True
            for attribute in raw_attributes:
                attribute_id = _probe1_int(getattr(attribute, "attribute_id", None))
                level_base = _probe1_int(getattr(attribute, "level_base", None))
                level = _probe1_int(getattr(attribute, "level", None))
                if attribute_id is None or level_base is None or level is None:
                    attributes_complete = False
                    errors.append("attribute entry was incomplete")
                    continue
                parsed_attributes.append(
                    {
                        "id": attribute_id,
                        "level_base": level_base,
                        "level": level,
                    }
                )

            if attributes_complete:
                attributes = sorted(parsed_attributes, key=lambda entry: entry["id"])
        except Exception as error:
            errors.append(f"attributes: {_probe1_error_text(error)}")

    encoded = None
    encoded_normalized = None
    encoded_decoder = "unavailable"
    if callable(getattr(PySkillbar, "encode_skill_template", None)):
        try:
            encoded_value = PySkillbar.encode_skill_template()
            if encoded_value is not None and not isinstance(encoded_value, str):
                raise TypeError(f"encoder returned {type(encoded_value).__name__}")
            encoded = encoded_value
        except Exception as error:
            errors.append(f"native encode: {_probe1_error_text(error)}")
    else:
        errors.append("PySkillbar.encode_skill_template is unavailable")

    if encoded:
        encoded_normalized, encoded_decoder, decode_errors = _probe1_decode_template(encoded)
        for error in decode_errors:
            formatted_error = f"encoded decode: {error}"
            if _probe1_is_transient_decode_error(error):
                transient_errors.append(formatted_error)
            else:
                errors.append(formatted_error)

    normalized_state = None
    if (
        all(skill_id is not None for skill_id in skills)
        and professions is not None
        and attributes is not None
    ):
        normalized_state = (
            tuple(skills),
            tuple(professions),
            tuple(
                (entry["id"], entry["level_base"], entry["level"])
                for entry in attributes
            ),
        )

    return {
        "agent_id": agent_id,
        "skills": skills,
        "professions": professions,
        "attributes": attributes,
        "encoded": encoded,
        "encoded_normalized": encoded_normalized,
        "encoded_decoder": encoded_decoder,
        "normalized": normalized_state,
        "errors": sorted(set(errors)),
        "transient_errors": sorted(set(transient_errors)),
    }


def _probe1_state_for_log(state, include_encoded=False):
    if state is None:
        return None
    result = {
        "agent_id": state["agent_id"],
        "skills": state["skills"],
        "professions": state["professions"],
        "attributes": state["attributes"],
    }
    if include_encoded:
        result.update(
            {
                "encoded": state["encoded"],
                "encoded_length": len(state["encoded"]) if state["encoded"] else 0,
                "encoded_decoder": state["encoded_decoder"],
                "encoded_normalized": state["encoded_normalized"],
            }
        )
    if state["errors"]:
        result["read_errors"] = state["errors"]
    if state["transient_errors"]:
        result["transient_errors"] = state["transient_errors"]
    return result


def _probe1_attribute_map(state, field):
    if state is None or state["attributes"] is None:
        return None
    return {
        entry["id"]: entry[field]
        for entry in state["attributes"]
    }


def _probe1_attribute_match(state, field, expected_attributes):
    """Compare only requested IDs; Agent.GetAttributes also exposes unrelated entries."""
    observed_attributes = _probe1_attribute_map(state, field)
    if observed_attributes is None or expected_attributes is None:
        return False
    return all(
        observed_attributes.get(attribute_id) == expected_value
        for attribute_id, expected_value in expected_attributes.items()
    )


def _probe1_expected_attribute_map(expected):
    if expected is None:
        return None
    return {
        entry["id"]: entry["value"]
        for entry in expected["attributes"]
    }


def _probe1_match_flags(state, expected=None, use_probe1_expected=True):
    if use_probe1_expected:
        expected = probe1_state["expected"]
    if state is None or expected is None:
        return {name: False for name in probe1_state["observable_first_match_ms"]}

    skills_match = (
        state["skills"] is not None
        and all(skill_id is not None for skill_id in state["skills"])
        and state["skills"] == expected["skills"]
    )
    professions_match = state["professions"] == [
        expected["profession"],
        expected["secondary_profession"],
    ]
    expected_attributes = _probe1_expected_attribute_map(expected)
    attributes_base_match = _probe1_attribute_match(
        state, "level_base", expected_attributes
    )
    attributes_level_match = _probe1_attribute_match(
        state, "level", expected_attributes
    )
    encoded_available = bool(state["encoded"])
    encoded_normalized = state["encoded_normalized"] == expected if state["encoded_normalized"] else False

    return {
        "skills": skills_match,
        "professions": professions_match,
        "attributes_base": attributes_base_match,
        "attributes_level": attributes_level_match,
        "encoded_available": encoded_available,
        "encoded_normalized": encoded_normalized,
        "requested_base": skills_match and professions_match and attributes_base_match,
        "requested_level": skills_match and professions_match and attributes_level_match,
    }


def _probe1_elapsed_ms(tick):
    return max(0, int(tick - probe1_state["return_tick"]))


def _probe1_track_transient_decode(
    state, elapsed_ms, probe_state=None, log_function=None
):
    if probe_state is None:
        probe_state = probe1_state
    if log_function is None:
        log_function = _probe1_log

    for error in state["transient_errors"]:
        if error not in probe_state["transient_decode_errors"]:
            probe_state["transient_decode_errors"].append(error)
            if probe_state["transient_decode_first_ms"] is None:
                probe_state["transient_decode_first_ms"] = elapsed_ms
                log_function(
                    "transient_decode_observed",
                    elapsed_ms=elapsed_ms,
                    decoder=state["encoded_decoder"],
                    errors=state["transient_errors"],
                )

    if (
        probe_state["transient_decode_errors"]
        and probe_state["transient_decode_resolved_ms"] is None
        and state["encoded_decoder"] == "PySkillbar.decode_skill_template"
    ):
        probe_state["transient_decode_resolved_ms"] = elapsed_ms
        log_function(
            "transient_decode_resolved",
            elapsed_ms=elapsed_ms,
            decoder=state["encoded_decoder"],
            errors=probe_state["transient_decode_errors"],
        )


def _probe1_transient_decode_summary(probe_state=None):
    if probe_state is None:
        probe_state = probe1_state
    return {
        "observed": bool(probe_state["transient_decode_errors"]),
        "errors": probe_state["transient_decode_errors"],
        "first_ms": probe_state["transient_decode_first_ms"],
        "resolved": probe_state["transient_decode_resolved_ms"] is not None,
        "resolved_ms": probe_state["transient_decode_resolved_ms"],
    }


def _probe1_timing_summary():
    return {
        "invoke_tick": probe1_state["invoke_tick"],
        "return_tick": probe1_state["return_tick"],
        "native_call_ms": (
            probe1_state["return_tick"] - probe1_state["invoke_tick"]
            if probe1_state["invoke_tick"] is not None and probe1_state["return_tick"] is not None
            else None
        ),
        "first_change_ms": probe1_state["first_change_ms"],
        "last_change_ms": probe1_state["last_change_ms"],
        "first_requested_match_ms": probe1_state["first_requested_match_ms"],
        "first_requested_match_modes": probe1_state["first_requested_match_modes"],
        "observable_first_match_ms": probe1_state["observable_first_match_ms"],
        "observable_stable_match_ms": probe1_state["observable_stable_match_ms"],
        "poll_samples": probe1_state["poll_samples"],
        "timeout_ms": PROBE1_TIMEOUT_MS,
        "stable_window_ms": PROBE1_STABLE_MS,
    }


def _probe1_comparison_summary(
    state, expected=None, requested_code=None, use_probe1_expected=True
):
    if use_probe1_expected:
        expected = probe1_state["expected"]
        requested_code = probe1_state["requested_code"]
    flags = _probe1_match_flags(state, expected, use_probe1_expected=False)
    encoded = state["encoded"] if state else None
    return {
        "skills_match": flags["skills"],
        "professions_match": flags["professions"],
        "attributes_vs_level_base_match": flags["attributes_base"],
        "attributes_vs_level_match": flags["attributes_level"],
        "requested_state_match_modes": [
            mode
            for mode, key in (("level_base", "requested_base"), ("level", "requested_level"))
            if flags[key]
        ],
        "encoded_available": flags["encoded_available"],
        "encoded_raw_match": bool(encoded) and encoded == requested_code,
        "encoded_normalized_match": flags["encoded_normalized"],
        "encoded_decoder": state["encoded_decoder"] if state else "unavailable",
    }


def _probe1_finish(status, state, tick, reason=None):
    probe1_state["status"] = status
    probe1_state["finished_tick"] = tick
    probe1_state["final_state"] = state
    if reason:
        probe1_state["failure_reason"] = reason

    event = "final_state" if status == PROBE1_STATUS_SUCCEEDED else "timeout_summary"
    if status == PROBE1_STATUS_FAILED:
        event = "failure_summary"
    _probe1_log(
        event,
        status=status,
        reason=reason,
        state=_probe1_state_for_log(state, include_encoded=True),
        comparison=_probe1_comparison_summary(state),
        timing=_probe1_timing_summary() if probe1_state["return_tick"] is not None else None,
        runtime_errors=probe1_state["runtime_errors"],
        transient_decode=_probe1_transient_decode_summary(),
    )


def _probe1_fail(reason, state=None):
    probe1_state["failure_reason"] = reason
    try:
        tick = _probe1_tick()
    except Exception:
        tick = None
    _probe1_finish(PROBE1_STATUS_FAILED, state, tick, reason)


def _probe1_start(template):
    global probe1_state

    run_id = probe1_state["run_id"] + 1
    probe1_state = _new_probe1_state(run_id)
    requested_code = (template or "").strip()
    probe1_state["requested_code"] = requested_code

    if not requested_code:
        _probe1_fail("template input is empty")
        return

    try:
        is_outpost = bool(Map.IsOutpost())
        map_id = _probe1_int(Map.GetMapID(), 0)
    except Exception as error:
        _probe1_fail(f"map precondition unavailable: {_probe1_error_text(error)}")
        return
    if not is_outpost:
        _probe1_fail(f"target is not in an outpost (map_id={map_id})")
        return

    try:
        target_agent_id = _probe1_int(Player.GetAgentID(), 0)
    except Exception as error:
        _probe1_fail(f"player agent unavailable: {_probe1_error_text(error)}")
        return
    if not target_agent_id:
        _probe1_fail("player agent id is zero")
        return

    before = _probe1_capture_target_state()
    probe1_state["before"] = before
    _probe1_log(
        "baseline",
        map_id=map_id,
        outpost=is_outpost,
        requested_code=requested_code,
        state=_probe1_state_for_log(before, include_encoded=True),
    )

    expected, decoder, decode_errors = _probe1_decode_template(requested_code)
    probe1_state["expected"] = expected
    probe1_state["expected_decoder"] = decoder
    _probe1_log(
        "requested_decode",
        code=requested_code,
        decoder=decoder,
        normalized=expected,
        decode_errors=decode_errors,
    )
    if expected is None:
        _probe1_fail("requested template could not be decoded", before)
        return

    before_flags = _probe1_match_flags(before)
    if before_flags["requested_base"] or before_flags["requested_level"]:
        _probe1_fail("requested template already matches the current target build", before)
        return

    try:
        invoke_tick = _probe1_tick()
    except Exception as error:
        _probe1_fail(f"timing clock unavailable: {_probe1_error_text(error)}", before)
        return

    try:
        native_return = skillbar_instance.LoadSkillTemplate(requested_code)
        return_tick = _probe1_tick()
    except Exception as error:
        probe1_state["invoke_tick"] = invoke_tick
        try:
            probe1_state["return_tick"] = _probe1_tick()
        except Exception:
            probe1_state["return_tick"] = invoke_tick
        probe1_state["native_exception"] = _probe1_error_text(error)
        _probe1_log(
            "native_load_return",
            invoke_tick=invoke_tick,
            return_tick=probe1_state["return_tick"],
            return_type="EXCEPTION",
            return_value=None,
            exception=probe1_state["native_exception"],
        )
        _probe1_fail("native template load raised an exception", before)
        return

    probe1_state["invoke_tick"] = invoke_tick
    probe1_state["return_tick"] = return_tick
    probe1_state["native_return_type"] = type(native_return).__name__
    probe1_state["native_return_value"] = _probe1_log_value(native_return)
    probe1_state["status"] = PROBE1_STATUS_RUNNING
    probe1_state["last_normalized_state"] = before["normalized"]
    _probe1_log(
        "native_load_return",
        invoke_tick=invoke_tick,
        return_tick=return_tick,
        return_type=probe1_state["native_return_type"],
        return_value=probe1_state["native_return_value"],
        native_call_ms=return_tick - invoke_tick,
    )


def _probe1_poll():
    if probe1_state["status"] != PROBE1_STATUS_RUNNING:
        return

    try:
        tick = _probe1_tick()
    except Exception as error:
        _probe1_fail(f"timing clock failed during polling: {_probe1_error_text(error)}", probe1_state["last_state"])
        return

    state = _probe1_capture_target_state()
    probe1_state["poll_samples"] += 1
    probe1_state["last_state"] = state
    for error in state["errors"]:
        if error not in probe1_state["runtime_errors"]:
            probe1_state["runtime_errors"].append(error)

    elapsed_ms = _probe1_elapsed_ms(tick)
    _probe1_track_transient_decode(state, elapsed_ms)

    normalized_state = state["normalized"]
    if normalized_state is not None:
        previous_normalized_state = probe1_state["last_normalized_state"]
        if previous_normalized_state is not None and normalized_state != previous_normalized_state:
            elapsed_ms = _probe1_elapsed_ms(tick)
            if probe1_state["first_change_ms"] is None:
                probe1_state["first_change_ms"] = elapsed_ms
                _probe1_log(
                    "first_state_change",
                    elapsed_ms=elapsed_ms,
                    state=_probe1_state_for_log(state),
                )
            else:
                _probe1_log(
                    "state_change",
                    elapsed_ms=elapsed_ms,
                    state=_probe1_state_for_log(state),
                )
            probe1_state["last_change_ms"] = elapsed_ms
        probe1_state["last_normalized_state"] = normalized_state

    flags = _probe1_match_flags(state)
    for observable, matches in flags.items():
        if matches:
            if probe1_state["observable_first_match_ms"][observable] is None:
                probe1_state["observable_first_match_ms"][observable] = elapsed_ms
            if probe1_state["observable_match_since_tick"][observable] is None:
                probe1_state["observable_match_since_tick"][observable] = tick
            stable_since = probe1_state["observable_match_since_tick"][observable]
            if (
                probe1_state["observable_stable_match_ms"][observable] is None
                and stable_since is not None
                and tick - stable_since >= PROBE1_STABLE_MS
            ):
                probe1_state["observable_stable_match_ms"][observable] = elapsed_ms
        else:
            probe1_state["observable_match_since_tick"][observable] = None

    requested_modes = [
        mode
        for mode, key in (("level_base", "requested_base"), ("level", "requested_level"))
        if flags[key]
    ]
    if requested_modes and probe1_state["first_requested_match_ms"] is None:
        probe1_state["first_requested_match_ms"] = elapsed_ms
        probe1_state["first_requested_match_modes"] = requested_modes
        _probe1_log(
            "first_requested_match",
            elapsed_ms=elapsed_ms,
            modes=requested_modes,
        )

    stable_requested_modes = [
        mode
        for mode, key in (("level_base", "requested_base"), ("level", "requested_level"))
        if probe1_state["observable_stable_match_ms"][key] is not None
    ]
    for mode in stable_requested_modes:
        if mode not in probe1_state["stable_logged"]:
            probe1_state["stable_logged"].add(mode)
            _probe1_log(
                "stable_requested_match",
                elapsed_ms=probe1_state["observable_stable_match_ms"]["requested_" + ("base" if mode == "level_base" else "level")],
                mode=mode,
                stable_window_ms=PROBE1_STABLE_MS,
            )

    if stable_requested_modes:
        _probe1_finish(PROBE1_STATUS_SUCCEEDED, state, tick)
        return

    if elapsed_ms >= PROBE1_TIMEOUT_MS:
        _probe1_finish(
            PROBE1_STATUS_TIMED_OUT,
            state,
            tick,
            "requested state did not remain stable for 100 ms before timeout",
        )


def _probe1_reset():
    global probe1_state
    if probe1_state["status"] == PROBE1_STATUS_RUNNING:
        _probe1_log("reset", reason="operator reset while polling")
    probe1_state = _new_probe1_state(probe1_state["run_id"])


def draw_probe1_controls():
    PyImGui.separator()
    PyImGui.text("Probe 1: direct target-side template diagnostics")
    PyImGui.text(f"Probe 1 status: {probe1_state['status']}")

    if probe1_state["status"] == PROBE1_STATUS_RUNNING:
        if PyImGui.button("Reset Probe 1"):
            _probe1_reset()
        PyImGui.same_line(0, 8)
        PyImGui.text(f"Polling sample {probe1_state['poll_samples']}")
    else:
        if probe2_state["status"] == PROBE1_STATUS_RUNNING:
            PyImGui.text("Probe 1 unavailable while Probe 2 is running")
        elif PyImGui.button("Run Probe 1 - Direct Load"):
            _probe1_start(skill_template)
        PyImGui.same_line(0, 8)
        if PyImGui.button("Reset Probe 1"):
            _probe1_reset()

    if probe1_state["status"] in (PROBE1_STATUS_SUCCEEDED, PROBE1_STATUS_TIMED_OUT, PROBE1_STATUS_FAILED):
        if probe1_state["failure_reason"]:
            PyImGui.text(f"Probe 1 note: {probe1_state['failure_reason']}")
        timing = _probe1_timing_summary() if probe1_state["return_tick"] is not None else None
        if timing:
            PyImGui.text(
                "Timing: "
                f"first change={timing['first_change_ms']} ms, "
                f"last change={timing['last_change_ms']} ms, "
                f"first match={timing['first_requested_match_ms']} ms"
            )
            PyImGui.text(
                "Stable match: "
                f"base={timing['observable_stable_match_ms']['requested_base']} ms, "
                f"level={timing['observable_stable_match_ms']['requested_level']} ms"
            )


def _probe2_waiting_elapsed_ms(tick):
    return max(0, int(tick - probe2_state["armed_tick"]))


def _probe2_convergence_elapsed_ms(tick):
    if probe2_state["first_change_tick"] is None:
        return None
    return max(0, int(tick - probe2_state["first_change_tick"]))


def _probe2_timing_summary():
    return {
        "armed_tick": probe2_state["armed_tick"],
        "first_change_tick": probe2_state["first_change_tick"],
        "waiting_for_change_ms": probe2_state["waiting_for_change_ms"],
        "convergence_elapsed_ms": probe2_state["convergence_elapsed_ms"],
        "last_change_convergence_ms": probe2_state["last_change_ms"],
        "first_requested_match_convergence_ms": probe2_state["first_requested_match_ms"],
        "first_requested_match_modes": probe2_state["first_requested_match_modes"],
        "observable_first_match_convergence_ms": probe2_state["observable_first_match_ms"],
        "observable_stable_match_convergence_ms": probe2_state["observable_stable_match_ms"],
        "poll_samples": probe2_state["poll_samples"],
        "arm_timeout_ms": PROBE2_ARM_TIMEOUT_MS,
        "convergence_timeout_ms": PROBE2_CONVERGENCE_TIMEOUT_MS,
        "stable_window_ms": PROBE2_STABLE_MS,
    }


def _probe2_finish(status, state, tick, reason=None):
    probe2_state["status"] = status
    probe2_state["finished_tick"] = tick
    probe2_state["final_state"] = state
    if tick is not None and probe2_state["armed_tick"] is not None:
        if probe2_state["first_change_tick"] is None:
            probe2_state["waiting_for_change_ms"] = max(
                0, int(tick - probe2_state["armed_tick"])
            )
        else:
            probe2_state["convergence_elapsed_ms"] = max(
                0, int(tick - probe2_state["first_change_tick"])
            )
    if reason:
        probe2_state["failure_reason"] = reason

    event = "final_state" if status == PROBE1_STATUS_SUCCEEDED else "timeout_summary"
    if status == PROBE1_STATUS_FAILED:
        event = "failure_summary"
    _probe2_log(
        event,
        status=status,
        reason=reason,
        state=_probe1_state_for_log(state, include_encoded=True),
        comparison=_probe1_comparison_summary(
            state,
            probe2_state["expected"],
            probe2_state["requested_code"],
            use_probe1_expected=False,
        ),
        timing=_probe2_timing_summary() if probe2_state["armed_tick"] is not None else None,
        runtime_errors=probe2_state["runtime_errors"],
        transient_decode=_probe1_transient_decode_summary(probe2_state),
    )


def _probe2_fail(reason, state=None):
    probe2_state["failure_reason"] = reason
    try:
        tick = _probe1_tick()
    except Exception:
        tick = None
    _probe2_finish(PROBE1_STATUS_FAILED, state, tick, reason)


def _probe2_start(template):
    global probe2_state

    run_id = probe2_state["run_id"] + 1
    probe2_state = _new_probe2_state(run_id)
    requested_code = (template or "").strip()
    probe2_state["requested_code"] = requested_code

    if not requested_code:
        _probe2_fail("template input is empty")
        return

    try:
        is_outpost = bool(Map.IsOutpost())
        map_id = _probe1_int(Map.GetMapID(), 0)
    except Exception as error:
        _probe2_fail(f"map precondition unavailable: {_probe1_error_text(error)}")
        return
    if not is_outpost:
        _probe2_fail(f"target is not in an outpost (map_id={map_id})")
        return

    try:
        target_agent_id = _probe1_int(Player.GetAgentID(), 0)
    except Exception as error:
        _probe2_fail(f"player agent unavailable: {_probe1_error_text(error)}")
        return
    if not target_agent_id:
        _probe2_fail("player agent id is zero")
        return

    before = _probe1_capture_target_state()
    probe2_state["before"] = before
    _probe2_log(
        "baseline",
        map_id=map_id,
        outpost=is_outpost,
        requested_code=requested_code,
        state=_probe1_state_for_log(before, include_encoded=True),
    )

    expected, decoder, decode_errors = _probe1_decode_template(requested_code)
    probe2_state["expected"] = expected
    probe2_state["expected_decoder"] = decoder
    _probe2_log(
        "requested_decode",
        code=requested_code,
        decoder=decoder,
        normalized=expected,
        decode_errors=decode_errors,
    )
    if expected is None:
        _probe2_fail("requested template could not be decoded", before)
        return

    before_flags = _probe1_match_flags(
        before, expected, use_probe1_expected=False
    )
    if before_flags["requested_base"] or before_flags["requested_level"]:
        _probe2_fail("requested template already matches the current target build", before)
        return

    try:
        start_tick = _probe1_tick()
    except Exception as error:
        _probe2_fail(f"timing clock unavailable: {_probe1_error_text(error)}", before)
        return

    probe2_state["armed_tick"] = start_tick
    probe2_state["phase"] = PROBE2_PHASE_ARMED
    probe2_state["status"] = PROBE1_STATUS_RUNNING
    probe2_state["last_normalized_state"] = before["normalized"]
    _probe1_track_transient_decode(
        before,
        0,
        probe2_state,
        _probe2_log,
    )
    _probe2_log(
        "observer_started",
        armed_tick=start_tick,
        requested_code=requested_code,
        expected_decoder=decoder,
        load_invoked=False,
        phase=PROBE2_PHASE_ARMED,
        arm_timeout_ms=PROBE2_ARM_TIMEOUT_MS,
        convergence_timeout_ms=PROBE2_CONVERGENCE_TIMEOUT_MS,
    )


def _probe2_poll():
    if probe2_state["status"] != PROBE1_STATUS_RUNNING:
        return

    try:
        tick = _probe1_tick()
    except Exception as error:
        _probe2_fail(
            f"timing clock failed during polling: {_probe1_error_text(error)}",
            probe2_state["last_state"],
        )
        return

    state = _probe1_capture_target_state()
    probe2_state["poll_samples"] += 1
    probe2_state["last_state"] = state
    for error in state["errors"]:
        if error not in probe2_state["runtime_errors"]:
            probe2_state["runtime_errors"].append(error)

    waiting_elapsed_ms = _probe2_waiting_elapsed_ms(tick)
    normalized_state = state["normalized"]
    if normalized_state is not None:
        previous_normalized_state = probe2_state["last_normalized_state"]
        if previous_normalized_state is not None and normalized_state != previous_normalized_state:
            if probe2_state["first_change_tick"] is None:
                probe2_state["first_change_tick"] = tick
                probe2_state["phase"] = PROBE2_PHASE_CONVERGING
                probe2_state["waiting_for_change_ms"] = waiting_elapsed_ms
                probe2_state["first_change_ms"] = waiting_elapsed_ms
                probe2_state["last_change_ms"] = 0
                _probe2_log(
                    "first_state_change",
                    elapsed_ms=waiting_elapsed_ms,
                    armed_tick=probe2_state["armed_tick"],
                    first_change_tick=tick,
                    waiting_for_change_ms=waiting_elapsed_ms,
                    convergence_elapsed_ms=0,
                    state=_probe1_state_for_log(state),
                )
            else:
                convergence_elapsed_ms = _probe2_convergence_elapsed_ms(tick)
                _probe2_log(
                    "state_change",
                    elapsed_ms=convergence_elapsed_ms,
                    first_change_tick=probe2_state["first_change_tick"],
                    convergence_elapsed_ms=convergence_elapsed_ms,
                    state=_probe1_state_for_log(state),
                )
                probe2_state["last_change_ms"] = convergence_elapsed_ms
        probe2_state["last_normalized_state"] = normalized_state

    if probe2_state["first_change_tick"] is None:
        observation_elapsed_ms = waiting_elapsed_ms
        flags = {
            name: False for name in probe2_state["observable_first_match_ms"]
        }
    else:
        observation_elapsed_ms = _probe2_convergence_elapsed_ms(tick)
        probe2_state["convergence_elapsed_ms"] = observation_elapsed_ms
        _probe1_track_transient_decode(
            state,
            observation_elapsed_ms,
            probe2_state,
            _probe2_log,
        )
        flags = _probe1_match_flags(
            state, probe2_state["expected"], use_probe1_expected=False
        )

    if probe2_state["first_change_tick"] is None:
        _probe1_track_transient_decode(
            state,
            observation_elapsed_ms,
            probe2_state,
            _probe2_log,
        )

    for observable, matches in flags.items():
        if matches:
            if probe2_state["observable_first_match_ms"][observable] is None:
                probe2_state["observable_first_match_ms"][observable] = observation_elapsed_ms
            if probe2_state["observable_match_since_tick"][observable] is None:
                probe2_state["observable_match_since_tick"][observable] = tick
            stable_since = probe2_state["observable_match_since_tick"][observable]
            if (
                probe2_state["observable_stable_match_ms"][observable] is None
                and stable_since is not None
                and tick - stable_since >= PROBE2_STABLE_MS
            ):
                probe2_state["observable_stable_match_ms"][observable] = observation_elapsed_ms
        else:
            probe2_state["observable_match_since_tick"][observable] = None

    requested_modes = [
        mode
        for mode, key in (("level_base", "requested_base"), ("level", "requested_level"))
        if flags[key]
    ]
    if requested_modes and probe2_state["first_requested_match_ms"] is None:
        probe2_state["first_requested_match_ms"] = observation_elapsed_ms
        probe2_state["first_requested_match_modes"] = requested_modes
        _probe2_log(
            "first_requested_match",
            elapsed_ms=observation_elapsed_ms,
            first_change_tick=probe2_state["first_change_tick"],
            convergence_elapsed_ms=observation_elapsed_ms,
            modes=requested_modes,
        )

    stable_requested_modes = [
        mode
        for mode, key in (("level_base", "requested_base"), ("level", "requested_level"))
        if probe2_state["observable_stable_match_ms"][key] is not None
    ]
    for mode in stable_requested_modes:
        if mode not in probe2_state["stable_logged"]:
            probe2_state["stable_logged"].add(mode)
            _probe2_log(
                "stable_requested_match",
                elapsed_ms=probe2_state["observable_stable_match_ms"]["requested_" + ("base" if mode == "level_base" else "level")],
                first_change_tick=probe2_state["first_change_tick"],
                convergence_elapsed_ms=probe2_state["observable_stable_match_ms"]["requested_" + ("base" if mode == "level_base" else "level")],
                mode=mode,
                stable_window_ms=PROBE2_STABLE_MS,
            )

    if stable_requested_modes:
        _probe2_finish(PROBE1_STATUS_SUCCEEDED, state, tick)
        return

    if probe2_state["first_change_tick"] is None:
        if waiting_elapsed_ms < PROBE2_ARM_TIMEOUT_MS:
            return
        _probe2_finish(
            PROBE1_STATUS_TIMED_OUT,
            state,
            tick,
            "no external change observed within the 30000 ms armed wait window",
        )
        return

    convergence_elapsed_ms = probe2_state["convergence_elapsed_ms"]
    if (
        convergence_elapsed_ms is not None
        and convergence_elapsed_ms >= PROBE2_CONVERGENCE_TIMEOUT_MS
    ):
        _probe2_finish(
            PROBE1_STATUS_TIMED_OUT,
            state,
            tick,
            "requested state did not remain stable for 100 ms within the 2000 ms convergence window",
        )


def _probe2_reset():
    global probe2_state
    if probe2_state["status"] == PROBE1_STATUS_RUNNING:
        _probe2_log("reset", reason="operator reset while polling")
    probe2_state = _new_probe2_state(probe2_state["run_id"])


def draw_probe2_controls():
    PyImGui.separator()
    PyImGui.text("Probe 2: remote template observer only")
    PyImGui.text(f"Probe 2 status: {probe2_state['status']}")
    PyImGui.text("This mode never invokes LoadSkillTemplate; send from Client A.")

    if probe2_state["status"] == PROBE1_STATUS_RUNNING:
        if probe2_state["phase"] == PROBE2_PHASE_ARMED:
            PyImGui.text(
                f"Phase: ARMED; waiting up to {PROBE2_ARM_TIMEOUT_MS / 1000:.0f} s for external change"
            )
        else:
            PyImGui.text(
                f"Phase: CONVERGING; {PROBE2_CONVERGENCE_TIMEOUT_MS / 1000:.0f} s verification window"
            )
        if PyImGui.button("Reset Probe 2"):
            _probe2_reset()
        PyImGui.same_line(0, 8)
        PyImGui.text(f"Polling sample {probe2_state['poll_samples']}")
    else:
        if probe1_state["status"] == PROBE1_STATUS_RUNNING:
            PyImGui.text("Probe 2 unavailable while Probe 1 is running")
        elif PyImGui.button("Start Probe 2 - Observe Only"):
            _probe2_start(skill_template)
        PyImGui.same_line(0, 8)
        if PyImGui.button("Reset Probe 2"):
            _probe2_reset()

    if probe2_state["status"] in (
        PROBE1_STATUS_SUCCEEDED,
        PROBE1_STATUS_TIMED_OUT,
        PROBE1_STATUS_FAILED,
    ):
        if probe2_state["failure_reason"]:
            PyImGui.text(f"Probe 2 note: {probe2_state['failure_reason']}")
        timing = _probe2_timing_summary() if probe2_state["armed_tick"] is not None else None
        if timing:
            PyImGui.text(
                "Timing: "
                f"waited={timing['waiting_for_change_ms']} ms, "
                f"convergence={timing['convergence_elapsed_ms']} ms"
            )
            PyImGui.text(
                "Stable match (convergence): "
                f"base={timing['observable_stable_match_convergence_ms']['requested_base']} ms, "
                f"level={timing['observable_stable_match_convergence_ms']['requested_level']} ms"
            )


def draw_skilldata(input_skill_id):

    PyImGui.separator()
    
    if input_skill_id != 0:
        # Create SkillID and SkillType instances based on input
        skill_instance = PySkill.Skill(input_skill_id)
            
        # Basic skill information
        # Basic skill information
        PyImGui.text(f"Skill ID: {skill_instance.id.id}")
        PyImGui.text(f"Skill Name: {skill_instance.id.GetName()}")
        PyImGui.text(f"Skill Type: {skill_instance.type.GetName()}")
        PyImGui.text(f"Profession: {skill_instance.profession.GetName()}")
        PyImGui.text(f"Attribute: {skill_instance.attribute.GetName()}")
        PyImGui.separator()
        
        # Skill Costs and Timers
        PyImGui.text(f"Energy Cost: {skill_instance.energy_cost}")
        PyImGui.text(f"Health Cost: {skill_instance.health_cost}")
        PyImGui.text(f"Adrenaline Cost: {skill_instance.adrenaline}")
        PyImGui.text(f"Overcast: {skill_instance.overcast}")
        PyImGui.text(f"Activation Time: {skill_instance.activation}")
        PyImGui.text(f"Aftercast Time: {skill_instance.aftercast}")
        PyImGui.text(f"Recharge Time: {skill_instance.recharge}")
        PyImGui.separator()

        # Skill Flags and Range
        PyImGui.text(f"Is Touch Range: {'Yes' if skill_instance.is_touch_range else 'No'}")
        PyImGui.text(f"Is Elite: {'Yes' if skill_instance.is_elite else 'No'}")
        PyImGui.text(f"Is Half Range: {'Yes' if skill_instance.is_half_range else 'No'}")
        PyImGui.text(f"Is PvP: {'Yes' if skill_instance.is_pvp else 'No'}")
        PyImGui.text(f"Is PvE: {'Yes' if skill_instance.is_pve else 'No'}")
        PyImGui.text(f"Is Playable: {'Yes' if skill_instance.is_playable else 'No'}")
        PyImGui.text(f"AoE Range: {skill_instance.aoe_range}")
        PyImGui.separator()
        
        # Duration and Scaling Information
        if PyImGui.collapsing_header("Duration and Scaling"):
            PyImGui.text(f"Duration (0 points): {skill_instance.duration_0pts}")
            PyImGui.text(f"Duration (15 points): {skill_instance.duration_15pts}")
            PyImGui.text(f"Scale (0 points): {skill_instance.scale_0pts}")
            PyImGui.text(f"Scale (15 points): {skill_instance.scale_15pts}")
            PyImGui.text(f"Bonus Scale (0 points): {skill_instance.bonus_scale_0pts}")
            PyImGui.text(f"Bonus Scale (15 points): {skill_instance.bonus_scale_15pts}")
            PyImGui.separator()

        # Combo and Skill Arguments
        if PyImGui.collapsing_header("Combo and Arguments"):
            PyImGui.text(f"Combo Requirement: {skill_instance.combo_req}")
            PyImGui.text(f"Combo Effect: {skill_instance.combo}")
            PyImGui.text(f"Skill Arguments: {skill_instance.skill_arguments}")
            PyImGui.text(f"Target: {skill_instance.target}")
            PyImGui.separator()

        # Weapon and Condition Requirements
        if PyImGui.collapsing_header("Weapon and Condition Requirements"):
            PyImGui.text(f"Weapon Requirement: {skill_instance.weapon_req}")
            PyImGui.text(f"Condition: {skill_instance.condition}")
            PyImGui.text(f"Effect 1: {skill_instance.effect1}")
            PyImGui.text(f"Effect 2: {skill_instance.effect2}")
            PyImGui.text(f"Special: {skill_instance.special}")
            PyImGui.separator()

        # Campaign, Titles, and Skill Information
        if PyImGui.collapsing_header("Campaign, Titles, and Skill Info"):
            from Py4GWCoreLib.Skill import Skill
            PyImGui.text(f"Campaign: {Skill.GetCampaign(input_skill_id)[1]}")
            PyImGui.text(f"Title ID: {skill_instance.title}")
            PyImGui.text(f"PvP Skill ID: {skill_instance.id_pvp}")
            PyImGui.separator()

        # Animations and Icon Information
        if PyImGui.collapsing_header("Animations and Icons"):
            PyImGui.text(f"Caster Overhead Animation ID: {skill_instance.caster_overhead_animation_id}")
            PyImGui.text(f"Caster Body Animation ID: {skill_instance.caster_body_animation_id}")
            PyImGui.text(f"Target Body Animation ID: {skill_instance.target_body_animation_id}")
            PyImGui.text(f"Target Overhead Animation ID: {skill_instance.target_overhead_animation_id}")
            PyImGui.text(f"Projectile Animation 1 ID: {skill_instance.projectile_animation1_id}")
            PyImGui.text(f"Projectile Animation 2 ID: {skill_instance.projectile_animation2_id}")
            PyImGui.text(f"Icon File ID: {skill_instance.icon_file_id}")
            PyImGui.text(f"Icon File ID 2: {skill_instance.icon_file2_id}")
            PyImGui.separator()

        # Skill Descriptions
        if PyImGui.collapsing_header("Skill Descriptions"):
            PyImGui.text(f"Skill Name ID: {skill_instance.name_id}")
            PyImGui.text(f"Concise Description ID: {skill_instance.concise}")
            PyImGui.text(f"Full Description ID: {skill_instance.description_id}")
            PyImGui.separator()

        # Additional Flags and Miscellaneous
        if PyImGui.collapsing_header("Additional Flags and Miscellaneous"):
            PyImGui.text(f"Is Stacking: {'Yes' if skill_instance.is_stacking else 'No'}")
            PyImGui.text(f"Is Non-Stacking: {'Yes' if skill_instance.is_non_stacking else 'No'}")
            PyImGui.text(f"Is Unused: {'Yes' if skill_instance.is_unused else 'No'}")
            PyImGui.separator()



def draw_window():
    global Module_Name
    global input_skillbar_index
    global skillbar_instance
    global skill_template
    global input_skill_slot
    global target_agentID

    # Refresh skillbar context
    try:
        skillbar_instance.GetContext()
    except Exception:
        # The probe records unavailable target state itself; keep the demo UI alive.
        pass
    _probe1_poll()
    _probe2_poll()
    

    if PyImGui.begin(Module_Name):

        if PyImGui.collapsing_header("Methods"):
            PyImGui.text("Skill Template (Outpost Exclusive)")
            skill_template = PyImGui.input_text("Expected Template String", skill_template)
            draw_probe1_controls()
            draw_probe2_controls()
            PyImGui.separator()
            
            # Input field for selecting skill slot (limited to 1..8)
            PyImGui.text("Select Skill Slot (1-8)")
            input_skill_slot = PyImGui.input_int("Skill Slot", input_skill_slot)
            if input_skill_slot < 1:  # Limit to minimum of 1
                input_skill_slot = 1
            elif input_skill_slot > 8:  # Limit to maximum of 8
                input_skill_slot = 8
                
            target_agentID = PyImGui.input_int("Target AgentID", target_agentID)
            
            # Use the skill from the selected slot
            if PyImGui.button("Use Selected Skill"):
                skillbar_instance.UseSkill(input_skill_slot, target_agentID)
                #function can accept 0 and will take current Target
            PyImGui.separator()
        
        PyImGui.separator()
        
        if PyImGui.collapsing_header("Skillbar"):
            for index, skill in enumerate(skillbar_instance.skills):
                if PyImGui.collapsing_header(f"Skill {index + 1}"):
                    PyImGui.text(f"Skill {index + 1}:")
                    PyImGui.text(f"  Skill ID: {skill.id.id}")
                    PyImGui.text(f"  Adrenaline A: {skill.adrenaline_a}")
                    PyImGui.text(f"  Adrenaline B: {skill.adrenaline_b}")
                    PyImGui.text(f"  Recharge: {skill.recharge} (this is the timestamp when casted)")
                    PyImGui.text(f"  Event: {skill.event}")
                    PyImGui.separator()
                    if PyImGui.collapsing_header(f"SkillData({skill.id.id})"):
                        draw_skilldata(skill.id.id)
                    PyImGui.separator()


        PyImGui.end()


# main() must exist in every script and is the entry point for your plugin's execution.
def main():
    try:
        draw_window()

    # Handle specific exceptions to provide detailed error messages
    except ImportError as e:
        PySystem.Console.Log("YourModule", f"ImportError encountered: {str(e)}")
    except ValueError as e:
        PySystem.Console.Log("YourModule", f"ValueError encountered: {str(e)}")
    except Exception as e:
        # Catch-all for any other exceptions
        PySystem.Console.Log("YourModule", f"Unexpected error encountered: {str(e)}")
    finally:
        # Optional: Code that will run whether an exception occurred or not
        # This can include cleanup tasks, logging, or final steps
        pass  # Replace with your actual code


# This ensures that main() is called when the script is executed directly.
if __name__ == "__main__":
    main()
