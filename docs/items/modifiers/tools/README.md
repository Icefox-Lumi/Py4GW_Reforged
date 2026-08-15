# Item-Mod Extraction Tools

This folder contains scripts used to extract or inspect item-mod behavior.
Read `../README.md` and the relevant research record before running a tool.

- `dump_mod_tables_ghidra.py` extracts game tables through Ghidra.
- `format_catalogs.py` formats item-catalog data beside the owning debug
  widgets.
- `game-mod-table-named.txt` and `game-mod-tables-resolved.txt` are live
  outputs of the `Dump Named Mod Table` and `Resolve Mod Tables` debug
  widgets (`Widgets/Coding/Debug/Py4GW/`); they regenerate on every run and
  are read by `format_catalogs.py` and the naming records.
- `../../archive/items/modifiers/tools/` preserves the superseded generated
  tables and the broken `build_master_mod_list.py` (its input module was
  removed).

Treat these tools as reverse-engineering utilities. Verify the target program,
game build, and output destination before execution.
