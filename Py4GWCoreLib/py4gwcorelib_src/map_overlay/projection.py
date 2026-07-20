"""Map Overlay projection — the game↔screen strategy for each mode.

Two implementations behind one interface:

- :class:`AxisAlignedProjection` — the **mission-map** frame. Pans/zooms, never rotates.
  Ports Mission Map's inlined ``RawGamePosToScreen`` / ``RawScreenToRawGamePos`` math and
  fetches the frame transform (pan/scale/zoom/centre/bounds) **once per frame** in
  :meth:`refresh`, caching boundaries per map id. Supports the extra ``mega_zoom``.
- :class:`RotatingProjection` — the **compass** frame. Rotates with the camera. Delegates to
  the native rotation-aware ``Map.MiniMap.MapProjection`` and supports the detached/floating
  placement (free centre + size, optional north-lock).

Both expose the same surface the render/agent layers consume: :meth:`refresh`,
:meth:`game_to_screen`, :meth:`screen_to_game`, :meth:`gwinch_to_pixels`,
:meth:`player_screen`, :meth:`content_rect`, and the ``rotation`` / ``center`` attributes.
"""

import math
from typing import Optional

from Py4GWCoreLib.Camera import Camera
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.UIManager import UIManager
from Py4GWCoreLib.enums import Range
from Py4GWCoreLib.enums import WindowID

from .model import PositionConfig

GWINCHES = 96.0


class Projection:
    """Common interface. Concrete modes fill these in."""

    rotation: float = 0.0
    center: tuple[float, float] = (0.0, 0.0)
    player_pos: tuple[float, float] = (0.0, 0.0)

    def refresh(self) -> bool:  # pragma: no cover - interface
        """Fetch this frame's transform. Return True if the frame is open and drawable."""
        raise NotImplementedError

    def game_to_screen(self, gx: float, gy: float) -> tuple[float, float]:  # pragma: no cover
        raise NotImplementedError

    def screen_to_game(self, sx: float, sy: float) -> tuple[float, float]:  # pragma: no cover
        raise NotImplementedError

    def gwinch_to_pixels(self, gwinch: float) -> float:  # pragma: no cover
        raise NotImplementedError

    def player_screen(self) -> tuple[float, float]:  # pragma: no cover
        raise NotImplementedError

    def content_rect(self) -> tuple[float, float, float, float]:  # pragma: no cover
        raise NotImplementedError


# ── Mission-map (axis-aligned) ───────────────────────────────────────────────────────────
class AxisAlignedProjection(Projection):
    def __init__(self) -> None:
        self.rotation = 0.0
        self.center = (0.0, 0.0)
        self.player_pos = (0.0, 0.0)
        self.mega_zoom = 0.0                     # set by host from config each frame

        self.left = self.top = self.right = self.bottom = 0.0
        self.width = self.height = 0.0
        self.zoom = 0.0
        self.pan_offset_x = self.pan_offset_y = 0.0
        self.scale_x = self.scale_y = 1.0
        self.center_x = self.center_y = 0.0
        self.boundaries: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self.left_bound = self.top_bound = self.right_bound = self.bottom_bound = 0.0

        self._cached_map_id = 0
        self._boundaries_by_map: dict[int, tuple[float, float, float, float]] = {}
        self._world_bounds_by_map: dict[int, tuple[float, float, float, float]] = {}

        # Precomputed affine terms so game_to_screen is 2 muls + 2 adds (see _rebuild_affine).
        self._valid = False
        self._ax = self._bx = self._ay = self._by = 0.0

    def refresh(self) -> bool:
        if not Map.MissionMap.IsWindowOpen():
            return False

        map_id = Map.GetMapID()
        if map_id != self._cached_map_id:
            self._cached_map_id = map_id
            self._boundaries_by_map.clear()
            self._world_bounds_by_map.clear()

        if map_id in self._boundaries_by_map:
            self.boundaries = self._boundaries_by_map[map_id]
        else:
            self.boundaries = Map.GetMapBoundaries()
            self._boundaries_by_map[map_id] = self.boundaries

        if map_id in self._world_bounds_by_map:
            self.left_bound, self.top_bound, self.right_bound, self.bottom_bound = self._world_bounds_by_map[map_id]
        else:
            self.left_bound, self.top_bound, self.right_bound, self.bottom_bound = Map.GetMapWorldMapBounds()
            self._world_bounds_by_map[map_id] = (self.left_bound, self.top_bound, self.right_bound, self.bottom_bound)

        coords = Map.MissionMap.GetMissionMapContentsCoords()
        self.left, self.top, self.right, self.bottom = float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3])
        self.width = self.right - self.left
        self.height = self.bottom - self.top

        self.pan_offset_x, self.pan_offset_y = Map.MissionMap.GetPanOffset()
        self.scale_x, self.scale_y = Map.MissionMap.GetScale()
        self.zoom = Map.MissionMap.GetZoom()
        self.center_x, self.center_y = Map.MissionMap.GetCenter()
        self.center = (self.center_x, self.center_y)
        self.player_pos = Player.GetXY()
        self._rebuild_affine()
        return True

    def _rebuild_affine(self) -> None:
        """Collapse the frame-constant transform into ``screen = game * a + b``.

        Every term here (origin, pan, scale, zoom) is fixed for the frame, so folding them once
        turns each projection into two multiplies and two adds instead of re-deriving the origin
        and zoom per agent.
        """
        b = self.boundaries
        self._valid = len(b) >= 4
        if not self._valid:
            return
        origin_x = self.left_bound + abs(b[0]) / GWINCHES
        origin_y = self.top_bound + abs(b[3]) / GWINCHES
        zoom_total = self.zoom + self.mega_zoom
        kx = self.scale_x * zoom_total
        ky = self.scale_y * zoom_total
        self._ax = kx / GWINCHES
        self._bx = (origin_x - self.pan_offset_x) * kx + self.center_x
        self._ay = -ky / GWINCHES
        self._by = (origin_y - self.pan_offset_y) * ky + self.center_y

    def game_to_screen(self, gx: float, gy: float) -> tuple[float, float]:
        if not self._valid:
            return 0.0, 0.0
        return (gx * self._ax + self._bx, gy * self._ay + self._by)

    def screen_to_game(self, sx: float, sy: float) -> tuple[float, float]:
        if not self._valid or self._ax == 0.0 or self._ay == 0.0:
            return 0.0, 0.0
        return ((sx - self._bx) / self._ax, (sy - self._by) / self._ay)

    def gwinch_to_pixels(self, gwinch: float) -> float:
        return gwinch * self._ax

    def player_screen(self) -> tuple[float, float]:
        return self.game_to_screen(self.player_pos[0], self.player_pos[1])

    def content_rect(self) -> tuple[float, float, float, float]:
        return (self.left, self.top, self.right, self.bottom)


# ── Compass (rotating) ───────────────────────────────────────────────────────────────────
class RotatingProjection(Projection):
    def __init__(self, position: PositionConfig) -> None:
        self.position = position
        self.rotation = 0.0
        self.center = (0.0, 0.0)
        self.player_pos = (0.0, 0.0)
        self.size = 400.0        # compass pixel radius (scale)
        self.buffer = 10.0
        self._cos = 1.0
        self._sin = 0.0
        self._s = 0.0            # scale / Range.Compass (pixels per gwinch)

    def refresh(self) -> bool:
        self.player_pos = Player.GetXY()
        frame_id = Map.MiniMap.GetFrameID()
        snapped = (
            self.position.snap_to_game
            and not self.position.detached
            and UIManager.FrameExists(frame_id)
            and UIManager.IsWindowVisible(WindowID.WindowID_Compass)
        )
        if snapped:
            coords = UIManager.GetFrameCoords(frame_id)
            cx, cy = Map.MiniMap.GetMapScreenCenter(coords)
            cx, cy = round(cx), round(cy)
            if cx > 100000 or cy > 100000:
                return False
            self.center = (float(cx), float(cy))
            self.size = float(round(Map.MiniMap.GetScale(coords)))
            self.rotation = Map.MiniMap.GetRotation()
        else:
            self.center = (float(self.position.detached_x), float(self.position.detached_y))
            self.size = float(self.position.detached_size)
            if self.position.always_point_north:
                self.rotation = 0.0
            else:
                self.rotation = Camera.GetCurrentYaw() - math.pi / 2
        self._cos = math.cos(self.rotation)
        self._sin = math.sin(self.rotation)
        self._s = self.size / float(Range.Compass.value)
        return True

    # The native Map.MiniMap.MapProjection helpers re-import Player on every call, so the same
    # math is inlined here against per-frame trig. Formula is unchanged.
    def game_to_screen(self, gx: float, gy: float) -> tuple[float, float]:
        cx, cy = self.center
        dx = (gx - self.player_pos[0]) * self._s
        dy = -(gy - self.player_pos[1]) * self._s
        return (cx + self._cos * dx - self._sin * dy,
                cy + self._sin * dx + self._cos * dy)

    def screen_to_game(self, sx: float, sy: float) -> tuple[float, float]:
        if self._s == 0.0:
            return 0.0, 0.0
        cx, cy = self.center
        ex = sx - cx
        ey = sy - cy
        # inverse rotation: cos(-r)=cos, sin(-r)=-sin
        rx = self._cos * ex + self._sin * ey
        ry = -self._sin * ex + self._cos * ey
        return (self.player_pos[0] + rx / self._s, self.player_pos[1] - ry / self._s)

    def gwinch_to_pixels(self, gwinch: float) -> float:
        return gwinch * self._s

    def player_screen(self) -> tuple[float, float]:
        return self.center

    def content_rect(self) -> tuple[float, float, float, float]:
        cx, cy = self.center
        r = self.size + self.buffer
        return (cx - r, cy - r, cx + r, cy + r)
