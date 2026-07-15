from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, cast

from .program import EnvironmentProgram

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class RunModels:
    builder: str
    actor: str


@dataclass(frozen=True)
class FrozenEnvironment:
    """An immutable-by-interface, content-addressed environment program."""

    _canonical_json: bytes
    content_hash: str

    @property
    def program(self) -> EnvironmentProgram:
        """Return a detached copy of the validated environment-program JSON."""

        return cast(EnvironmentProgram, copy.deepcopy(json.loads(self._canonical_json)))


def freeze_environment(program: Mapping[str, Any]) -> FrozenEnvironment:
    canonical = json.dumps(program, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return FrozenEnvironment(canonical, hashlib.sha256(canonical).hexdigest())
