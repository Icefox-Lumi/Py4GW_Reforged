Nicholas Farm Manager - v1.3
================================

RECOMMENDED INSTALL LAYOUT

Nicholas the Traveler/
|-- .widget                         <- existing widget marker
|-- Nicholas Manager.py             <- the ONLY visible Widget Browser entry
`-- _modules/
    |-- NicholasFarmBase.py          <- hidden support module
    `-- NicholasFarms.py             <- hidden farm registry

IMPORTANT WHEN UPGRADING FROM v1.2
----------------------------------
Delete the old top-level files:
- NicholasFarmBase.py
- NicholasFarms.py

If they remain next to Nicholas Manager.py inside the .widget folder, the
Widget Manager will continue to discover them as separate widgets.

Why _modules works
------------------
WidgetManager discovers Python files only in directories that contain a
".widget" marker. The "_modules" folder intentionally does not contain one.
Nicholas Manager loads both support modules explicitly with importlib.

Widget description
------------------
Nicholas Manager now exposes MODULE_DESCRIPTION, MODULE_CATEGORY, MODULE_TAGS
and MODULE_ALIASES for Widget Browser hover/search metadata.

Credits included in MODULE_DESCRIPTION:
Farm paths and Nicholas exchange paths are credited to BubbleTea and are
migrated/adapted from his original AutoIt Nicholas the Traveler scripts.

Collector conversions to implement next
----------------------------------------
- Bog Skale Fin -> Herring
- Chunk of Drake Flesh -> Drake Kabob
- Mandragor Root -> Mandragor Root Cake
- Sentient Spore -> Bottle of Vabbian Wine
- Skale Fin -> Bowl of Skalefin Soup

v1.3.1 correction
-----------------
The .widget discovery marker is now INCLUDED in the package.
Without this marker WidgetManager ignores the Nicholas the Traveler folder
entirely.

Expected Widget Browser result:
- Nicholas Manager          -> visible
- NicholasFarmBase          -> hidden
- NicholasFarms             -> hidden

v1.3.2 import cleanup
---------------------
The private support folder is now a real Python package:

    _modules/
        __init__.py
        NicholasFarmBase.py
        NicholasFarms.py

Imports now explicitly use:

    from _modules.NicholasFarmBase import ...
    from _modules.NicholasFarms import ...

NicholasFarmBase also imports NicholasFarms through the same qualified package.

The parent Nicholas widget directory is inserted into sys.path at runtime
because Py4GW launches scripts from a <string> context.

The _modules directory still has NO .widget marker, so its Python files remain
hidden from Widget Browser discovery.

v1.3.3 - full package / import fix
---------------------------------
This package MUST be installed as a whole.

Final layout:

    Nicholas the Traveler/
        .widget
        Nicholas Manager.py
        _modules/
            __init__.py
            NicholasFarmBase.py
            NicholasFarms.py

Important:
- Remove any old top-level NicholasFarmBase.py or NicholasFarms.py.
- Do not mix _modules files from v1.3.1/v1.3.2 with a newer Manager.
- NicholasFarmBase now uses a package-relative import:

      from .NicholasFarms import ...

- Nicholas Manager adds its own widget directory to sys.path and then uses:

      from _modules.NicholasFarmBase import ...
      from _modules.NicholasFarms import ...

This avoids the old "No module named 'NicholasFarms'" error.
