"""Temporary explicit controls for the reviewed, process-local Stage 3B capture."""

from Py4GWCoreLib import PyImGui

from Py4GWCoreLib.Builds.Skills.BipDiagnostic import (
    arm_capture,
    capture_status,
    inspect_account_evidence,
    stop_capture,
    update_capture,
)

MODULE_NAME = "Smart BiP Diagnostic"
MODULE_CATEGORY = "Coding"
MODULE_TAGS = ["debug", "BiP", "energy", "diagnostic"]
OPTIONAL = True


def on_enable() -> None:
    # WidgetManager also calls this when restoring a persisted enabled preference.
    pass


def on_disable() -> None:
    stop_capture("ABORTED_WIDGET_DISABLED")


def update() -> None:
    update_capture()


def draw() -> None:
    visible = PyImGui.begin(MODULE_NAME)
    try:
        if not visible:
            return
        PyImGui.text(capture_status())
        PyImGui.text("One 60-second capture; starts in explorable aggro.")
        PyImGui.text("Owner: My Blood is Power (exact PvE bar).")
        if PyImGui.button("Arm one capture"):
            arm_capture()
        PyImGui.same_line()
        if PyImGui.button("Stop"):
            stop_capture()
        if PyImGui.button("Inspect account evidence"):
            inspect_account_evidence()
        PyImGui.text("Results: SmartBiP3B in the Py4GW console.")
    finally:
        PyImGui.end()
