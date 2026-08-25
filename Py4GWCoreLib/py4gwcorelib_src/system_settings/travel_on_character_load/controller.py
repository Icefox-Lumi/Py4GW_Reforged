"""Profiled runtime callback for automatic travel after character changes."""

from typing import Optional

from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player

from . import model
from . import persistence


_CALLBACK_NAME = "Travel On Character Load"
_CharacterKey = tuple[int, int, int, int] | str


def _log(message: str) -> None:
    try:
        import PySystem

        PySystem.Console.Log(_CALLBACK_NAME, message, PySystem.Console.MessageType.Warning)
    except Exception:
        pass


class TravelOnCharacterLoadController:
    """Own account-local travel triggers and execute each trigger once per character."""

    def __init__(self) -> None:
        self.config = persistence.load()
        self._registered = False
        self._settings_account_email = ""
        self._character_key: Optional[_CharacterKey] = None

    def set_travel_on_first_load(self, enabled: bool) -> None:
        self.config.travel_on_first_load = bool(enabled)
        persistence.save(self.config)

    def set_travel_on_character_switch(self, enabled: bool) -> None:
        self.config.travel_on_character_switch = bool(enabled)
        persistence.save(self.config)

    def set_destination(self, destination: str) -> None:
        if destination not in (model.DESTINATION_GUILD_HALL, model.DESTINATION_OUTPOST):
            return
        self.config.destination = destination
        persistence.save(self.config)

    def set_outpost_id(self, outpost_id: int) -> None:
        self.config.outpost_id = int(outpost_id)
        persistence.save(self.config)

    def reload_account_settings(self) -> bool:
        self.config = persistence.load()
        return True

    def register(self) -> None:
        """Register one profiled Main callback, idempotently across widget reloads."""

        try:
            import PyCallback

            from Py4GWCoreLib.py4gwcorelib_src.Profiling import ProfilingRegistry

            PyCallback.PyCallback.RemoveByName(_CALLBACK_NAME)
            PyCallback.PyCallback.Register(
                _CALLBACK_NAME,
                PyCallback.Phase.Update,
                self._callback,
                priority=99,
                context=PyCallback.Context.Main,
            )
            ProfilingRegistry().register(_CALLBACK_NAME)
            self._registered = True
        except Exception as exc:
            _log("callback registration error: %s" % exc)

    def unregister(self) -> None:
        try:
            import PyCallback

            PyCallback.PyCallback.RemoveByName(_CALLBACK_NAME)
        except Exception:
            pass
        self._registered = False

    def _callback(self) -> None:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.Profiling import ProfilingRegistry

            registry = ProfilingRegistry()
            if registry.enabled:
                registry.runcall_scope("widgets", "%s:main" % _CALLBACK_NAME, self._apply)
                return
        except Exception:
            pass
        self._apply()

    def _refresh_local_config_after_bind(self) -> bool:
        try:
            account_email = str(Player.GetAccountEmail() or "").strip()
        except Exception:
            return False
        if not account_email:
            return False
        if account_email == self._settings_account_email:
            return True
        if not persistence.local_is_ready():
            return False
        self.config = persistence.load()
        self._settings_account_email = account_email
        self._character_key = None
        return True

    @staticmethod
    def _current_character_key() -> Optional[_CharacterKey]:
        try:
            uuid = tuple(int(value) for value in Player.GetPlayerUUID())
            if len(uuid) == 4 and any(uuid):
                return uuid  # type: ignore[return-value]
        except Exception:
            pass

        try:
            name = str(Player.GetName() or "").strip()
        except Exception:
            return None
        return "name:%s" % name if name else None

    def _travel_to_destination(self) -> None:
        if self.config.destination == model.DESTINATION_GUILD_HALL:
            if Map.IsGuildHall():
                return
            Map.TravelGH()
            return

        if self.config.destination != model.DESTINATION_OUTPOST:
            _log("Travel skipped: unknown destination %r." % self.config.destination)
            return

        outpost_ids = Map.GetOutpostIDs()
        if self.config.outpost_id not in outpost_ids:
            _log("Travel skipped: outpost ID %d is not in the map catalog." % self.config.outpost_id)
            return
        if Map.IsMapIDMatch(target_map=self.config.outpost_id):
            return

        Map.Travel(self.config.outpost_id)

    def _apply(self) -> None:
        if not self._refresh_local_config_after_bind():
            return
        if not Map.IsMapReady() or not Player.IsPlayerLoaded():
            return

        character_key = self._current_character_key()
        if character_key is None:
            return

        if self._character_key is None:
            self._character_key = character_key
            if self.config.travel_on_first_load:
                self._travel_to_destination()
            return

        if character_key == self._character_key:
            return

        self._character_key = character_key
        if self.config.travel_on_character_switch:
            self._travel_to_destination()


_controller: Optional[TravelOnCharacterLoadController] = None


def get_controller() -> TravelOnCharacterLoadController:
    """Return the process-wide travel-on-character-load controller."""

    global _controller
    if _controller is None:
        _controller = TravelOnCharacterLoadController()
    return _controller
