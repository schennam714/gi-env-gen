from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class FrozenEnvironment:
    """An immutable-by-interface, content-addressed environment program."""

    _canonical_json: bytes
    content_hash: str

    @property
    def program(self) -> JsonObject:
        return copy.deepcopy(json.loads(self._canonical_json))


def freeze_environment(program: Mapping[str, Any]) -> FrozenEnvironment:
    canonical = json.dumps(program, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return FrozenEnvironment(canonical, hashlib.sha256(canonical).hexdigest())

