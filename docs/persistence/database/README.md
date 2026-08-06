# Database Documentation Map

This folder contains current database architecture context. It is distinct
from `docs/persistence/ini-manager/`, which covers Settings and INI migration.

## Authority and status

- `database-manager-and-database-namespace.md` describes the current
  `DBMgr`/`Database`/`Account` ownership model and points to live sources.
- The authoritative implementation is `Py4GWCoreLib/database_src/DBMgr.py`,
  `Py4GWCoreLib/database_src/Account.py`, and `Py4GWCoreLib/Database.py`.
- `DBMGR_HANDOVER.md` at the repository root is an earlier prototype/handover;
  it is historical context and does not override the current implementation.
- SQLite is the sanctioned non-`Settings`/`JsonFactory` persistence exception
  for `Py4GWCoreLib/database_src/DBMgr.py`; preserve that boundary when adding
  other storage behavior.

## Review order

1. Read the current architecture note for namespace and ownership intent.
2. Inspect the live `DBMgr`, `Account`, and `Database` implementations.
3. Consult `docs/persistence/audit/` for the broader persistence boundary and
   exceptions.
4. Use focused database scripts/tests and report actual runtime evidence.
