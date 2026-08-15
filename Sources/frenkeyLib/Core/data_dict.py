"""Typed JSON-serializable collections for the DataCollector.

These are pure in-memory collections: serialization helpers only. Persistence
belongs to the owning collector, which reads and writes its ``JsonFactory``
document through ``BaseCollector.load``/``try_save``. Nothing here touches the
filesystem; the jail boundary is owned by ``JsonFactory`` alone.

The document payload shape is ``{"version": str, "data": ...}``, matching the
legacy on-disk schema so existing catalogs survive the storage-owner swap.
"""

import time
from typing import Any, Callable, Optional

from Sources.frenkeyLib.Core.json_serializable import JsonSerializableDictionary
from Sources.frenkeyLib.Core.json_serializable import JsonSerializableList
from Sources.frenkeyLib.Core.json_serializable import T_DICT_KEY
from Sources.frenkeyLib.Core.json_serializable import T_SERIALIZABLE_VALUE


def remove_none_values(value: object) -> object:
    """Strip ``None`` entries from dict/list payloads.

    The legacy file writer dropped nulls before writing, so the stored schema
    never contained them; keep that shape for parity.
    """
    if isinstance(value, dict):
        return {
            key: remove_none_values(child_value)
            for key, child_value in value.items()
            if child_value is not None
        }
    if isinstance(value, list):
        return [
            remove_none_values(item)
            for item in value
            if item is not None
        ]
    return value


class DataList(JsonSerializableList[T_SERIALIZABLE_VALUE]):
    """A typed list with a ``{version, data}`` document payload."""

    def __init__(
        self,
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
        data: Optional[list[T_SERIALIZABLE_VALUE]] = None,
    ):
        super().__init__(item_type=value_type, data=data)
        self.version = str(version)
        self.last_change: float = time.monotonic()

    def _to_document_payload(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'data': [item.to_dict() for item in self],
        }


class DataDict(
    JsonSerializableDictionary[T_DICT_KEY, T_SERIALIZABLE_VALUE],
):
    """A typed dict with a ``{version, data}`` document payload."""

    def __init__(
        self,
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
        key_decoder: Optional[Callable[[str], T_DICT_KEY]] = None,
        key_encoder: Optional[Callable[[T_DICT_KEY], str]] = None,
        data: Optional[dict[T_DICT_KEY, T_SERIALIZABLE_VALUE]] = None,
    ):
        super().__init__(
            value_type=value_type,
            data=data,
            key_decoder=key_decoder,
            key_encoder=key_encoder,
        )
        self.version = str(version)
        self.last_change: float = time.monotonic()

    def _to_document_payload(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'data': JsonSerializableDictionary.to_dict(self),
        }
