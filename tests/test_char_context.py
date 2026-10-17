"""Independent Win32 context-layout and accessor regressions."""

# pyright: strict

from __future__ import annotations

import ctypes
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _install_package(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = _install_module(monkeypatch, name)
    module.__dict__["__path__"] = []
    return module


def _load_source(monkeypatch: pytest.MonkeyPatch, name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load production source at {path}")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _load_char_context_layout(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Load the real Win32 declarations without registering runtime callbacks."""
    assert (
        ctypes.sizeof(ctypes.c_void_p) == 4 and ctypes.sizeof(ctypes.c_wchar) == 2
    ), "CharContext regressions require the supported Windows 32-bit interpreter"
    package = "_char_context_layout"
    for name in (package, f"{package}.internals", f"{package}.context"):
        _install_package(monkeypatch, name)
    for name in ("helpers", "gw_array"):
        _load_source(
            monkeypatch,
            f"{package}.internals.{name}",
            _REPO_ROOT / "Py4GWCoreLib/native_src/internals" / f"{name}.py",
        )
    callback = _install_module(monkeypatch, "PyCallback")

    def register_callback(*_args: Any, **_kwargs: Any) -> None:
        pass

    callback.__dict__.update(
        PyCallback=types.SimpleNamespace(Register=register_callback),
        Phase=types.SimpleNamespace(PreUpdate=0),
        Context=types.SimpleNamespace(Draw=0),
    )
    return _load_source(
        monkeypatch,
        f"{package}.context.CharContext",
        _REPO_ROOT / "Py4GWCoreLib/native_src/context/CharContext.py",
    )


def _synthetic_char_context(layout: types.ModuleType, email: str, prefix: str = "ABCD") -> Any:
    """Own a synthetic buffer; write the email at Native's independent offset."""
    assert len(prefix) == 4 and len(email.encode("utf-16-le")) < 0x80, (prefix, email)
    memory = ctypes.create_string_buffer(0x458)
    ctypes.memmove(ctypes.addressof(memory) + 0x3D0, prefix.encode("utf-16-le"), 8)
    encoded = (email + "\0").encode("utf-16-le")
    ctypes.memmove(ctypes.addressof(memory) + 0x3D8, encoded, len(encoded))
    return types.SimpleNamespace(memory=memory, view=layout.CharContextStruct.from_buffer(memory))


def test_char_context_native_win32_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _load_char_context_layout(monkeypatch)
    expected = {
        "h0000_array": 0x0000,
        "h0010": 0x0010,
        "h0014_array": 0x0014,
        "h0024": 0x0024,
        "h0034_array": 0x0034,
        "h0044_array": 0x0044,
        "h0054": 0x0054,
        "player_uuid_ptr": 0x0064,
        "player_name_enc": 0x0074,
        "h009C": 0x009C,
        "h00EC_array": 0x00EC,
        "h00FC": 0x00FC,
        "world_flags": 0x0190,
        "token1": 0x0194,
        "map_id": 0x0198,
        "is_explorable": 0x019C,
        "host": 0x01A0,
        "token2": 0x01B8,
        "h01BC": 0x01BC,
        "h0228": 0x0228,
        "district_number": 0x022C,
        "language": 0x0230,
        "observe_map_id": 0x0234,
        "current_map_id": 0x0238,
        "observe_map_type": 0x023C,
        "current_map_type": 0x0240,
        "h0244": 0x0244,
        "observer_matches_array": 0x0258,
        "h0268": 0x0268,
        "player_flags": 0x02AC,
        "player_number": 0x02B0,
        "h02B4": 0x02B4,
        "progress_bar_ptr": 0x0360,
        "h0360": 0x0364,
        "player_email_ptr": 0x03D8,
    }
    actual = {name: getattr(layout.CharContextStruct, name).offset for name, _ in layout.CharContextStruct._fields_}
    assert actual == expected, ("Native CharContext field offsets", expected, actual)
    assert layout.CharContextStruct._pack_ == 1
    assert ctypes.alignment(layout.CharContextStruct) == 1
    assert ctypes.sizeof(layout.CharContextStruct) == 0x458
    assert ctypes.sizeof(layout.ProgressBar) == 0x2C
    types_by_name = dict(layout.CharContextStruct._fields_)
    assert types_by_name["h02B4"]._length_ == 43
    assert types_by_name["h0360"]._length_ == 29
    assert types_by_name["player_email_ptr"] is ctypes.c_wchar * 64
    assert types_by_name["progress_bar_ptr"] is ctypes.POINTER(layout.ProgressBar)


@pytest.mark.parametrize("prefix", ("ABCD", "\x01\x02\x03\x04", "\0\0\0\0"), ids=("text", "controls", "zeros"))
def test_char_context_reads_native_email_past_misleading_prefix(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    layout = _load_char_context_layout(monkeypatch)
    synthetic = _synthetic_char_context(layout, "current@example.test", prefix)
    view = synthetic.view
    assert view.player_email_encoded_str == view.player_email_str == "current@example.test", (
        prefix,
        view.player_email_str,
    )
    legacy = ctypes.wstring_at(ctypes.addressof(synthetic.memory) + 0x3D0, 64).split("\0", 1)[0]
    assert layout.encoded_wstr_to_str(legacy) != view.player_email_str, (prefix, legacy)
    progress = layout.ProgressBar()
    progress.pips, progress.progress = 3, 0.5
    ctypes.c_uint32.from_buffer(synthetic.memory, 0x360).value = ctypes.addressof(progress)
    assert view.progress_bar.pips == 3 and view.progress_bar.progress == 0.5
    # The preserved padding name now denotes Native's h0364 array, including its final words.
    ctypes.c_uint32.from_buffer(synthetic.memory, 0x364).value = 0x12345678
    assert view.h0360[0] == 0x12345678
