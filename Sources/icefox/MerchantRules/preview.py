"""Published Merchant Rules preview state and pure interpretation.

Native acquisition adapters, admission, scheduling, colors, drawing and transport
remain widget-owned. Preview state is evidence, not execution authority.
"""

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal
from typing import Protocol

from Sources.icefox.MerchantRules import planning as _planning
from Sources.icefox.MerchantRules.planning import ExecutionPlanEntry
from Sources.icefox.MerchantRules.planning import PlanResult
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_ALREADY_DONE
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_BLOCKED
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_NO_MATCH
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_PROTECTED
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_SKIPPED
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_UNSAFE
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_WARNING

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.inventory_evidence import InventoryItemInfo

PREVIEW_STATUS_READY = "ready"
PREVIEW_STATUS_LIVE_CHECK = "live_check"
PREVIEW_STATUS_NEEDS_XUNLAI = "needs_xunlai"
PREVIEW_STATUS_AFTER_TRAVEL = "after_travel"
PREVIEW_STATUS_TRAVEL = "travel"

PreviewTone = Literal["warning", "info", "muted", "success"]


class ReasonFormatter(Protocol):
    def __call__(
        self,
        reason: str,
        *,
        action_type: str,
        is_skipped: bool,
        will_execute: bool,
        is_consumable_crafter: bool,
    ) -> str: ...


@dataclass(frozen=True)
class PreviewSummary:
    primary_count: int
    secondary_count: int
    status_label: str
    summary: str
    detail: str


class PreviewSession:
    """Own one published preview and its comparison state, without action authority."""

    def __init__(
        self,
        *,
        initial_plan: PlanResult,
        collect_inventory: Callable[[], list["InventoryItemInfo"]],
        get_model_counts: Callable[[], Callable[[list["InventoryItemInfo"]], dict[int, int]]],
        clock: Callable[[], float],
        get_model_label: Callable[[], Callable[[int], str]],
        read_diff_row_limit: Callable[[], int],
        read_merchant_labels: Callable[[], Mapping[str, str]],
        read_action_labels: Callable[[], Mapping[str, str]],
        read_status_labels: Callable[[], Mapping[str, str]],
        read_status_order: Callable[[], tuple[str, ...]],
        read_busy: Callable[[], bool],
        read_detailed_preview: Callable[[], bool],
        read_hide_already_done: Callable[[], bool],
        read_status_message: Callable[[], str],
        embark_name: Callable[[], str],
        get_skipped_classifier: Callable[[], Callable[[ExecutionPlanEntry], str]],
        get_reason_formatter: Callable[[], ReasonFormatter],
    ) -> None:
        self.preview_plan: PlanResult = initial_plan
        self.preview_ready: bool = False
        self.preview_requires_execute_travel: bool = False
        self.preview_execute_travel_target_outpost_id: int = 0
        self.preview_execute_travel_target_outpost_name: str = ""
        self.preview_inventory_diff_summary: str = ""
        self.preview_inventory_diff_rows: list[str] = []
        self.last_preview_compare_duration_ms: float = 0.0
        self.execute_drift_requires_confirmation: bool = False
        self._collect_inventory = collect_inventory
        self._get_model_counts = get_model_counts
        self._clock = clock
        self._get_model_label = get_model_label
        self._read_diff_row_limit = read_diff_row_limit
        self._read_merchant_labels = read_merchant_labels
        self._read_action_labels = read_action_labels
        self._read_status_labels = read_status_labels
        self._read_status_order = read_status_order
        self._read_busy = read_busy
        self._read_detailed_preview = read_detailed_preview
        self._read_hide_already_done = read_hide_already_done
        self._read_status_message = read_status_message
        self._embark_name = embark_name
        self._get_skipped_classifier = get_skipped_classifier
        self._get_reason_formatter = get_reason_formatter

    def clear_preview_inventory_diff(self) -> None:
        self.preview_inventory_diff_summary = ""
        self.preview_inventory_diff_rows = []
        self.last_preview_compare_duration_ms = 0.0
        self.execute_drift_requires_confirmation = False

    def clear_preview_projection_state(self) -> None:
        self.preview_requires_execute_travel = False
        self.preview_execute_travel_target_outpost_id = 0
        self.preview_execute_travel_target_outpost_name = ""

    def set_preview_projection_state(
        self,
        *,
        requires_travel: bool = False,
        target_outpost_id: int = 0,
        target_outpost_name: str = "",
    ) -> None:
        if not requires_travel:
            self.clear_preview_projection_state()
            return
        self.preview_requires_execute_travel = True
        self.preview_execute_travel_target_outpost_id = max(0, int(target_outpost_id))
        self.preview_execute_travel_target_outpost_name = str(target_outpost_name or "").strip()

    def preview_has_execute_travel_pending(self) -> bool:
        return bool(
            self.preview_ready
            and self.preview_requires_execute_travel
            and self.preview_execute_travel_target_outpost_id > 0
            and self.preview_execute_travel_target_outpost_name
        )

    def compare_current_inventory_against_preview(self) -> bool:
        """Compare live model counts with the preview snapshot and require drift confirmation.

        Any difference invalidates one-click execution until the user explicitly confirms the
        newly displayed drift; the stored plan itself is not silently rebuilt here.
        """

        self.clear_preview_inventory_diff()
        if not self.preview_ready:
            self.preview_inventory_diff_summary = "Run Preview before comparing inventory drift."
            return False
        if not self.preview_plan.inventory_snapshot_captured:
            self.preview_inventory_diff_summary = "This preview did not capture an inventory snapshot to compare."
            return False

        started_at = self._clock()
        current_items = self._collect_inventory()
        current_model_counts = self._get_model_counts()(current_items)
        self.last_preview_compare_duration_ms = max(0.0, (self._clock() - started_at) * 1000.0)

        preview_model_counts = dict(self.preview_plan.inventory_model_counts)
        changed_rows: list[tuple[int, str]] = []
        for model_id in sorted(set(preview_model_counts.keys()) | set(current_model_counts.keys())):
            preview_count = max(0, int(preview_model_counts.get(model_id, 0)))
            current_count = max(0, int(current_model_counts.get(model_id, 0)))
            if current_count == preview_count:
                continue
            delta = current_count - preview_count
            delta_prefix = "+" if delta > 0 else ""
            changed_rows.append(
                (
                    abs(delta),
                    f"{delta_prefix}{delta} {self._get_model_label()(model_id)} "
                    f"(now {current_count}, preview {preview_count})",
                )
            )

        if not changed_rows:
            self.preview_inventory_diff_summary = (
                f"Current inventory still matches the last preview snapshot across {len(current_items)} stack(s)."
            )
            self.execute_drift_requires_confirmation = False
            return True

        changed_rows.sort(key=lambda row: (-row[0], row[1].lower()))
        self.preview_inventory_diff_rows = [label for _weight, label in changed_rows[: self._read_diff_row_limit()]]
        total_changed = len(changed_rows)
        if total_changed > self._read_diff_row_limit():
            self.preview_inventory_diff_rows.append(
                f"...and {total_changed - self._read_diff_row_limit()} more changed model(s)."
            )
        self.preview_inventory_diff_summary = (
            f"Inventory changed since preview: {total_changed} model(s) differ from the last snapshot."
        )
        self.execute_drift_requires_confirmation = True
        return True

    def get_preview_unavailable_here_reason(
        self,
        entry: ExecutionPlanEntry,
        *,
        availability_here: dict[str, bool],
        plan: PlanResult,
    ) -> str:
        merchant_type = str(entry.merchant_type)
        action_type = str(entry.action_type)
        if merchant_type == _planning.MERCHANT_TYPE_TRAVEL or action_type == "travel":
            return ""
        if _planning.is_preview_entry_available_here(
            entry,
            availability_here=availability_here,
            plan=plan,
        ):
            return ""
        if merchant_type != _planning.MERCHANT_TYPE_INVENTORY and not bool(availability_here.get(merchant_type, False)):
            merchant_label = self._read_merchant_labels().get(merchant_type, merchant_type)
            return f"{merchant_label} not available here."
        if _planning.preview_entry_needs_local_storage_access(entry, plan=plan):
            return f"{self._read_merchant_labels()[_planning.MERCHANT_TYPE_STORAGE]} not available here."
        return "Not available here."

    def get_plan_local_action_labels(self, plan: PlanResult) -> list[str]:
        labels: list[str] = []
        if _planning.plan_has_local_identify_actions(plan):
            labels.append("local identify")
        if _planning.plan_has_local_salvage_actions(plan):
            labels.append("local salvage")
        if _planning.plan_has_local_destroy_actions(plan):
            labels.append("local destroy actions")
        if _planning.plan_has_local_storage_actions(plan):
            labels.append("Xunlai deposits")
        return labels

    def get_preview_state(self) -> tuple[str, PreviewTone, str]:
        actionable, skipped = _planning.split_preview_entries(self.preview_plan.entries)
        if self._read_busy():
            return (
                "Busy",
                "warning",
                "Preview, identify, salvage, deposits, storage scan, merchant automation, "
                "or execution is currently running.",
            )
        if self.preview_ready:
            if self.preview_plan.multi_stop_route:
                embark_label = self.preview_plan.multi_stop_consumable_outpost_name or self._embark_name()
                destination_label = self.preview_plan.multi_stop_destination_outpost_name
                detail = (
                    f"Preview routes Consumable Crafter buys through {embark_label}, "
                    f"then continues to {destination_label} for remaining work. "
                    "Execute Here runs only entries marked Ready now."
                    if destination_label
                    else (
                        f"Preview routes Consumable Crafter buys through {embark_label} and stops there. "
                        "Execute Here runs only entries marked Ready now."
                    )
                )
                if actionable:
                    return "Multi-stop", "info", detail
                if skipped:
                    return "Multi-stop", "muted", detail
                return "Multi-stop", "muted", detail
            if self.preview_has_execute_travel_pending():
                target_label = self.preview_execute_travel_target_outpost_name or "the selected outpost"
                detail = (
                    f"Preview is projected assuming Auto Travel reaches {target_label}. "
                    "Travel + Execute will travel, recheck current items and available services, then execute. "
                    "Execute Here runs only entries marked Ready now."
                )
                if actionable:
                    return "Projected", "info", detail
                if skipped:
                    return "Projected", "muted", detail
                return "Projected", "muted", detail
            if actionable:
                action_count = len(actionable)
                action_word = "action" if action_count == 1 else "actions"
                ready_verb = "is" if action_count == 1 else "are"
                return (
                    "Ready",
                    "success",
                    f"{action_count} {action_word} {ready_verb} ready in the current preview.",
                )
            if skipped:
                return "Ready", "muted", "Preview is current, but nothing will execute."
            return "Ready", "muted", "Preview is current."
        return "Stale", "warning", "Run Preview to refresh the current map and inventory state."

    def get_skipped_preview_status_key(
        self,
        entry: ExecutionPlanEntry,
        displayed_reason: str,
    ) -> str:
        return self._get_skipped_classifier()(entry)

    def get_preview_entry_status_key(
        self,
        entry: ExecutionPlanEntry,
        displayed_reason: str,
        *,
        is_conditional: bool,
        available_here: bool,
        unavailable_here_reason: str,
        muted: bool,
        plan: PlanResult | None = None,
    ) -> str:
        if muted:
            return self.get_skipped_preview_status_key(entry, displayed_reason)
        if str(entry.action_type) == "travel" or str(entry.merchant_type) == _planning.MERCHANT_TYPE_TRAVEL:
            return PREVIEW_STATUS_TRAVEL
        if is_conditional:
            if self.preview_has_execute_travel_pending() or bool(
                plan is not None and int(plan.travel_to_outpost_id) > 0
            ):
                return PREVIEW_STATUS_AFTER_TRAVEL
            if str(entry.merchant_type) == _planning.MERCHANT_TYPE_STORAGE:
                return PREVIEW_STATUS_NEEDS_XUNLAI
            return PREVIEW_STATUS_LIVE_CHECK
        if available_here:
            return PREVIEW_STATUS_READY
        if "xunlai" in str(unavailable_here_reason or "").lower():
            return PREVIEW_STATUS_NEEDS_XUNLAI
        if unavailable_here_reason:
            return PREVIEW_STATUS_AFTER_TRAVEL
        return PREVIEW_STATUS_READY

    def normalize_preview_entry_reason_display_text(
        self,
        entry: ExecutionPlanEntry,
        reason: str,
    ) -> str:
        reason = str(reason or "").strip()
        if not reason:
            return ""
        action_type = str(entry.action_type or "").strip().lower()
        state = str(entry.state or "").strip().lower()
        # Other actions never read merchant_type in the original formatter.
        is_consumable_crafter = (
            action_type == "buy" and str(entry.merchant_type) == _planning.MERCHANT_TYPE_CONSUMABLE_CRAFTER
        )
        return self._get_reason_formatter()(
            reason,
            action_type=action_type,
            is_skipped=state == _planning.PLAN_STATE_SKIPPED,
            will_execute=state == _planning.PLAN_STATE_WILL_EXECUTE,
            is_consumable_crafter=is_consumable_crafter,
        )

    def get_preview_reason_for_display(self, entry: ExecutionPlanEntry) -> str:
        reason = str(entry.reason or "").strip()
        if not reason:
            return ""
        if not self.preview_has_execute_travel_pending():
            return self.normalize_preview_entry_reason_display_text(entry, reason)

        target_outpost_name = self.preview_execute_travel_target_outpost_name or "the selected outpost"
        suffix = _planning.projected_preview_reason_suffix(
            entry.merchant_type, target_outpost_name, read_merchant_labels=self._read_merchant_labels
        )
        if not suffix:
            return self.normalize_preview_entry_reason_display_text(entry, reason)
        legacy_suffix = suffix.replace("Travel + Execute", "Execute") if suffix else ""
        if reason == suffix:
            return ""
        if legacy_suffix and reason == legacy_suffix:
            return ""
        spaced_suffix = f" {suffix}"
        if reason.endswith(spaced_suffix):
            return self.normalize_preview_entry_reason_display_text(entry, reason[: -len(spaced_suffix)].rstrip())
        if reason.endswith(suffix):
            return self.normalize_preview_entry_reason_display_text(entry, reason[: -len(suffix)].rstrip())
        if legacy_suffix:
            legacy_spaced_suffix = f" {legacy_suffix}"
            if reason.endswith(legacy_spaced_suffix):
                return self.normalize_preview_entry_reason_display_text(
                    entry,
                    reason[: -len(legacy_spaced_suffix)].rstrip(),
                )
            if reason.endswith(legacy_suffix):
                return self.normalize_preview_entry_reason_display_text(entry, reason[: -len(legacy_suffix)].rstrip())
        return self.normalize_preview_entry_reason_display_text(entry, reason)

    def should_show_preview_reason(
        self,
        entry: ExecutionPlanEntry,
        displayed_reason: str,
        *,
        show_reasons: bool = False,
        is_conditional: bool = False,
    ) -> bool:
        if not str(displayed_reason or "").strip():
            return False
        raw_reason = str(entry.reason or "").strip().lower()
        if str(entry.action_type) == "destroy" and str(entry.state) == _planning.PLAN_STATE_WILL_EXECUTE:
            return True
        if any(
            marker in raw_reason
            for marker in (
                "included protected item",
                "keep count requires splitting",
                "protected-item override",
                "permanently destroy",
            )
        ):
            return True
        return bool(show_reasons or is_conditional or self._read_detailed_preview())

    def group_preview_entries_by_action(
        self,
        entries: list[ExecutionPlanEntry],
    ) -> list[tuple[str, list[ExecutionPlanEntry]]]:
        grouped_entries: dict[str, list[ExecutionPlanEntry]] = {}
        action_order: list[str] = []
        for entry in entries:
            action_type = str(entry.action_type or "unknown")
            if action_type not in grouped_entries:
                grouped_entries[action_type] = []
                action_order.append(action_type)
            grouped_entries[action_type].append(entry)
        return [(action_type, grouped_entries[action_type]) for action_type in action_order]

    def get_not_changed_entry_status_key(self, entry: ExecutionPlanEntry) -> str:
        displayed_reason = self.get_preview_reason_for_display(entry)
        return self.get_skipped_preview_status_key(entry, displayed_reason)

    def get_visible_not_changed_entries(
        self,
        entries: list[ExecutionPlanEntry],
    ) -> list[ExecutionPlanEntry]:
        if not self._read_hide_already_done():
            return list(entries)
        return [
            entry for entry in entries if self.get_not_changed_entry_status_key(entry) != PREVIEW_STATUS_ALREADY_DONE
        ]

    def get_not_changed_status_counts(
        self,
        entries: list[ExecutionPlanEntry],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in entries:
            status_key = self.get_not_changed_entry_status_key(entry)
            counts[status_key] = counts.get(status_key, 0) + 1
        return counts

    def get_not_changed_group_default_open(
        self,
        entries: list[ExecutionPlanEntry],
    ) -> bool:
        if not entries or len(entries) >= 20:
            return False
        status_counts = self.get_not_changed_status_counts(entries)
        if set(status_counts).issubset({PREVIEW_STATUS_NO_MATCH, PREVIEW_STATUS_ALREADY_DONE}):
            return False
        attention_statuses = {
            PREVIEW_STATUS_UNSAFE,
            PREVIEW_STATUS_BLOCKED,
            PREVIEW_STATUS_PROTECTED,
            PREVIEW_STATUS_WARNING,
            PREVIEW_STATUS_SKIPPED,
        }
        return any(status_counts.get(status_key, 0) > 0 for status_key in attention_statuses)

    def get_not_changed_group_header_text(
        self,
        action_type: str,
        visible_entries: list[ExecutionPlanEntry],
        all_entries: list[ExecutionPlanEntry],
    ) -> tuple[str, str]:
        action_label = self._read_action_labels().get(action_type, action_type.title())
        visible_count = len(visible_entries)
        full_count = len(all_entries)
        count_text = str(visible_count) if visible_count == full_count else f"{visible_count} shown of {full_count}"
        status_counts = self.get_not_changed_status_counts(visible_entries)
        full_status_counts = self.get_not_changed_status_counts(all_entries)
        nonzero_statuses = [
            status_key for status_key in self._read_status_order() if status_counts.get(status_key, 0) > 0
        ]
        header_statuses = nonzero_statuses[:3]
        header_parts = [f"{action_label} ({count_text})"]
        header_parts.extend(
            f"{self._read_status_labels()[status_key]} {status_counts[status_key]}" for status_key in header_statuses
        )
        if len(nonzero_statuses) > len(header_statuses):
            header_parts.append(f"+{len(nonzero_statuses) - len(header_statuses)} more")

        tooltip_parts = [f"{action_label}: showing {visible_count} of {full_count} entries."]
        if nonzero_statuses:
            tooltip_parts.append(
                "Visible statuses: "
                + ", ".join(
                    f"{self._read_status_labels()[status_key]} {status_counts[status_key]}"
                    for status_key in nonzero_statuses
                )
                + "."
            )
        full_nonzero_statuses = [
            status_key for status_key in self._read_status_order() if full_status_counts.get(status_key, 0) > 0
        ]
        if visible_count != full_count and full_nonzero_statuses:
            tooltip_parts.append(
                "Full statuses: "
                + ", ".join(
                    f"{self._read_status_labels()[status_key]} {full_status_counts[status_key]}"
                    for status_key in full_nonzero_statuses
                )
                + "."
            )
        hidden_count = full_count - visible_count
        if hidden_count > 0:
            tooltip_parts.append(f"Hidden by Hide Already done: {hidden_count}.")
        return " | ".join(header_parts), " ".join(tooltip_parts)

    def build_remote_preview_summary(self) -> PreviewSummary:
        """Interpret the published preview without initialization or transport authority."""

        direct_count, conditional_count, skipped_count = _planning.get_preview_entry_counts(self.preview_plan.entries)
        actionable_count = direct_count + conditional_count
        local_identify_ready = _planning.plan_has_local_identify_actions(self.preview_plan)
        local_destroy_ready = _planning.plan_has_local_destroy_actions(self.preview_plan)
        local_salvage_ready = _planning.plan_has_local_salvage_actions(self.preview_plan)
        local_storage_ready = _planning.plan_has_local_storage_actions(self.preview_plan)
        local_action_labels = self.get_plan_local_action_labels(self.preview_plan)
        local_non_storage_ready = bool(local_identify_ready or local_salvage_ready or local_destroy_ready)
        conditional_cleanup_ready = _planning.plan_has_conditional_cleanup_actions(self.preview_plan)
        projected_preview = self.preview_has_execute_travel_pending()
        if actionable_count > 0:
            if projected_preview:
                status_label = "Projected"
            elif (
                not self.preview_plan.supported_map
                and local_destroy_ready
                and not local_identify_ready
                and not local_salvage_ready
                and not local_storage_ready
            ):
                status_label = "Destroy Ready"
            elif not self.preview_plan.supported_map and local_non_storage_ready:
                status_label = "Local Ready"
            else:
                status_label = "Conditional" if direct_count <= 0 and conditional_count > 0 else "Ready"
            summary_parts = [f"{actionable_count} can run", f"{skipped_count} blocked"]
            if conditional_count > 0:
                summary_parts.append(f"{conditional_count} need live checks")
            summary = ", ".join(summary_parts) + "."
        elif projected_preview:
            status_label = "No Actions"
            summary = "No actionable merchant work found."
        elif not self.preview_plan.supported_map:
            status_label = "Unsupported"
            summary = self.preview_plan.supported_reason or "Current map is not supported."
        else:
            status_label = "No Actions"
            summary = "No actionable merchant work found."

        if self.preview_plan.multi_stop_route:
            embark_label = self.preview_plan.multi_stop_consumable_outpost_name or self._embark_name()
            destination_label = self.preview_plan.multi_stop_destination_outpost_name
            detail_parts = [
                (
                    (
                        f"Multi-stop route: craft Consumable Crafter targets at {embark_label}, "
                        f"then travel to {destination_label} for remaining Merchant Rules work."
                    )
                    if destination_label
                    else f"Multi-stop route: craft Consumable Crafter targets at {embark_label} and stop there."
                )
            ]
            if _planning.plan_needs_exact_storage_scan(self.preview_plan):
                detail_parts.append(
                    "Storage-aware planning is still partial until Xunlai is opened for an exact storage scan."
                )
            elif conditional_cleanup_ready:
                detail_parts.append("Planned Xunlai cleanup work will execute if storage can be opened after arrival.")
            elif conditional_count > 0:
                detail_parts.append("Conditional entries remain estimated until each stop is confirmed.")
            detail = " ".join(detail_parts).strip()
        elif projected_preview:
            target_label = self.preview_execute_travel_target_outpost_name or "the selected outpost"
            detail_parts = [
                f"Projected after travel to {target_label}. Travel + Execute will auto-travel, "
                "recheck current items and available services, then execute.",
            ]
            if _planning.plan_needs_exact_storage_scan(self.preview_plan):
                detail_parts.append(
                    "Storage-aware rune planning is still partial until Xunlai is opened for an exact storage scan."
                )
            elif conditional_cleanup_ready:
                detail_parts.append("Planned Xunlai cleanup work will execute if storage can be opened after arrival.")
            elif conditional_count > 0:
                detail_parts.append("Conditional entries remain estimated until the destination context is confirmed.")
            detail = " ".join(detail_parts).strip()
        elif actionable_count > 0 and not self.preview_plan.supported_map and local_non_storage_ready:
            non_storage_labels = [label for label in local_action_labels if label != "Xunlai deposits"]
            detail = (
                "Merchant NPCs are unavailable here, but "
                f"{', '.join(non_storage_labels or local_action_labels)} can still run."
            )
            if conditional_cleanup_ready:
                detail = f"{detail} Planned Xunlai cleanup work will run if storage can be opened."
        elif actionable_count > 0 and not self.preview_plan.supported_map and local_storage_ready:
            detail = (
                "Merchant NPCs are unavailable here, but Xunlai cleanup work is still ready."
                if not conditional_cleanup_ready
                else (
                    "Merchant NPCs are unavailable here, but planned Xunlai cleanup work "
                    "will run if storage can be opened."
                )
            )
        elif not self.preview_plan.supported_map:
            detail = (
                self.preview_plan.supported_reason or self._read_status_message() or "Current map is not supported."
            )
        elif _planning.plan_needs_exact_storage_scan(self.preview_plan):
            detail = "Storage-aware planning is still partial until Xunlai is opened for an exact storage scan."
        elif conditional_cleanup_ready:
            detail = "Planned Xunlai cleanup work will execute if storage can be opened."
        elif conditional_count > 0:
            detail = "Some actions need a live merchant, trader, crafter, or Xunlai check before MR can confirm them."
        elif actionable_count > 0:
            detail = self._read_status_message() or self.preview_plan.supported_reason
        else:
            detail = self._read_status_message() or self.preview_plan.supported_reason or summary
        return PreviewSummary(
            primary_count=actionable_count,
            secondary_count=skipped_count,
            status_label=status_label,
            summary=summary,
            detail=detail,
        )

    def preview_uses_current_service_context(self) -> bool:
        return bool(
            self.preview_ready
            and not self.preview_requires_execute_travel
            and not bool(getattr(self.preview_plan, "multi_stop_route", False))
        )
