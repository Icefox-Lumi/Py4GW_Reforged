from typing import Optional
import Py4GW
import PyImGui
import PySystem

from Py4GWCoreLib import Timer, UIManager
from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import ImGui
from Py4GWCoreLib import ThemeTextures
from Py4GWCoreLib import Style
from Py4GWCoreLib import Map
from Py4GWCoreLib import IconsFontAwesome5
from Py4GWCoreLib import Color, ColorPalette
from Py4GWCoreLib import JsonFactory

from Py4GWCoreLib.ImGui_src.types import Alignment
from Py4GWCoreLib.Py4GWcorelib import ConsoleLog, ThrottledTimer, Utils
from Py4GWCoreLib.enums import Key
from Py4GWCoreLib.py4gwcorelib_src.WidgetManager import Widget, WidgetHandler, get_widget_handler
MODULE_NAME = "Travel"

_cfg = JsonFactory("Widgets/Travel.json")  # account scope; self-persisting

save_throttle_time = 1000
save_throttle_timer = Timer()
save_throttle_timer.Start()

game_throttle_time = 50
game_throttle_timer = Timer()
game_throttle_timer.Start()

click_timer = ThrottledTimer(125)
click_timer.Start()

MODULE_ICON = "Textures\\Module_Icons\\travel_cursor.png"
class Config:
    global MODULE_NAME
    def __init__(self):
        self.show_travel_history : bool = True
        self.history_length : int = 5
        self.favorites : list[int] = []
        self.show_favorites : bool = True
        self.save_requested : bool = False
        self.close_after_travel : bool = True
    
    def load(self):
        # Load the configuration from the jailed JSON document (self-persisting).
        self.favorites = _cfg.get_json("favorites", [])
        self.show_travel_history = _cfg.get_bool("show_travel_history", True)
        self.show_favorites = _cfg.get_bool("show_favorites", True)
        self.history_length = _cfg.get_int("history_length", 5)
        self.close_after_travel = _cfg.get_bool("close_after_travel", True)

    def save(self):
        # Write into the jailed JSON document; autosaved on a debounce.
        _cfg.set_json("favorites", list(self.favorites))
        _cfg.set_bool("show_travel_history", self.show_travel_history)
        _cfg.set_bool("show_favorites", self.show_favorites)
        _cfg.set_int("history_length", self.history_length)
        _cfg.set_bool("close_after_travel", self.close_after_travel)

        self.save_requested = False
            
    def request_save(self):
        self.save_requested = True


widget_config = Config()
widget_config.load()

new_favorite = 0
travel_window_open = False
config_window_open = False
TRAVEL_BUTTON_SIZE = 48.0
outposts = dict(zip(Map.GetOutpostIDs(), Map.GetOutpostNames()))
outposts = {id: outpost.replace("outpost", "") for id, outpost in outposts.items() if outpost}  # Filter out empty names
outpost_index = 0
filtered_outposts = [(id, outpost) for id, outpost in outposts.items()]
filtered_history = []
search_outpost = ""
is_traveling = False
is_map_ready = False
is_party_loaded = False
travel_history = []
priority_outposts = {
    194 : "Kaineng Center",
    817 : "Kaineng Center",
    857 : "Embark Beach",
    449 : "Kamadan Jewel of Istan",
    818 : "Kamadan Jewel of Istan",
    819 : "Kamadan Jewel of Istan",
    642 : "Eye of the North",
    821 : "Eye of the North",
}

outpost_aliases = {
    474: ["doa", "domain of anguish"],
}

widget_handler : WidgetHandler = get_widget_handler()
widget_info : Optional[Widget] = None

def tooltip():
    PyImGui.set_next_window_size((600, 0))
    PyImGui.begin_tooltip()
    # Title
    title_color = Color(255, 200, 100, 255)
    ImGui.image(MODULE_ICON, (32, 32))
    PyImGui.same_line(0, 10)
    ImGui.push_font("Regular", 20)
    ImGui.text_aligned(MODULE_NAME, alignment=Alignment.MidLeft, color=title_color.color_tuple, height=32)
    ImGui.pop_font()
    PyImGui.spacing()
    PyImGui.spacing()
    PyImGui.separator()
    # Description
    #ellaborate a better description 
    PyImGui.text("This widget provides a comprehensive interface")
    PyImGui.text("for traveling to outposts within the game.")
    PyImGui.text("Features include searching for outposts,")
    PyImGui.text("maintaining a travel history, and")
    PyImGui.text("managing favorite outposts for quick access.")
    PyImGui.spacing()
    
    # Features
    PyImGui.text_colored("Features:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Search for outposts by name or initials.")
    PyImGui.bullet_text("Travel to the highlighted outpost by pressing Enter.")
    PyImGui.bullet_text("Travel history shows the last 5 outposts you traveled to.")
    PyImGui.bullet_text("Mark or unmark outposts as favorites with Shift + Left Click.")
    PyImGui.spacing()
    # Credits
    PyImGui.text_colored("Credits:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Developed by frenkey")
    
    PyImGui.end_tooltip()

def configure():
    global widget_config, config_window_open, new_favorite, widget_info, widget_handler
    global MODULE_NAME
    
    if widget_info is None:
        widget_info = widget_handler.get_widget_info(MODULE_NAME)
    
    config_window_open = True
    visible, config_window_open = PyImGui.begin_with_close(
        "Travel##config", config_window_open, PyImGui.WindowFlags.AlwaysAutoResize
    )
    if visible:
        
        
        if PyImGui.begin_tab_bar("##TravelConfigTabs"):                
            if PyImGui.begin_tab_item("Favorites"):
                show_favorites = ImGui.checkbox("Show Favorites on Travel Window", widget_config.show_favorites)
                if show_favorites != widget_config.show_favorites:
                    widget_config.show_favorites = show_favorites
                    widget_config.request_save()
                    
                PyImGui.spacing()
                PyImGui.separator()
                PyImGui.spacing()
                
                outpost_items = {id: f"{outpost} ({id})" for id, outpost in outposts.items() if outpost}
                #sort outpost_items by name
                outpost_items = dict(sorted(outpost_items.items(), key=lambda item: item[1].lower()))
                
                outpost_ids = list(outpost_items.keys())
                outpost_names = list(outpost_items.values())
                PyImGui.push_item_width(300)
                new_favorite = PyImGui.combo("##NewFavorite", new_favorite, outpost_names)
                PyImGui.same_line(0, 5)
                if ImGui.button("Add Favorite", 150):
                    if new_favorite >= 0 and new_favorite < len(outposts):
                        id = outpost_ids[new_favorite]
                        
                        if id not in widget_config.favorites:
                            widget_config.favorites.append(id)
                            widget_config.request_save()
                            
                PyImGui.spacing()
                PyImGui.separator()
                PyImGui.spacing()
                if widget_config.favorites:
                    if PyImGui.begin_table("##FavoritesTable", 4, PyImGui.TableFlags.NoBordersInBody, 0, 0):
                        PyImGui.table_setup_column(f"Number", PyImGui.TableColumnFlags.WidthFixed, 25)
                        PyImGui.table_setup_column(f"Outpost", PyImGui.TableColumnFlags.WidthStretch, 0)
                        PyImGui.table_setup_column(f"Id", PyImGui.TableColumnFlags.WidthFixed, 50)
                        PyImGui.table_setup_column(f"Action", PyImGui.TableColumnFlags.WidthFixed, 75)
                        
                        PyImGui.table_next_row()
                        PyImGui.table_next_column()

                        for (i, id) in enumerate(widget_config.favorites):
                            outpost = outposts.get(id)
                            
                            if outpost:
                                PyImGui.set_cursor_pos_y(PyImGui.get_cursor_pos_y() + 5)
                                PyImGui.text(f"{i + 1}")
                                PyImGui.table_next_column()
                                
                                PyImGui.set_cursor_pos_y(PyImGui.get_cursor_pos_y() + 5)
                                PyImGui.text(outpost)
                                PyImGui.table_next_column()
                                
                                PyImGui.set_cursor_pos_y(PyImGui.get_cursor_pos_y() + 5)
                                PyImGui.text(f"{id}")
                                PyImGui.table_next_column()
                                
                                if ImGui.button(f"Remove##{id}", 75, 25):
                                    widget_config.favorites.remove(id)
                                    widget_config.request_save()
                                    
                                PyImGui.table_next_column()
                                ImGui.show_tooltip(f"{outpost} ({id})")
                            else:
                                PySystem.Console.Log(MODULE_NAME, f"Favorite outpost {id} not found in outposts.", PySystem.Console.MessageType.Warning)
                                
                        PyImGui.end_table()
                            
                PyImGui.end_tab_item()
            
            if PyImGui.begin_tab_item("General"):
                show_history = ImGui.checkbox("Show Travel History on Travel Window", widget_config.show_travel_history)
                if show_history != widget_config.show_travel_history:
                    widget_config.show_travel_history = show_history
                    widget_config.request_save()
                
                ImGui.text_aligned(f"Travel History Length ({widget_config.history_length})", width=100, height=24, alignment=Alignment.MidLeft)
                PyImGui.same_line(0, 2)
                history_length = ImGui.slider_int(f"##Travel History Length", widget_config.history_length, 1, 20)
                if history_length != widget_config.history_length:
                    widget_config.history_length = max(1, min(20, history_length))
                    widget_config.request_save()
                
                PyImGui.end_tab_item()
                
            if PyImGui.begin_tab_item("Help"):
                PyImGui.dummy((455, 0))
                PyImGui.text("Outpost Travel Configuration")
                PyImGui.separator()
                PyImGui.text("This widget allows you to travel to outposts.")
                PyImGui.bullet_text("search for outposts by name or initials")
                PyImGui.bullet_text("travel to the highlighted outpost by pressing Enter")
                PyImGui.bullet_text("travel history shows the last 5 outposts you traveled to.")
                PyImGui.bullet_text("mark or unmark outposts as favorites with Shift + Left Click")
                PyImGui.end_tab_item()
            PyImGui.end_tab_bar()  
        
    PyImGui.end()
    
    if not config_window_open:
        if widget_info and widget_info.configuring:
            widget_handler.set_widget_configuring(MODULE_NAME, False)

        pass

def themed_floating_button(button_rect : tuple[float, float, float, float]):
    match(ImGui.get_style().Theme):
        case Style.StyleTheme.Guild_Wars:
            ThemeTextures.Button_Background.value.get_texture().draw_in_drawlist(
                button_rect[:2], 
                button_rect[2:],
                tint=(255, 255, 255, 255) if ImGui.is_mouse_in_rect(button_rect) else (200, 200, 200, 255),
            )
            
            ThemeTextures.Button_Frame.value.get_texture().draw_in_drawlist(
                button_rect[:2], 
                button_rect[2:],
                tint=(255, 255, 255, 255) if ImGui.is_mouse_in_rect(button_rect) else (200, 200, 200, 255),
            )
            
        case Style.StyleTheme.Minimalus:
            PyImGui.draw_list_add_rect_filled(
                button_rect[0] + 1,
                button_rect[1] + 1,
                button_rect[0] + button_rect[2] -1,
                button_rect[1] + button_rect[3] -1,
                Utils.RGBToColor(48, 48, 48, 150) if ImGui.is_mouse_in_rect(button_rect) else Utils.RGBToColor(0, 0, 0, 150),
                0,
                0,
            )   
            
            PyImGui.draw_list_add_rect(
                button_rect[0] + 1,
                button_rect[1] + 1,
                button_rect[0] + button_rect[2] -1,
                button_rect[1] + button_rect[3] -1,
                Utils.RGBToColor(255, 255, 255, 75) if ImGui.is_mouse_in_rect(button_rect) else Utils.RGBToColor(200, 200, 200, 50),
                0,
                0,
                1,
            )            
            
            pass
        
        case Style.StyleTheme.Py4GW:
            PyImGui.draw_list_add_rect_filled(
                button_rect[0] + 1,
                button_rect[1] + 1,
                button_rect[0] + button_rect[2] -1,
                button_rect[1] + button_rect[3] -1,
                Utils.RGBToColor(51, 76, 102, 255) if ImGui.is_mouse_in_rect(button_rect) else Utils.RGBToColor(26, 38, 51, 255),
                4,
                0,
            )   
            
            PyImGui.draw_list_add_rect(
                button_rect[0] + 1,
                button_rect[1] + 1,
                button_rect[0] + button_rect[2] -1,
                button_rect[1] + button_rect[3] -1,
                Utils.RGBToColor(204, 204, 212, 50),
                4,
                0,
                1,
            )
            pass

def DrawWindow():
    global is_traveling, widget_config, search_outpost, travel_window_open, filtered_outposts, outpost_index, filtered_history
    global game_throttle_time, game_throttle_timer, save_throttle_time, save_throttle_timer
    
    try:    
        show_ui = not UIManager.IsWorldMapShowing() and not Map.IsMapLoading() and not Map.IsInCinematic() and not Map.Pregame.InCharacterSelectScreen()
        
        if not show_ui:
            return
        
        padding = TRAVEL_BUTTON_SIZE * 0.05
        style = ImGui.get_style()
        io = PyImGui.get_io()
        button_rect = (0.0, 0.0, TRAVEL_BUTTON_SIZE, TRAVEL_BUTTON_SIZE)
        PyImGui.set_next_window_size((TRAVEL_BUTTON_SIZE, TRAVEL_BUTTON_SIZE), PyImGui.ImGuiCond.FirstUseEver)
        style.WindowPadding.push_style_var_direct(padding, padding)
        win_open = PyImGui.begin("##TravelButton", PyImGui.WindowFlags.NoTitleBar | PyImGui.WindowFlags.NoResize | PyImGui.WindowFlags.NoScrollbar)
        style.WindowPadding.pop_style_var_direct()
        if not win_open:
            PyImGui.end()
            return

        if win_open:
            button_pos = PyImGui.get_window_pos()
            actual_button_size = PyImGui.get_window_size()
            button_rect = (button_pos[0], button_pos[1], actual_button_size[0], actual_button_size[1])
            is_hovered = ImGui.is_mouse_in_rect(button_rect)
            button_size = PyImGui.get_content_region_avail()[0] * (1 if is_hovered else 0.8)
            
            icon_rect = (button_rect[0] + (button_rect[2] - button_size) / 2, button_rect[1] + (button_rect[3] - button_size) / 2, button_size, button_size)

            ThemeTextures.TravelCursor.value.get_texture().draw_in_drawlist(
                icon_rect[:2],
                icon_rect[2:],
            )
            
            PyImGui.invisible_button("##Open Travel Window", (button_rect[2], button_rect[3]))

            item_hovered = PyImGui.is_item_hovered()

            if item_hovered and PyImGui.is_mouse_released(0):
                travel_window_open = not travel_window_open

            ImGui.show_tooltip("Click to open travel window")
            
            PyImGui.end()
        
        if not travel_window_open:
            return
        
        traveled = False
        expanded, travel_window_open = PyImGui.begin_with_close(
            "Travel", travel_window_open, PyImGui.WindowFlags.AlwaysAutoResize
        )
        if expanded:
            search_focused = False
            
            style = ImGui.get_style()
            
            if widget_config.favorites and widget_config.show_favorites:
                if PyImGui.is_rect_visible((0, 20)):
                    columns = min(len(widget_config.favorites), 4)
                    if PyImGui.begin_table("##Favorites", columns, PyImGui.TableFlags.NoBordersInBody, 0, 0):
                        for i in range(columns):
                            PyImGui.table_setup_column(f"Column {i}", PyImGui.TableColumnFlags.WidthStretch, 0)
                            
                        
                        for id in widget_config.favorites:
                            outpost = outposts.get(id)
                            
                            if outpost:
                                PyImGui.table_next_column()
                                if ImGui.button(generate_initials(outpost), PyImGui.get_content_region_avail()[0], 25):
                                    click_select_outpost(io, id, 0)
                                    traveled = True
                            
                                
                                ImGui.show_tooltip(f"{outpost} ({id})")
                            else:
                                PySystem.Console.Log(MODULE_NAME, f"Favorite outpost {id} not found in outposts.", PySystem.Console.MessageType.Warning)
                                
                        PyImGui.end_table()
                
                PyImGui.separator()

            PyImGui.push_item_width(250)
            changed, search = ImGui.search_field("##Search Outpost", search_outpost, "Search ...", PyImGui.InputTextFlags.AutoSelectAll)
            if changed and search != search_outpost:
                search_outpost = search                
                search = search_outpost.lower()
                
                filtered_outposts = [(id, outpost) for id, outpost in outposts.items() if not search or search in outpost.lower() or search in generate_initials(outpost).lower() or any(search in alias for alias in outpost_aliases.get(id, []))]
                ## filter priority outposts to the top then alphabetically                
                # filtered_outposts = sorted(filtered_outposts, key=lambda item: item[1].lower())                
                filtered_outposts.sort(key=lambda item: (0 if item[0] in priority_outposts else 1, priority_outposts.get(item[0], ""), item[1].lower()))
                
                filtered_history = [(id, outpost) for id, outpost in travel_history if not search or search in outpost.lower() or search in generate_initials(outpost).lower()] if widget_config.show_travel_history else []
                
                outpost_index = 0
            
            if PyImGui.is_window_appearing():
                PyImGui.set_keyboard_focus_here(-1)
            
            search_focused = PyImGui.is_item_active() or PyImGui.is_item_focused()    
          
            items_height = max(1, min(300, ((len(filtered_outposts) * 20 if search else 0) + (len(filtered_history) * 20 + (20 if search and filtered_outposts else 0) if filtered_history else 0))))
            if items_height > 1:
                PyImGui.spacing()
            
                if PyImGui.begin_child("##OutpostList", (0, items_height), False, PyImGui.WindowFlags.NoFlag):                                
                    travel_history_len = len(filtered_history)
                    ImGui.push_font("Italic", 12)
                    PyImGui.indent(10)
                    
                    for i, (id, outpost) in enumerate(filtered_history):
                        is_selected = i == outpost_index                        
                        
                        y = PyImGui.get_cursor_pos_y()
                        x = PyImGui.get_cursor_pos_x()
                        
                        ImGui.push_font("Regular", 8)
                        PyImGui.set_cursor_pos_y(y + 2)
                        ImGui.text(IconsFontAwesome5.ICON_HISTORY)
                        ImGui.pop_font()
                        
                        PyImGui.set_cursor_pos((x + 20, y))
                        
                        ImGui.selectable(outpost + f" ({id})", is_selected, PyImGui.SelectableFlags.NoFlag, (0, 0))
                        if PyImGui.is_item_clicked(0) or (is_selected and PyImGui.is_key_pressed(Key.Enter.value)):
                            ConsoleLog(MODULE_NAME, f"Traveling to outpost {outpost} ({id}) from history.", PySystem.Console.MessageType.Info)
                            click_select_outpost(io, id, i)
                            traveled = True
                            
                        is_favorite = id in widget_config.favorites
                        ImGui.show_tooltip(f"Travel to {outpost} ({id})\n\n{("Add as favorite with Shift + Left Click" if not is_favorite else "Remove from favorites with Shift + Left Click")}")
                                                                                       
                        if is_selected:
                            PyImGui.set_scroll_here_y(0.5)
                            
                    ImGui.pop_font()
                    
                    if filtered_history and search and filtered_outposts:
                        PyImGui.spacing()
                        PyImGui.separator()
                        PyImGui.spacing()
                    
                    PyImGui.unindent(10)
                    
                    ImGui.push_font("Regular", 14)
                    if filtered_outposts and search:
                        for i in range(travel_history_len, len(filtered_outposts) + travel_history_len):
                            id, outpost = filtered_outposts[i - travel_history_len]

                            is_selected = i == outpost_index
                            ImGui.selectable(outpost + f" ({id})", is_selected, PyImGui.SelectableFlags.NoFlag, (0, 0))
                            if PyImGui.is_item_clicked(0) or (is_selected and PyImGui.is_key_pressed(Key.Enter.value)):
                                ConsoleLog(MODULE_NAME, f"Traveling to outpost {outpost} ({id}) from search results.", PySystem.Console.MessageType.Info)
                                click_select_outpost(io, id, i)                                
                                traveled = True
                            
                            is_favorite = id in widget_config.favorites
                            ImGui.show_tooltip(f"Travel to {outpost}\n\n{("Add as favorite with Shift + Left Click" if not is_favorite else "Remove from favorites with Shift + Left Click")}")
                                    
                            if is_selected:
                                PyImGui.set_scroll_here_y(0.5)
                                
                    
                    
                    ImGui.pop_font()
        
                    if click_timer.IsExpired():
                        max_index = (len(filtered_outposts) if search and filtered_outposts else 0) + travel_history_len - 1
                        
                        if max_index < 0:
                            max_index = 0
                        
                        if PyImGui.is_key_down(Key.DownArrow.value):
                            if outpost_index < max_index:
                                outpost_index += 1
                                click_timer.Reset()
                                
                        elif PyImGui.is_key_down(Key.UpArrow.value):
                            if outpost_index > 0:
                                outpost_index -= 1
                                click_timer.Reset()
                                
                                
                PyImGui.end_child()
                                
            if PyImGui.is_mouse_clicked(0):
                window_pos = PyImGui.get_window_pos()
                window_size = PyImGui.get_window_size()
                window_rect = (window_pos[0], window_pos[1], window_size[0], window_size[1])
                if not ImGui.is_mouse_in_rect(button_rect) and not ImGui.is_mouse_in_rect(window_rect):
                    travel_window_open = False
                                 
                                   
                
        PyImGui.end()
        

        if save_throttle_timer.HasElapsed(save_throttle_time):
            save_throttle_timer.Reset()
            
            if widget_config.save_requested:
                widget_config.save()
            

    except Exception as e:
        is_traveling = False
        PySystem.Console.Log(MODULE_NAME, f"Error in DrawWindow: {str(e)}", PySystem.Console.MessageType.Debug)

def generate_initials(name):
    return ''.join(word[0] for word in name.split() if word)
                
def click_select_outpost(io : PyImGui.ImGuiIO, id, i):
    global widget_config, outpost_index, travel_history, filtered_history
    
    if io.key_shift:
        if id not in widget_config.favorites:
            widget_config.favorites.append(id)
            widget_config.request_save()
        else:
            widget_config.favorites.remove(id)
            widget_config.request_save()
    else:
        outpost_index = i
        TravelToOutpost(id)
        filtered_history = [(id, outpost) for id, outpost in travel_history if not search_outpost or search_outpost.lower() in outpost.lower() or search_outpost.lower() in generate_initials(outpost).lower()]

def TravelToOutpost(outpost_id):
    global is_traveling, widget_config, MODULE_NAME, travel_history
    
    if not is_traveling:
        if outpost_id != Map.GetMapID():
            ConsoleLog(MODULE_NAME, f"Traveling to outpost: {outposts[outpost_id]} ({outpost_id})", PySystem.Console.MessageType.Debug)
            is_traveling = True
            Map.Travel(outpost_id)
            
            if outpost_id in [id for id, _ in travel_history]:
                travel_history = [(id, outpost) for id, outpost in travel_history if id != outpost_id]
            
            # Add the outpost to start of the travel history
            travel_history.insert(0, (outpost_id, outposts[outpost_id]))

            # Remove the last entry if the history exceeds 5 entries
            if len(travel_history) > widget_config.history_length:
                # Remove the oldest entry
                travel_history.pop()
    else:
        ConsoleLog(MODULE_NAME, "Already traveling, please wait.", PySystem.Console.MessageType.Warning)
    
    if widget_config.close_after_travel:
        travel_window_open = False
        


_commands_registered = False


def _resolve_outpost(query: str) -> Optional[int]:
    """Best-effort resolve a chat query to an outpost id: exact id, exact name, initials,
    substring, or a defined alias. Priority outposts win ties."""
    q = query.strip().lower()
    if not q:
        return None
    if q.isdigit() and int(q) in outposts:
        return int(q)
    initials_match = None
    substr_match = None
    for oid, name in outposts.items():
        nl = name.lower()
        if q == nl:
            return oid
        if any(q == a for a in outpost_aliases.get(oid, [])):
            return oid
        if initials_match is None and q == generate_initials(name).lower():
            initials_match = oid
        if substr_match is None and q in nl:
            substr_match = oid
    return initials_match if initials_match is not None else substr_match


def _chat_travel(args, raw):
    """/travel <name|initials|id>  — travel to an outpost. No arg opens the travel window."""
    query = (raw or "").strip() or " ".join(args)
    if not query:
        travel_window_open = True
        return
    oid = _resolve_outpost(query)
    if oid is not None:
        TravelToOutpost(oid)
    else:
        ConsoleLog(MODULE_NAME, f"No outpost matched '{query}'.", PySystem.Console.MessageType.Warning)


def _ensure_commands():
    global _commands_registered
    if _commands_registered:
        return
    try:
        from Py4GWCoreLib.ChatCommands import ChatCommands

        ChatCommands.register(
            "travel", _chat_travel, aliases=["tp"],
            help="Travel to an outpost: /travel <name|initials|id> (no arg opens the window).",
        )
        _commands_registered = True
    except Exception as e:
        PySystem.Console.Log(MODULE_NAME, f"chat command register failed: {e}", PySystem.Console.MessageType.Error)


def main():
    """Required main function for the widget"""
    global game_throttle_timer, game_throttle_time, is_traveling
    global is_map_ready, is_party_loaded

    try:
        _ensure_commands()
        if game_throttle_timer.HasElapsed(game_throttle_time):
            is_map_ready = Map.IsMapReady()
            is_party_loaded = GLOBAL_CACHE.Party.IsPartyLoaded()
            game_throttle_timer.Start()
            
            if is_map_ready and is_party_loaded:
                is_traveling = False
        
        if widget_config.save_requested and save_throttle_timer.HasElapsed(save_throttle_time):
            widget_config.save()
            save_throttle_timer.Reset()
            
        if is_map_ready and is_party_loaded:
            DrawWindow()
            
    except Exception as e:
        PySystem.Console.Log(MODULE_NAME, f"Error in main: {str(e)}", PySystem.Console.MessageType.Debug)
        return False
    return True

# These functions need to be available at module level
__all__ = ['main', 'configure']

if __name__ == "__main__":
    main()
