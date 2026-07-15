from copy import deepcopy
from typing import Any

from harness.builder import BuildRequest, GenerationFailed, build
from harness.openai_provider import BUILDER_INSTRUCTIONS, MANIFEST_INSTRUCTIONS

from .test_cli import reach_build_response


class RejectedBuildProviderFake:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        return deepcopy(self.response)


def test_unused_legend_token_diagnostic_names_token_entity_and_count() -> None:
    rejected = reach_build_response()
    rejected["environment"]["legend"]["W"] = {
        "id": "wall",
        "properties": {"symbol": "#", "solid": True},
    }

    result = build("Reach it", RejectedBuildProviderFake(rejected))

    assert isinstance(result, GenerationFailed)
    diagnostic = result.attempts[0].diagnostics[0]
    assert diagnostic.code == "LEGEND_TOKEN_COUNT"
    assert diagnostic.path == "environment.legend.W"
    assert diagnostic.message == (
        "Legend token 'W' for entity 'wall' occurs 0 times; expected exactly once."
    )


def test_builder_prompts_distinguish_reserved_terrain_from_entity_tokens() -> None:
    for instructions in (MANIFEST_INSTRUCTIONS, BUILDER_INSTRUCTIONS):
        assert "Do not declare legend entities for static # walls or . floors" in instructions
        assert "Every declared legend token must occur exactly once" in instructions


def test_builder_prompts_favor_compact_numeric_countdown_rules() -> None:
    for instructions in (MANIFEST_INSTRUCTIONS, BUILDER_INSTRUCTIONS):
        assert (
            "Represent numeric counters, budgets, and timers as global numeric values"
            in instructions
        )
    assert "decrement them with one change_value effect" in BUILDER_INSTRUCTIONS
    assert "Do not enumerate one automatic rule per numeric state" in BUILDER_INSTRUCTIONS
