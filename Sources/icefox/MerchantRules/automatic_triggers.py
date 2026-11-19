"""Per-widget automatic work requests and entry latches for Merchant Rules."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.configuration import IdentifySettings
    from Sources.icefox.MerchantRules.configuration import SalvageRule
    from Sources.icefox.MerchantRules.configuration import SalvageSettings


class AutomaticTriggerRuntime(Protocol):
    """Live observations and the five existing admission paths."""

    @property
    def current_triggers(self) -> AutomaticTriggers: ...

    def identify_settings(self) -> IdentifySettings: ...

    def salvage_settings(self) -> SalvageSettings: ...

    def salvage_rule_has_selectors(self, rule: SalvageRule) -> bool: ...

    def destroy_auto_enabled(self) -> bool: ...

    @property
    def auto_cleanup_on_outpost_entry(self) -> bool: ...

    @property
    def gold_balance_enabled(self) -> bool: ...

    @property
    def gold_balance_on_outpost_entry(self) -> bool: ...

    @property
    def execution_running(self) -> bool: ...

    @property
    def travel_preview_running(self) -> bool: ...

    @property
    def identify_running(self) -> bool: ...

    @property
    def instant_destroy_running(self) -> bool: ...

    @property
    def salvage_running(self) -> bool: ...

    @property
    def storage_scan_running(self) -> bool: ...

    @property
    def auto_cleanup_running(self) -> bool: ...

    @property
    def gold_balance_running(self) -> bool: ...

    @property
    def manual_vendor_running(self) -> bool: ...

    def refresh_lifecycle(self) -> None: ...

    def lifecycle_block_reason(self) -> str: ...

    def service_block_reason(self) -> str: ...

    def has_pending_work(self) -> bool: ...

    def has_cleanup_sources(self) -> bool: ...

    def is_outpost(self) -> bool: ...

    def is_guild_hall(self) -> bool: ...

    def inventory_signature(self) -> tuple[tuple[int, int], ...]: ...

    def identify_poll_expired(self) -> bool: ...

    def reset_identify_poll(self) -> None: ...

    def salvage_poll_expired(self) -> bool: ...

    def reset_salvage_poll(self) -> None: ...

    def instant_destroy_poll_expired(self) -> bool: ...

    def reset_instant_destroy_poll(self) -> None: ...

    def submit_identify(self) -> None: ...

    def submit_salvage(self) -> None: ...

    def submit_cleanup(self) -> None: ...

    def submit_gold(self) -> None: ...

    def submit_destroy(self) -> None: ...


class AutomaticTriggers:
    """Own automatic eligibility decisions and transient requests for one widget."""

    def __init__(self, runtime: AutomaticTriggerRuntime) -> None:
        self._runtime = runtime
        self.auto_cleanup_zone_attempted: bool = False
        self.auto_cleanup_zone_token: str = ""
        self.gold_entry_attempted: bool = False
        self.gold_entry_zone_token: str = ""
        self.instant_destroy_rescan_requested: bool = False
        self.instant_destroy_last_signature: tuple[tuple[int, int], ...] = ()
        self.salvage_rescan_requested: bool = False
        self.salvage_last_signature: tuple[tuple[int, int], ...] = ()
        self.identify_rescan_requested: bool = False
        self.identify_last_signature: tuple[tuple[int, int], ...] = ()

    def update_auto_cleanup_runtime(self) -> None:
        runtime = self._runtime
        if not runtime.auto_cleanup_on_outpost_entry:
            return
        # _tick_runtime refreshes lifecycle state before observers and resets this latch on transitions.
        if runtime.current_triggers.auto_cleanup_zone_attempted:
            return

        runtime.refresh_lifecycle()
        if runtime.service_block_reason():
            return
        if runtime.has_pending_work():
            return
        if not runtime.has_cleanup_sources():
            return
        if not (runtime.is_outpost() or runtime.is_guild_hall()):
            return
        if (
            runtime.execution_running
            or runtime.travel_preview_running
            or runtime.identify_running
            or runtime.instant_destroy_running
            or runtime.salvage_running
            or runtime.storage_scan_running
            or runtime.auto_cleanup_running
            or runtime.manual_vendor_running
        ):
            return
        runtime.current_triggers.auto_cleanup_zone_attempted = True
        runtime.submit_cleanup()

    def update_auto_gold_runtime(self) -> None:
        runtime = self._runtime
        if not runtime.gold_balance_enabled or not runtime.gold_balance_on_outpost_entry:
            return
        # _tick_runtime refreshes lifecycle state before observers and resets this latch on transitions.
        if runtime.current_triggers.gold_entry_attempted:
            return

        runtime.refresh_lifecycle()
        if runtime.service_block_reason():
            return
        if not (runtime.is_outpost() or runtime.is_guild_hall()):
            return
        if runtime.has_pending_work():
            return
        if (
            runtime.execution_running
            or runtime.travel_preview_running
            or runtime.identify_running
            or runtime.instant_destroy_running
            or runtime.salvage_running
            or runtime.storage_scan_running
            or runtime.auto_cleanup_running
            or runtime.gold_balance_running
            or runtime.manual_vendor_running
        ):
            return
        runtime.current_triggers.gold_entry_attempted = True
        try:
            runtime.submit_gold()
        except Exception:
            runtime.current_triggers.gold_entry_attempted = False
            raise

    def clear_inventory_monitor_signatures(self) -> None:
        self.identify_last_signature = ()
        self.salvage_last_signature = ()
        self.instant_destroy_last_signature = ()

    def request_identify_rescan(self) -> None:
        self.identify_rescan_requested = True

    def update_identify_runtime(self) -> None:
        runtime = self._runtime
        settings = runtime.identify_settings()
        if not bool(settings.on_inventory_change) or not any(bool(value) for value in settings.rarities.values()):
            runtime.current_triggers.identify_rescan_requested = False
            return

        should_rescan = bool(runtime.current_triggers.identify_rescan_requested)
        if not should_rescan and not runtime.identify_poll_expired():
            return

        runtime.refresh_lifecycle()
        if runtime.lifecycle_block_reason():
            return
        if runtime.has_pending_work():
            return
        if (
            runtime.execution_running
            or runtime.travel_preview_running
            or runtime.identify_running
            or runtime.instant_destroy_running
            or runtime.salvage_running
            or runtime.storage_scan_running
            or runtime.auto_cleanup_running
            or runtime.gold_balance_running
            or runtime.manual_vendor_running
        ):
            return

        current_signature = runtime.inventory_signature()
        runtime.reset_identify_poll()
        if not should_rescan and current_signature == runtime.current_triggers.identify_last_signature:
            return

        runtime.current_triggers.identify_rescan_requested = False
        runtime.submit_identify()

    def request_salvage_rescan(self) -> None:
        self.salvage_rescan_requested = True

    def update_salvage_runtime(self) -> None:
        runtime = self._runtime
        settings = runtime.salvage_settings()
        if not bool(settings.on_inventory_change) or not any(
            bool(rule.enabled) and runtime.salvage_rule_has_selectors(rule) for rule in settings.rules
        ):
            runtime.current_triggers.salvage_rescan_requested = False
            return

        should_rescan = bool(runtime.current_triggers.salvage_rescan_requested)
        if not should_rescan and not runtime.salvage_poll_expired():
            return

        runtime.refresh_lifecycle()
        if runtime.lifecycle_block_reason():
            return
        if runtime.has_pending_work():
            return
        if (
            runtime.execution_running
            or runtime.travel_preview_running
            or runtime.identify_running
            or runtime.instant_destroy_running
            or runtime.salvage_running
            or runtime.storage_scan_running
            or runtime.auto_cleanup_running
            or runtime.manual_vendor_running
        ):
            return

        current_signature = runtime.inventory_signature()
        runtime.reset_salvage_poll()
        if not should_rescan and current_signature == runtime.current_triggers.salvage_last_signature:
            return

        runtime.current_triggers.salvage_rescan_requested = False
        runtime.submit_salvage()

    def request_instant_destroy_rescan(self) -> None:
        self.instant_destroy_rescan_requested = True

    def update_instant_destroy_runtime(self) -> None:
        runtime = self._runtime
        if not runtime.destroy_auto_enabled():
            runtime.current_triggers.instant_destroy_rescan_requested = False
            return

        should_rescan = bool(runtime.current_triggers.instant_destroy_rescan_requested)
        if not should_rescan and not runtime.instant_destroy_poll_expired():
            return

        runtime.refresh_lifecycle()
        if runtime.lifecycle_block_reason():
            return
        if runtime.has_pending_work():
            return
        if (
            runtime.execution_running
            or runtime.travel_preview_running
            or runtime.identify_running
            or runtime.instant_destroy_running
            or runtime.salvage_running
            or runtime.storage_scan_running
            or runtime.auto_cleanup_running
            or runtime.manual_vendor_running
        ):
            return

        current_signature = runtime.inventory_signature()
        runtime.reset_instant_destroy_poll()
        if not should_rescan and current_signature == runtime.current_triggers.instant_destroy_last_signature:
            return

        runtime.current_triggers.instant_destroy_rescan_requested = False
        runtime.submit_destroy()
