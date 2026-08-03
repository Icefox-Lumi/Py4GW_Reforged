from enum import IntEnum
from Py4GWCoreLib import Color
from Py4GWCoreLib import PyImGui
from datetime import datetime
from typing import Optional


#region Logconsole  
class LogConsole:
    class LogSeverity(IntEnum):
        INFO = 0
        WARNING = 1
        ERROR = 2
        CRITICAL = 3
        SUCCESS = 4

        def __str__(self):
            return self.name.capitalize()

        def to_color(self) -> 'Color':
            if self == self.INFO:
                return Color(255, 255, 255, 255)  # White
            elif self == self.WARNING:
                return Color(255, 255, 0, 255)    # Yellow
            elif self == self.ERROR:
                return Color(255, 0, 0, 255)      # Red
            elif self == self.CRITICAL:
                return Color(128, 0, 128, 255)    # Purple
            elif self == self.SUCCESS:
                return Color(0, 255, 0, 255)      # Green
            return Color(255, 255, 255, 255)      # Default

    class LogEntry:
        def __init__(self, message: str, extra_info: Optional[str],severity: Optional['LogConsole.LogSeverity'] = None):
            if severity is None:
                severity = LogConsole.LogSeverity.INFO
            self.message: str = message
            self.extra_info: str = extra_info if extra_info is not None else ""
            self.severity: LogConsole.LogSeverity = severity
            self.color: Color = severity.to_color()
            self.timestamp = datetime.now()

        def __str__(self):
            return f"[{self.severity}] {self.message}"

    def __init__(self, module_name="LogConsole", log_to_file: bool = False):
        self.messages: list[LogConsole.LogEntry] = []
        self.log_to_file: bool = log_to_file
        self.window_name = module_name
        self.window_flags = PyImGui.WindowFlags.AlwaysAutoResize
        
    def SetLogToFile(self, log_to_file: bool):
        """Set whether to log messages to a file."""
        self.log_to_file = log_to_file     
    
    def LogMessage(self, message: str, extra_info: Optional[str], severity: Optional['LogConsole.LogSeverity'] = None):
        """Add a new log entry to the console."""
        entry = LogConsole.LogEntry(message, extra_info, severity)
        self.messages.append(entry)

    def DrawConsole(self):
        """Draw the log console window."""
        visible, _ = PyImGui.begin(self.window_name, None, self.window_flags)
        if visible:
            if PyImGui.begin_child("Log Messages", (0, 0), True, PyImGui.WindowFlags.AlwaysVerticalScrollbar):
                if PyImGui.begin_table("LogTable", 3, PyImGui.TableFlags.RowBg | PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.Borders):
                    PyImGui.table_setup_column("Time", PyImGui.TableColumnFlags.WidthFixed, 75)
                    PyImGui.table_setup_column("Message", PyImGui.TableColumnFlags.WidthFixed, 150)
                    PyImGui.table_setup_column("Reason", PyImGui.TableColumnFlags.WidthStretch)
                    PyImGui.table_headers_row()
                    for message in reversed(self.messages):
                        PyImGui.table_next_row()
                        PyImGui.table_set_column_index(0)
                        PyImGui.text(f"{message.timestamp.strftime('%H:%M:%S')}")
                        
                        PyImGui.table_set_column_index(1)
                        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, message.color.to_tuple_normalized())
                        PyImGui.text_wrapped(message.message)
                        PyImGui.table_set_column_index(2)
                        PyImGui.text_wrapped(message.extra_info)
                        PyImGui.pop_style_color(1)
                    PyImGui.end_table()
                PyImGui.end_child()
        PyImGui.end()

    
    
#endregion
