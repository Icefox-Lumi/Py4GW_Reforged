"""Game-thread GW.dat archive access backed by the native GWDatReader."""


def read_file_by_hash(file_hash: str) -> bytes | None:
    """Read a decompressed GW.dat entry by encoded file hash."""
    ...


def read_file_by_id(file_id: int, stream_id: int = 1) -> bytes | None:
    """Read a decompressed GW.dat entry by sequential file ID."""
    ...
