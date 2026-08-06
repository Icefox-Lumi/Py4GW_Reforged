# Persistence Documentation

Use this directory for sanctioned storage implementations and migration
records.

## Mandatory persistence jail boundaries

Persistence ownership is strict:

- INI data MUST use `Settings`.
- JSON and structured data MUST use `JsonFactory`.
- No other persistence handler, wrapper, protocol, provider, repository,
  adapter, or bypass is allowed, even when it delegates internally to
  `Settings` or `JsonFactory`.
- Account-scoped INI documents remain under `settings/<email>/<name>` and
  global INI documents under `settings/Global/<name>`.
- Account-scoped JSON documents remain under `json/<email>/<name>` and global
  JSON documents under `json/Global/<name>`.
- JSON has no root scope. The only project-root exception is `Py4GW.ini`,
  reached through `Settings.py4gw_ini()`.

`Settings` and `JsonFactory` are not convenience APIs. They are the project's
persistence jail boundaries. They enforce the allowed storage roots, valid
scopes, path handling, account/global isolation, native locking, autosave,
and the Python/native persistence contract. Replacing or hiding either class
behind another access layer removes the authoritative ownership boundary and
creates a path for those guarantees to be bypassed.

If the required capability is missing, stop the feature work and report the
capability gap to the owner. Do not add an extension, raw handler, or private
persistence abstraction in the feature change. Only a separately approved
persistence-infrastructure change may modify the owning implementation, and
it must preserve the folder jail. Feature-specific code may own in-memory
schema validation and transformation, but all persistent reads and writes
must remain on the concrete `Settings` or `JsonFactory` object.

- `ini_manager/` — INI/Settings migration and behavior records.
- `database/` — SQLite database manager and namespace documentation.
- `audit/` — audit and rationale for the persistence boundary.

The owning implementation and native backend remain authoritative.
