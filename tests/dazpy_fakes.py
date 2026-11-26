"""Shared fakes for the dazpy SDK unit tests (not a test module).

* ``mock_client`` — a ``MagicMock(spec=DazClient)`` whose ``execute`` returns a
  canned ``ExecutionResult``; the workhorse of the script-generation tests.
* ``sync_client`` / ``async_client`` — real ``DazClient`` / ``AsyncDazClient``
  instances built through their constructors, with the transport
  (``requests.Session`` / ``httpx.AsyncClient``) replaced by a mock.
* ``FakeRigBone`` / ``FakeRigSkeleton`` / ``FakeRigScene`` and the
  ``Kinematic*`` variants — duck-typed skeletons for the interaction solver.
  (``recipe_fakes.FakeScene`` is unrelated: it fakes recipe live state.)

Import with the tests dir on ``sys.path``: ``from dazpy_fakes import ...``.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

from dazpy._client import DazClient
from dazpy._node import NodeIdentifier
from dazpy._result import ExecutionResult


# ── Clients ───────────────────────────────────────────────────────────────

def mock_client(return_value=None, output=None) -> MagicMock:
    """A spec'd DazClient mock whose ``execute`` returns *return_value*."""
    client = MagicMock(spec=DazClient)
    client.execute.return_value = ExecutionResult(
        value=return_value,
        output=output or [],
        request_id="test1234",
    )
    return client


def sync_client(token: str = "", **kwargs) -> tuple[DazClient, MagicMock]:
    """A real DazClient whose ``requests.Session`` is a MagicMock.

    Version checks are off unless the caller passes ``check_version=True``.
    """
    kwargs.setdefault("check_version", False)
    session = MagicMock()
    with patch("dazpy._client._requests.Session", return_value=session):
        client = DazClient(token=token, **kwargs)
    return client, session


def async_client(token: str = "", **kwargs):
    """A real AsyncDazClient whose ``httpx.AsyncClient`` is a MagicMock with
    awaitable ``post``/``get``/``delete``/``aclose``.

    Version checks are off unless the caller passes ``check_version=True``.
    """
    from dazpy.aio import AsyncDazClient

    kwargs.setdefault("check_version", False)
    http = MagicMock()
    http.post = AsyncMock()
    http.get = AsyncMock()
    http.delete = AsyncMock()
    http.aclose = AsyncMock()
    with patch("dazpy._client_aio.httpx.AsyncClient", return_value=http):
        client = AsyncDazClient(token=token, **kwargs)
    return client, http


# ── Rig fakes for the interaction solver ──────────────────────────────────

class FakeRigBone:
    def __init__(
        self,
        name: str,
        label: str | None = None,
        parent: FakeRigBone | None = None,
        rotation_order: str | None = "XYZ",
        local_position: tuple[float, float, float] | None = (0.0, 0.0, 0.0),
        local_euler: tuple[float, float, float] | None = (0.0, 0.0, 0.0),
    ) -> None:
        self.name = name
        self.label = label
        self.parent = parent
        self.rotation_order = rotation_order
        self.local_position = local_position
        self.local_euler = local_euler
        self._identifier = NodeIdentifier(name)


class FakeRigSkeleton:
    """No ``find_bone``: the solver's IK paths skip skeletons without one."""

    def __init__(self, label: str, bones: list) -> None:
        self.label = label
        self._bones = bones
        self._identifier = NodeIdentifier(label, kind="label")
        self.position_calls: list[tuple[float, float, float]] = []

    def bones(self) -> list:
        return self._bones

    def set_position(self, x: float, y: float, z: float) -> None:
        self.position_calls.append((x, y, z))


class FakeRigScene:
    def __init__(self, skeletons: list[FakeRigSkeleton]) -> None:
        self._skeletons = skeletons

    def skeletons(self) -> list[FakeRigSkeleton]:
        return self._skeletons

    def find_skeleton_by_label(self, label: str) -> FakeRigSkeleton:
        for skeleton in self._skeletons:
            if skeleton.label == label:
                return skeleton
        raise KeyError(label)


class KinematicFakeBone:
    """A bone whose world ``position`` follows its parents' Z rotations (2-D FK)."""

    def __init__(
        self,
        name: str,
        label: str | None = None,
        parent: KinematicFakeBone | None = None,
        local_position: tuple[float, float, float] | None = (1.0, 0.0, 0.0),
    ) -> None:
        self.name = name
        self.label = label
        self.parent = parent
        self.rotation_order = "XYZ"
        self.local_position = local_position
        self.local_euler = (0.0, 0.0, 0.0)
        self._identifier = NodeIdentifier(name)
        self._world_position = (0.0, 0.0, 0.0)

    def _world_angle(self) -> float:
        own = math.radians(self.local_euler[2])
        if self.parent is None:
            return own
        return self.parent._world_angle() + own

    @property
    def position(self) -> tuple[float, float, float]:
        if self.parent is None:
            return self._world_position
        parent_position = self.parent.position
        parent_angle = self.parent._world_angle()
        offset = self.local_position or (0.0, 0.0, 0.0)
        cos_a = math.cos(parent_angle)
        sin_a = math.sin(parent_angle)
        rotated = (
            offset[0] * cos_a - offset[1] * sin_a,
            offset[0] * sin_a + offset[1] * cos_a,
            offset[2],
        )
        return (
            parent_position[0] + rotated[0],
            parent_position[1] + rotated[1],
            parent_position[2] + rotated[2],
        )

    def set_local_rotation(self, x: float, y: float, z: float) -> None:
        self.local_euler = (x, y, z)


class KinematicFakeSkeleton(FakeRigSkeleton):
    """Adds ``find_bone``, so the solver runs IK against ``KinematicFakeBone``s."""

    def __init__(self, label: str, bones: list[KinematicFakeBone]) -> None:
        super().__init__(label, bones)
        self._by_name = {bone.name: bone for bone in bones}

    def find_bone(self, name: str) -> KinematicFakeBone:
        return self._by_name[name]
