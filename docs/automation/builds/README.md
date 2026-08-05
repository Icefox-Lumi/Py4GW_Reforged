# Build-Authoring Documentation Map

This folder contains build authoring workflow, prompt guidance, and the
`BuildMgr`/`SkillsTemplate` contract.

## Authority and status

- `buildmgr_and_skills_template.md` describes the current ownership and package
  contract between `BuildMgr`, `SkillsTemplate`, and skill modules.
- `build_authoring_handover.md` records the preferred implementation method:
  thin explicit build controllers with generic behavior owned by `BuildMgr`.
- `build_prompting_guide.md` records an effective request shape for build work;
  it is workflow guidance, not runtime behavior.
- Current `Py4GWCoreLib/BuildMgr.py`, `Py4GWCoreLib/Builds/Skills/`, HeroAI
  skill metadata, and active build scripts outrank examples or recommendations
  in these documents.

## Review order

1. Read the ownership contract.
2. Read the handover for implementation boundaries.
3. Use the prompting guide to structure a request or analysis.
4. Inspect the affected build, `BuildMgr`, skill metadata, and current fallback
   behavior before editing.
