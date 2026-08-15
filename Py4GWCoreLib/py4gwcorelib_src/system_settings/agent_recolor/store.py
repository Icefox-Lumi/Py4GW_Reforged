"""Agent Recolor persistence — a GLOBAL shareable agent-rule list + a PER-ACCOUNT toggle.

Two scopes on one document (``Widgets/System/Agent Recolor.ini``):

* **global** — the ordered agent-rule list, stored as JSON in a single key so it round-trips
  cleanly and is trivially shareable/exportable. Agent rules are intricate; a single machine-wide
  set avoids replicating them per account (nothing is hardcoded — the file *is* the config).
* **account** — the master on/off plus per-category (agents/gadgets) gates. The *feature*
  is opted into per account even though the agent rules are shared.

``Settings`` is imported lazily (import-safe offline) and self-throttled — we only get/set.
"""

import json

from typing import List

from . import model

_DOC = "Widgets/System/Agent Recolor.ini"


def _global():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        return Settings(_DOC, "global")
    except Exception:
        return None


def _account():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        return Settings(_DOC, "account")
    except Exception:
        return None


# ── global agent-rule list ──────────────────────────────────────────────────────────────────
def load_agent_rules() -> "List[model.AgentRule]":
    s = _global()
    if s is None:
        return []
    return agent_rules_from_json(s.get_str("rules", "list", ""))


def save_agent_rules(rules: "List[model.AgentRule]") -> None:
    s = _global()
    if s is not None:
        s.set("rules", "list", agent_rules_to_json(rules))


def agent_rules_to_json(rules: "List[model.AgentRule]") -> str:
    return json.dumps([r.to_dict() for r in rules])


def agent_rules_from_json(raw: str) -> "List[model.AgentRule]":
    try:
        data = json.loads(raw) if raw else []
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: "List[model.AgentRule]" = []
    for item in data:
        if isinstance(item, dict):
            try:
                out.append(model.AgentRule.from_dict(item))
            except Exception:
                continue
    return out


# ── per-account toggles ─────────────────────────────────────────────────────────────────────
def load_toggles() -> dict:
    s = _account()
    if s is None:
        return {"enabled": False, "agents_on": True, "gadgets_on": True}
    return {
        "enabled": s.get_bool("general", "enabled", False),
        "agents_on": s.get_bool("general", "agents_on", True),
        "gadgets_on": s.get_bool("general", "gadgets_on", True),
    }


def save_toggle(key: str, value: bool) -> None:
    s = _account()
    if s is not None:
        s.set("general", key, bool(value))
