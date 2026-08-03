from ctypes.wintypes import PUINT
import PyQuest

from Py4GWCoreLib import *

MODULE_NAME = "Quest Handler"

class BotVars:
    def __init__(self, map_id=0):
        self.window_name = "Quest Handler Test"
        self.window_flags = PyImGui.WindowFlags.NoFlag
        self.quest_handler = PyQuest.PyQuest()
        

bot_vars = BotVars()

quest_id_input = 0
# Example of additional utility function
def DrawWindow():
    global bot_vars, quest_id_input

    try:
        if PyImGui.begin(bot_vars.window_name, bot_vars.window_flags):

            quest_id = bot_vars.quest_handler.get_active_quest_id()
            PyImGui.text(f"Active Quest ID: {quest_id}")

            quest_id_input = PyImGui.input_int("Quest ID", quest_id_input)

            if PyImGui.button("Set Active Quest ID"):
                bot_vars.quest_handler.set_active_quest_id(quest_id_input)

            if PyImGui.button("Abandon Quest ID"):
                bot_vars.quest_handler.abandon_quest_id(quest_id_input)

            PyImGui.end()

    except Exception as e:
        frame = inspect.currentframe()
        current_function = frame.f_code.co_name if frame else "DrawWindow"
        PySystem.Console.Log("Quest Handler", f"Error in {current_function}: {str(e)}", PySystem.Console.MessageType.Error)
        raise

# main function must exist in every script and is the entry point for your script's execution.
def main():
    try:
         DrawWindow()

    # Handle specific exceptions to provide detailed error messages
    except ImportError as e:
        PySystem.Console.Log(MODULE_NAME, f"ImportError encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    except ValueError as e:
        PySystem.Console.Log(MODULE_NAME, f"ValueError encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    except TypeError as e:
        PySystem.Console.Log(MODULE_NAME, f"TypeError encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    except Exception as e:
        # Catch-all for any other unexpected exceptions
        PySystem.Console.Log(MODULE_NAME, f"Unexpected error encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    finally:
        # Optional: Code that will run whether an exception occurred or not
        #PySystem.Console.Log(module_name, "Execution of Main() completed", PySystem.Console.MessageType.Info)
        # Place any cleanup tasks here
        pass

# This ensures that Main() is called when the script is executed directly.
if __name__ == "__main__":
    main()
