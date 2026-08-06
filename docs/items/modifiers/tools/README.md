# Item-Mod Extraction Tools

This folder contains the scripts and generated tables used to extract or format
the item-mod catalogs. Read `../README.md` and the relevant numbered research
record before running a tool.

- `dump_mod_tables_ghidra.py` extracts game tables through Ghidra.
- `format_catalogs.py` and `build_master_mod_list.py` derive catalog outputs.
- `game_mod_table*.py` and related text files are generated artifacts.

Treat these tools as reverse-engineering utilities. Verify the target program,
game build, and output destination before execution.
