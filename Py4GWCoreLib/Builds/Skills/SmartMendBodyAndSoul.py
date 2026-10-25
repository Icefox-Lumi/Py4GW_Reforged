"""My BiP's healing and cleansing decisions; BuildMgr owns every submission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import dist
from math import isfinite
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import cast

from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.py4gwcorelib_src.FrameCache import frame_cache
from Py4GWCoreLib.Skill import Skill

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import BipDiagnostic
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import MendAttempt
    from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Observation

MendMode = Literal["emergency", "urgent", "routine", "preventive", "opportunistic"]
_Context = tuple[object, ...]
_CONDITIONS = (
    "Bleeding",
    "Blind",
    "Burning",
    "Cracked_Armor",
    "Crippled",
    "Dazed",
    "Deep_Wound",
    "Disease",
    "Poison",
    "Weakness",
)
_THRESHOLDS: dict[MendMode, float] = {"emergency": 0.40, "routine": 0.75, "preventive": 0.85}
_SPELL_TYPES = frozenset({4, 5, 6, 9, 11, 24, 25})


@dataclass(frozen=True)
class _Remote:
    health: float
    conditions: frozenset[str] | None = None
    bar: tuple[int, ...] = ()
    observation: Observation | None = None


@dataclass(frozen=True)
class _Ally:
    agent_id: int
    health: float
    order: int


@dataclass(frozen=True)
class _Value:
    severity: int = 6
    useful: int = 0
    capacity: int = 0
    ranked_conditions: tuple[str, ...] = ()


class SmartMendBodyAndSoul:
    """Frame-local observations, fixed proposals, and no independent action state."""

    def __init__(self, build: BuildMgr) -> None:
        self.build: BuildMgr = build
        self.bip_diagnostic: BipDiagnostic | None = None
        self._skill_id = Skill.GetID("Mend_Body_and_Soul")
        self._condition_names = {Skill.GetID(name): name for name in _CONDITIONS}

    def _context(self) -> _Context:
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import SkillBar

        slot_id: Callable[[int], int] = cast(Any, SkillBar).GetSkillIDBySlot
        return (
            Player.GetAgentID(),
            Player.GetAccountEmail(),
            Player.GetName(),
            Map.GetMapID(),
            Map.GetRegion()[0],
            Map.GetDistrict(),
            Map.GetLanguage()[0],
            tuple(slot_id(slot) for slot in range(1, 9)),
            getattr(self.build, "_generation", 0),
            getattr(self.build, "_active", False),
            id(getattr(self.build, "_cached_data", None)),
        )

    def _mode_allowed(self, mode: MendMode) -> bool:
        if mode in ("preventive", "opportunistic"):
            return self.build.IsInAggro()
        if mode == "urgent":
            return self.build.IsInAggro() or self.build.IsCloseToAggro()
        return mode in _THRESHOLDS

    def _reserve_available(self) -> bool:
        energy_cost: Callable[[int, int], float] = cast(Any, Routines.Checks.Skills).GetEnergyCostWithEffects
        cost = float(energy_cost(self._skill_id, Player.GetAgentID()))
        energy = Agent.GetEnergy(Player.GetAgentID()) * Agent.GetMaxEnergy(Player.GetAgentID())
        return isfinite(cost) and cost >= 0 and isfinite(energy) and energy >= 2 * cost

    @staticmethod
    def _spirit_count() -> int:
        read: Callable[[float, float, float], list[int]] = cast(Any, Routines.Agents).GetFilteredSpiritArray
        spirits = read(*Player.GetXY(), Range.Earshot.value) or []
        return len({aid for aid in spirits if aid > 0 and Agent.IsValid(aid)})

    @frame_cache(category="SmartMendBodyAndSoul", source_lib="publications")
    def _publications(self, context: _Context, details: bool) -> dict[int, _Remote | None]:
        return self._read_publications(details)

    def _read_publications(self, details: bool) -> dict[int, _Remote | None]:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Party
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

        remote: dict[int, _Remote | None] = {}
        try:
            party_id = Party.GetPartyID()
            members = {
                Party.Players.GetAgentIDByLoginNumber(member.login_number)
                for member in Party.GetPlayers() or []
                if member.is_connected
            }
            location = (Map.GetMapID(), Map.GetRegion()[0], Map.GetDistrict(), Map.GetLanguage()[0])
            accounts = GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=False)
        except Exception:
            return remote
        for account in accounts:
            try:
                data = account.AgentData
                aid = int(data.AgentID)
            except Exception:
                continue
            if aid == Player.GetAgentID() or aid not in members:
                continue
            if aid in remote:
                remote[aid] = None
                continue
            remote[aid] = None
            try:
                stamp, login = int(account.LastUpdated), int(data.LoginNumber)
                identity = (
                    stamp,
                    aid,
                    login,
                    int(account.AgentPartyData.PartyID),
                    (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language),
                )
                hp = float(data.Health.Current)
                if not (
                    account.IsAccount
                    and account.IsSlotActive
                    and login > 0
                    and login == Agent.GetLoginNumber(aid)
                    and identity[3:] == (party_id, location)
                    and publication_is_live(get_uncached_tick_count64(), stamp, 250)
                    and not (data.Is_Dead or data.Is_DeadByTypeMap)
                    and isfinite(hp)
                    and 0 < hp <= 1
                ):
                    continue
                bar: tuple[int, ...] = ()
                if details:
                    bar = tuple(int(skill.Id) for skill in data.Skillbar.Skills)
                if identity != (
                    int(account.LastUpdated),
                    int(data.AgentID),
                    int(data.LoginNumber),
                    int(account.AgentPartyData.PartyID),
                    (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language),
                ):
                    continue
                # LastUpdated is an account heartbeat. Buffs refresh on a separate
                # stage without a field timestamp; even retained positive IDs are
                # unknown evidence, not a condition census or a cleansing permit.
                remote[aid] = _Remote(hp, bar=bar)
            except Exception:
                # An uncertain remote publication cannot authorize a decision.
                continue
        if details:
            try:
                read: Callable[[int, int, str], Observation | None] = cast(
                    Any, GLOBAL_CACHE.ShMem
                ).ReadConditionObservation
            except AttributeError:
                return remote
            for aid in members - {Player.GetAgentID()}:
                try:
                    observation = read(aid, Agent.GetLoginNumber(aid), Agent.GetNameByID(aid))
                    if observation is None:
                        continue
                    previous = remote.get(aid)
                    # Condition age is independent of the 250 ms health gate.
                    # Health-only modes still use the unchanged first-pass allies.
                    hp = previous.health if previous is not None else Agent.GetHealth(aid)
                    remote[aid] = _Remote(
                        hp, observation.conditions, previous.bar if previous is not None else (), observation
                    )
                except Exception:
                    continue
        return remote

    def _allies(self, remote: dict[int, _Remote | None]) -> list[_Ally]:
        from Py4GWCoreLib.HeroAI import targeting

        ids: list[int] = cast(Any, targeting).FilterAllyArray(
            targeting.GetAllAlliesArray(Range.Spellcast.value, ordered=True),
            Range.Spellcast.value,
            filter_skill_id=self._skill_id,
        )
        result: list[_Ally] = []
        for order, aid in enumerate(dict.fromkeys(ids)):
            if not Agent.IsValid(aid) or not Agent.IsAlive(aid):
                continue
            if not dist(Player.GetXY(), Agent.GetXY(aid)) <= Range.Spellcast.value:
                continue
            if aid in remote:
                publication = remote[aid]
                if publication is None:
                    continue
                hp = publication.health
            else:
                hp = Agent.GetHealth(aid)
            if isfinite(hp) and 0 < hp <= 1:
                result.append(_Ally(aid, hp, order))
        return result

    @frame_cache(category="SmartMendBodyAndSoul", source_lib="conditions")
    def _conditions(self, aid: int, context: _Context) -> frozenset[str] | None:
        return self._read_conditions(aid)

    def _read_conditions(self, aid: int) -> frozenset[str] | None:
        # The native effect-list surface supplies no verified freshness contract
        # for another player. A missing account publication must not turn that
        # recipient into a trusted local observation, including at final admission.
        if aid != Player.GetAgentID():
            try:
                if Agent.GetLoginNumber(aid) != 0:
                    return None
            except Exception:
                return None
        try:
            from Py4GWCoreLib.Effect import Effects

            if not Agent.IsConditioned(aid):
                return frozenset()
            found = {
                self._condition_names[effect.skill_id]
                for effect in Effects.GetEffects(aid)
                if effect.skill_id in self._condition_names and not (effect.duration > 0 and effect.time_remaining <= 0)
            }
        except Exception:
            found: set[str] = set()
        # These local flags have specific identities. The poison/disease visual
        # flag is ambiguous, and the generic conditioned flag supplies no count.
        for name, check in (
            ("Bleeding", Agent.IsBleeding),
            ("Crippled", Agent.IsCrippled),
            ("Deep_Wound", Agent.IsDeepWounded),
        ):
            try:
                if check(aid):
                    found.add(name)
            except Exception:
                continue
        return frozenset(found)

    @staticmethod
    def _spellcaster(aid: int, publication: _Remote | None) -> bool:
        from Py4GWCoreLib import Party
        from Py4GWCoreLib import SkillBar

        bar = publication.bar if publication is not None else ()
        try:
            if aid == Player.GetAgentID():
                slot_id: Callable[[int], int] = cast(Any, SkillBar).GetSkillIDBySlot
                bar = tuple(slot_id(slot) for slot in range(1, 9))
            elif publication is None:
                for hero in Party.GetHeroes() or []:
                    if hero.agent_id == aid and hero.owner_player_id == Agent.GetLoginNumber(Player.GetAgentID()):
                        index = Party.GetHeroIndex(hero.hero_id)
                        if index > 0:
                            bar = tuple(int(skill.id.id) for skill in cast(Any, SkillBar).GetHeroSkillbar(index))
                        break
            if len(bar) == 8 and any(bar):
                skill_type: Callable[[int], tuple[int, str]] = cast(Any, Skill).GetType
                return any(skill_type(skill)[0] in _SPELL_TYPES for skill in bar if skill > 0)
        except Exception:
            pass
        return Agent.GetProfessions(aid)[0] in (3, 4, 5, 6, 8) or Routines.Checks.Agents.IsCaster(aid)

    def _value(
        self,
        ally: _Ally,
        spirits: int,
        remote: dict[int, _Remote | None],
        context: _Context,
        *,
        fresh: bool = False,
    ) -> _Value:
        if not spirits:
            return _Value()
        publication = remote.get(ally.agent_id)
        conditions: frozenset[str] | None
        if ally.agent_id in remote:
            conditions = publication.conditions if publication is not None else None
        else:
            conditions = self._read_conditions(ally.agent_id) if fresh else self._conditions(ally.agent_id, context)
        if not conditions:
            return _Value()
        aid = ally.agent_id
        martial = Routines.Checks.Agents.IsMartial(aid)
        melee = Routines.Checks.Agents.IsMelee(aid)
        ranks: list[int] = []
        ranked_conditions: list[str] = []
        for condition in conditions:
            before = len(ranks)
            if condition == "Deep_Wound":
                ranks.append(0 if ally.health < 0.60 else 4)
            elif condition == "Dazed" and self._spellcaster(aid, publication):
                ranks.append(1)
            elif condition == "Blind" and martial:
                ranks.append(2)
            elif condition == "Crippled" and melee:
                ranks.append(3)
            elif condition == "Burning":
                ranks.append(4)
            elif condition == "Weakness":
                if martial:
                    ranks.append(4)
                elif self._spellcaster(aid, publication):
                    ranks.append(5)
            elif condition == "Cracked_Armor" and Agent.GetProfessions(aid)[0] in (1, 2, 7, 9, 10):
                ranks.append(4)
            elif condition in ("Poison", "Bleeding", "Disease"):
                ranks.append(5)
            if len(ranks) > before:
                ranked_conditions.append(condition)
        # Capacity counts observed identities, including low-value ones: the game
        # chooses removal order, so no particular useful condition is promised.
        return _Value(min(ranks, default=6), len(ranks), min(spirits, len(conditions)), tuple(ranked_conditions))

    @staticmethod
    def _eligible(mode: MendMode, ally: _Ally, value: _Value) -> bool:
        if mode in _THRESHOLDS:
            return ally.health < _THRESHOLDS[mode]
        return value.severity < 4 if mode == "urgent" else value.useful >= 2

    def try_cast(self, *, mode: MendMode) -> BuildCoroutine:
        if (
            not self.build.IsSkillEquipped(self._skill_id)
            or not Routines.Checks.Skills.CanCast()
            or not self.build.CanCastSkillID(self._skill_id)
            or not self._mode_allowed(mode)
            or (mode == "opportunistic" and not self._reserve_available())
        ):
            return False
        context = self._context()
        remote = self._publications(context, False)
        allies = self._allies(remote)
        cleansing = mode in ("urgent", "opportunistic")
        if cleansing and any(ally.health < 0.40 for ally in allies):
            return False
        spirits = 0 if mode == "emergency" else self._spirit_count()
        if cleansing and not spirits:
            return False
        if spirits:
            remote = self._publications(context, True)
            if cleansing:
                allies = self._allies(remote)
                if any(ally.health < 0.40 for ally in allies):
                    return False
        ranked: list[tuple[tuple[float, ...], _Ally, _Value]] = []
        for ally in allies:
            # Filter health before considering any condition preference.
            if mode in _THRESHOLDS and ally.health >= _THRESHOLDS[mode]:
                continue
            value = self._value(ally, spirits, remote, context)
            if not self._eligible(mode, ally, value):
                continue
            if mode == "urgent":
                key = (value.severity, ally.health, -value.capacity, ally.order, ally.agent_id)
            elif mode == "opportunistic":
                key = (value.severity, -value.capacity, ally.health, ally.order, ally.agent_id)
            else:
                key = (ally.health, value.severity, -value.capacity, ally.order, ally.agent_id)
            ranked.append((key, ally, value))
        if not ranked:
            return False
        _, selected_ally, selected_value = min(ranked, key=lambda entry: entry[0])
        target = selected_ally.agent_id
        selected = remote.get(target)
        selected_observation = selected.observation if selected is not None else None
        diagnostic = self.bip_diagnostic
        attempt: MendAttempt | None = None
        if diagnostic is not None:
            try:
                attempt = diagnostic.mend_candidate(
                    target,
                    selected_ally.health,
                    mode,
                    selected_observation,
                    selected_value.ranked_conditions,
                    spirits,
                    selected_value.severity,
                    selected_value.useful,
                    selected_value.capacity,
                )
            except Exception:
                pass

        def admission(
            accepted: bool,
            reason: str,
            *,
            health: float | None = None,
            spirits: int | None = None,
            observation: Observation | None = None,
            binding: str = "NOT_CHECKED",
        ) -> bool:
            if attempt is not None and diagnostic is not None:
                try:
                    diagnostic.mend_admission(
                        attempt,
                        accepted,
                        reason,
                        health=health,
                        spirits=spirits,
                        observation=observation,
                        binding=binding,
                    )
                except Exception:
                    pass
            return accepted

        def still_eligible() -> bool:
            if context != self._context() or not Routines.Checks.Skills.CanCast() or not self._mode_allowed(mode):
                return admission(False, "CONTEXT_OR_CAST_OR_MODE")
            current_remote = self._read_publications(cleansing)
            current_allies = self._allies(current_remote)
            proposed = next((ally for ally in current_allies if ally.agent_id == target), None)
            if proposed is None or (cleansing and any(ally.health < 0.40 for ally in current_allies)):
                return admission(False, "TARGET_OR_EMERGENCY")
            if not cleansing:
                return proposed.health < _THRESHOLDS[mode]
            current_spirits = self._spirit_count()
            if not current_spirits or (mode == "opportunistic" and not self._reserve_available()):
                return admission(False, "SPIRITS_OR_RESERVE", health=proposed.health, spirits=current_spirits)
            current = current_remote.get(target)
            observation = current.observation if current is not None else None
            if selected_observation is not None:
                if (
                    observation is None
                    or observation.binding != selected_observation.binding
                    or observation.sequence < selected_observation.sequence
                ):
                    return admission(
                        False,
                        "PUBLICATION_OR_BINDING",
                        health=proposed.health,
                        spirits=current_spirits,
                        observation=observation,
                        binding="REJECTED_OR_UNAVAILABLE",
                    )
            elif observation is not None:
                return admission(False, "SOURCE_CHANGED")
            value = self._value(proposed, current_spirits, current_remote, context, fresh=True)
            return admission(
                self._eligible(mode, proposed, value),
                "CURRENT_POLICY",
                health=proposed.health,
                spirits=current_spirits,
                observation=observation,
                binding="VALID" if observation is not None else "NOT_OWNER_PUBLICATION",
            )

        try:
            accepted = yield from self.build.CastSkillIDAndRestoreTarget(
                self._skill_id,
                target,
                extra_condition=still_eligible,
            )
            if attempt is not None and diagnostic is not None:
                try:
                    diagnostic.mend_return(attempt, accepted)
                except Exception:
                    pass
        finally:
            # A closed/abandoned coroutine proves no return, even if work was
            # already queued before target restoration yielded. Never retract it.
            if attempt is not None and diagnostic is not None:
                try:
                    diagnostic.mend_cancel(attempt)
                except Exception:
                    pass
        if accepted and self.bip_diagnostic is not None:
            self.bip_diagnostic.submission("heal", target)
        return accepted
