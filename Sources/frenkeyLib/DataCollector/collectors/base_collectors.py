import time
from typing import Any, Optional

from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory
from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer
from Sources.frenkeyLib.Core.data_dict import DataDict, DataList, remove_none_values
from Sources.frenkeyLib.Core.json_serializable import T_SERIALIZABLE_VALUE


class BaseCollector:
    """Per-frame collector shell backed by one account-scoped ``JsonFactory`` document.

    The document payload is ``{"version": str, "data": ...}``. Collection runs
    on a throttle; the collector marks the data dirty (``requires_save``) and
    the save throttle flushes it through the owning document. The document is
    self-persisting, so there is deliberately no save-every-N loop here: the
    flush only serializes when something actually changed.
    """

    def __init__(self, document_name: str, *args: Any, **kwargs: Any) -> None:
        self.document = JsonFactory(document_name, 'account')
        super().__init__(*args, **kwargs)

        self.run_throttle = ThrottledTimer(250)
        self.save_throttle = ThrottledTimer(1_000)
        self.current_context_key = ''
        self.checked_ids: list[int] = []

    def mark_id_as_checked(self, agent_id: int):
        self.checked_ids.append(agent_id)

    def run(self):
        self._handle_context_change()

        if not self._is_ready():
            return

        if self.run_throttle.IsExpired():
            self.run_throttle.Reset()
            self._collect()

        if self.save_throttle.IsExpired():
            self.save_throttle.Reset()
            self.try_save()

    def _is_ready(self) -> bool:
        return Map.IsMapReady() and Player.IsPlayerLoaded()

    def _collect(self):
        raise NotImplementedError

    def _flush_cache(self):
        self.checked_ids.clear()

    def _handle_context_change(self):
        context_key = self._get_context_key()
        if context_key == self.current_context_key:
            return

        self.current_context_key = context_key
        self._flush_cache()

    def _get_context_key(self) -> str:
        account_email = str(Player.GetAccountEmail() or '').strip()
        player_name = str(Player.GetName() or '').strip()
        map_id = int(Map.GetMapID() or 0)
        return f'{account_email}|{player_name}|{map_id}'

    def load(self) -> None:
        """Replace the collection with the document's stored data."""
        raw_data = self.document.get_json('data', None)

        if isinstance(self, DataDict):
            self.clear()
            self.version = self.document.get_str('version', self.version)
            if isinstance(raw_data, dict):
                self.replace_from_dict(raw_data)
        elif isinstance(self, DataList):
            self.clear()
            self.version = self.document.get_str('version', self.version)
            if isinstance(raw_data, list):
                self.replace_from_dict(raw_data)
        else:
            return

        self.last_change = time.monotonic()

    def try_save(self) -> bool:
        """Flush collected data into the owning document when marked dirty."""
        if not isinstance(self, (DataDict, DataList)) or not self.requires_save:
            return False

        payload = self._to_document_payload()
        self.document.set_json('data', remove_none_values(payload['data']))
        self.document.set('version', self.version)
        self.requires_save = False
        self.last_change = time.monotonic()
        return True


class ListCollector(BaseCollector, DataList[T_SERIALIZABLE_VALUE]):
    def __init__(
        self,
        document_name: str,
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
    ):
        super().__init__(document_name, version=version, value_type=value_type)
        self.load()
