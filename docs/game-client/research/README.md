# Game-Client Research

This directory contains cross-topic Guild Wars client investigation: client
architecture, packet capture, travel, name handling, skills, quest data, and
RE methods. It is evidence, not current runtime authority.

- `reverse-engineering-reference.md` is the entry point for the WASM-first
  workflow and the client-wide function/memory model.
- `cpp-wasm-mapping.md` explains C++/WASM/EXE translation.
- `packet-sniffers-reference.md`, `map-travel-*.md`, and
  `name-obfuscation-reverse-engineering.md` record their named subsystems.
- `quest-data-request-pipeline.md` records the quest-binding data-loading
  behavior and its game-thread crash fix.
- `struct-identification-methodology.md` is the reusable struct-identification
  method.
- `../../archive/game-client/research/` preserves historical backups and
  superseded callable-function catalogs.

UI-specific native findings live in `../../ui/research/`; item-modifier
findings live in `../../items/modifiers/`.
