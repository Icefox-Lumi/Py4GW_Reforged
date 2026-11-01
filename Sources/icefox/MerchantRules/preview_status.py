"""Classify skipped preview entries without owning runtime or UI state."""

from typing import Protocol

PREVIEW_STATUS_NO_MATCH = "no_match"
PREVIEW_STATUS_ALREADY_DONE = "already_done"
PREVIEW_STATUS_SKIPPED = "skipped"
PREVIEW_STATUS_PROTECTED = "protected"
PREVIEW_STATUS_BLOCKED = "blocked"
PREVIEW_STATUS_UNSAFE = "unsafe"
PREVIEW_STATUS_WARNING = "warning"

PREVIEW_NOT_CHANGED_STATUS_ORDER: tuple[str, ...] = (
    PREVIEW_STATUS_UNSAFE,
    PREVIEW_STATUS_BLOCKED,
    PREVIEW_STATUS_PROTECTED,
    PREVIEW_STATUS_WARNING,
    PREVIEW_STATUS_SKIPPED,
    PREVIEW_STATUS_NO_MATCH,
    PREVIEW_STATUS_ALREADY_DONE,
)


class _SkippedPreviewEntry(Protocol):
    @property
    def reason(self) -> str: ...

    @property
    def action_type(self) -> str: ...

    @property
    def label(self) -> str: ...


def classify_skipped_preview_entry(entry: _SkippedPreviewEntry) -> str:
    status_hint = str(getattr(entry, "status_hint", "") or "").strip().lower()
    if status_hint in PREVIEW_NOT_CHANGED_STATUS_ORDER:
        return status_hint

    # Backward-compatible fallback for entries that do not yet carry a semantic hint.
    # Only the stable raw planner reason participates; friendly display wording does not.
    reason_text = str(entry.reason or "").strip().lower()
    action_type = str(entry.action_type or "").strip().lower()
    label_text = str(entry.label or "").strip().lower()
    if action_type == "buy" and label_text == "inventory space":
        return PREVIEW_STATUS_WARNING
    if action_type == "deposit" and "deposit keep-out" in reason_text:
        return PREVIEW_STATUS_PROTECTED
    if "protected" in reason_text:
        return PREVIEW_STATUS_PROTECTED
    if "unsafe" in reason_text or "safely" in reason_text or "safe split" in reason_text:
        return PREVIEW_STATUS_UNSAFE
    if "target already met" in reason_text:
        return PREVIEW_STATUS_ALREADY_DONE
    if "no matching" in reason_text or "nothing found" in reason_text or "no unidentified items found" in reason_text:
        return PREVIEW_STATUS_NO_MATCH
    if (
        "blocked" in reason_text
        or "could not" in reason_text
        or "not available" in reason_text
        or "unavailable" in reason_text
        or "no id kit" in reason_text
        or "no normal salvage kit" in reason_text
        or "no upgrade salvage kit" in reason_text
        or "identify before salvaging" in reason_text
        or "cannot infer" in reason_text
        or "ambiguous" in reason_text
        or "requires rank" in reason_text
        or "map is not ready" in reason_text
        or "not an outpost or guild hall" in reason_text
    ):
        return PREVIEW_STATUS_BLOCKED
    return PREVIEW_STATUS_SKIPPED
