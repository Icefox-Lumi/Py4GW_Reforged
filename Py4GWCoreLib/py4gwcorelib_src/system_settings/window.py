"""System Settings-specific SidebarWindow facade."""

from typing import Optional

from Py4GWCoreLib import ImGui
import PyImGui

from .account_copy import draw_copy_header
from .account_copy import get_copy_service


class SystemSettingsWindow(ImGui.SidebarWindow):
    """SidebarWindow with an inherited account-copy header for private sections."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._account_setting_ids_by_section: dict[str, str] = {}

    @staticmethod
    def _guarded(setting_id: str, context):
        def _draw():
            if get_copy_service().is_setting_locked(setting_id):
                PyImGui.text_colored(
                    "This setting is being updated from another loaded account.",
                    (0.60, 0.60, 0.65, 1.0),
                )
                return
            context()

        return _draw

    def add_account_section(
        self,
        group,
        setting_id: str,
        name: str,
        context=None,
        *,
        tabs=None,
        help: Optional[str] = None,
        help_file: Optional[str] = None,
        icon: str = "",
        default: bool = False,
    ):
        self._account_setting_ids_by_section[name] = setting_id
        guarded_context = self._guarded(setting_id, context) if context is not None else None
        return self.add_section(
            group,
            name,
            guarded_context,
            tabs=tabs,
            help=help,
            help_file=help_file,
            icon=icon,
            default=default,
            header=lambda sid=setting_id: draw_copy_header(sid),
        )

    def add_tab(self, section, name: str, context, **kwargs):
        section_name = section.name if isinstance(section, ImGui.SidebarWindow.Section) else str(section)
        setting_id = self._account_setting_ids_by_section.get(section_name)
        guarded_context = self._guarded(setting_id, context) if setting_id else context
        return super().add_tab(section, name, guarded_context, **kwargs)
