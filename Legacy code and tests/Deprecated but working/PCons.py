from Py4GWCoreLib import *
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
import os
module_name = "PCons Manager"

script_directory = os.path.dirname(os.path.abspath(__file__))
root_directory = os.path.normpath(os.path.join(script_directory, ".."))
ini_file_location = os.path.join(root_directory, "Widgets/Config/PCons.ini")
matching_items = []

ini_handler = Settings("Widgets/Config/PCons.ini", "global")

class PCons:
    global ini_handler
    def __init__(self):
        self.ini_entry_name = module_name
        self.enable_module = ini_handler.get_bool(self.ini_entry_name, "Enable Module", False)
        self.aftercast = 500
        self.aftercast_timer = Timer()
        self.aftercast_timer.Start()
        self.pcons = {
            'Essence of Celerity': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Essence of Celerity", False),
                'effect_id': 2522,
                'model_id': 24859,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Grail of Might': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Grail of Might", False),
                'effect_id': 2521,
                'model_id': 24860,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Armor of Salvation': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Armor of Salvation", False),
                'effect_id': 2520,
                'model_id': 24861,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Red Rock Candy': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Red Rock Candy", False),
                'effect_id': 2973,
                'model_id': 21492,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Blue Rock Candy': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Blue Rock Candy", False),
                'effect_id': 2971,
                'model_id': 21488,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Green Rock Candy': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Green Rock Candy", False),
                'effect_id': 2972,
                'model_id': 21489,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Golden Egg': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Golden Egg", False),
                'effect_id': 1934,
                'model_id': 22752,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Birthday Cupcake': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Birthday Cupcake", False),
                'effect_id': 1945,
                'model_id': 22269,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Candy Corn': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Candy Corn", False),
                'effect_id': 2604,
                'model_id': 28433,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Candy Apple': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Candy Apple", False),
                'effect_id': 2605,
                'model_id': 28431,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Slice of Pumpkin Pie': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Slice of Pumpkin Pie", False),
                'effect_id': 2649,
                'model_id': 28432,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'War Supplies': {
                'active': ini_handler.get_bool(self.ini_entry_name, "War Supplies", False),
                'effect_id': 3174,
                'model_id': 32558,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Drake Kabob': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Drake Kabob", False),
                'effect_id': 1680,
                'model_id': 17060,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
            'Bowl of Skalefin Soup': {
                'active': ini_handler.get_bool(self.ini_entry_name, "Bowl of Skalefin Soup", False),
                'effect_id': 1681,
                'model_id': 17061,
                'internal_cooldown': 5000,
                'internal_timer': Timer()
            },
        }

    def save(self):
        ini_handler.set(self.ini_entry_name, "Enable Module", str(self.enable_module))
        for name, data in self.pcons.items():
            ini_handler.set(self.ini_entry_name,
                                  name, str(data['active']))

widget_config = PCons()
WINDOW_NAME = "PCons Manager"
WINDOW_FLAGS = PyImGui.WindowFlags.AlwaysAutoResize

def handle_pcons():
    """Check and use PCONS if needed"""
    global widget_config, matching_items
    try:
        player_id = Player.GetAgentID()
        for pcon_name, data in widget_config.pcons.items():
            if data['active']:
                stack_size = 0
                if matching_items:
                    item = matching_items[0]
                    stack_size = Item.Properties.GetQuantity(item)
                    
                if stack_size == 0:
                    continue
                        
                has_effect = Effects.EffectExists(player_id, data['effect_id']) or Effects.BuffExists(player_id, data['effect_id'])
            
                if not has_effect:
                    items = ItemArray.GetItemArray([Bag.Backpack, Bag.Belt_Pouch, Bag.Bag_1, Bag.Bag_2])
                    matching_items = ItemArray.Filter.ByCondition(items, lambda item_id: Item.GetModelID(item_id) == data['model_id'])
                    if matching_items:
                        if data['internal_timer'].IsStopped() or data['internal_timer'].HasElapsed(data['internal_cooldown']):
                            data['internal_timer'].Stop()
                            PySystem.Console.Log(module_name, f"Using {pcon_name}.", PySystem.Console.MessageType.Debug)
                            ActionQueueManager().AddAction("ACTION", "UseItem", matching_items[0])
                            widget_config.aftercast_timer.Reset()
                            data['internal_timer'].Start()
                            return  # Exit after using one pcon

    except Exception as e:
        PySystem.Console.Log(module_name, f"Error monitoring PCONS: {str(e)}", PySystem.Console.MessageType.Debug)

def DrawWindow():
    """Draw the PCONS manager window"""
    global widget_config, matching_items
    try:
        if PyImGui.begin(WINDOW_NAME, WINDOW_FLAGS):
            PyImGui.text("PCons Auto-Usage")
            PyImGui.separator()

            widget_config.enable_module = PyImGui.checkbox("PCcons enabled", widget_config.enable_module)

            if not widget_config.enable_module:
                PyImGui.text_colored("PCcons Module is disabled", (0.5, 0.5, 0.5, 1.0))
            else:
                if not Map.IsExplorable():
                    PyImGui.text_colored("PCcons Module only works in explorable area", (1.0, 1.0, 0.0, 1.0))

                PyImGui.separator()

                for name, data in widget_config.pcons.items():
                      
                    items = ItemArray.GetItemArray([Bag.Backpack, Bag.Belt_Pouch, Bag.Bag_1, Bag.Bag_2])
                    matching_items = ItemArray.Filter.ByCondition(items, lambda item_id: Item.GetModelID(item_id) == data['model_id'])
                    stack_size = 0
                
                    if matching_items:
                        item = matching_items[0]
                        stack_size = Item.Properties.GetQuantity(item)
                    
                    #color_status = data['active']
                    #if color_status:
                    #    PyImGui.push_style_color(PyImGui.ImGuiCol.Text, Utils.RGBToNormal(200, 255, 150, 255))
                      
                    data['active'] = PyImGui.checkbox(f"{name} [{stack_size}] ", data['active'])   
                    
                    #if color_status:
                    #    PyImGui.pop_style_color(1)            
                    
                    if PyImGui.is_item_hovered():
                        ImGui.show_tooltip(f"Effect ID: {data['effect_id']}, Model ID: {data['model_id']}")
                        
                    

            widget_config.save()
        PyImGui.end()

    except Exception as e:
        PySystem.Console.Log(module_name, f"Error in DrawWindow: {str(e)}", PySystem.Console.MessageType.Debug)

def main():
    """Required main function for the widget"""
    global widget_config
    
    return #disable the widget

    if Routines.Checks.Map.MapValid():
        DrawWindow()

        if widget_config.aftercast_timer.IsStopped() or widget_config.aftercast_timer.HasElapsed(widget_config.aftercast):
            widget_config.aftercast_timer.Stop()

            if widget_config.enable_module and Map.IsExplorable():
                handle_pcons()
                
        ActionQueueManager().ProcessQueue("ACTION")
    else:
        ActionQueueManager().ResetQueue("ACTION")



def configure():
    """Required configuration function for the widget"""
    pass

# These functions need to be available at module level
__all__ = ['main', 'configure']

if __name__ == "__main__":
    main()
