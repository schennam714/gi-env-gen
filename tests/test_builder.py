from copy import deepcopy
from typing import Any

from gi_env_gen.builder import AcceptedBuild, GenerationFailed, build

from .fixtures import reach_build_response


class FakeProvider:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def generate_build(self, prompt: str) -> dict[str, Any]:
        self.requests.append({"prompt": prompt})
        return deepcopy(self.response)


def test_builder_accepts_replayed_program_and_splits_solution_evidence() -> None:
    provider = FakeProvider(reach_build_response())

    result = build("Make a tiny world where I reach a beacon.", provider)

    assert isinstance(result, AcceptedBuild)
    assert len(result.environment.content_hash) == 64
    assert result.validation.solution[0]["action"] == "TRAVEL"
    assert result.validation.replay[-1].state.status == "success"
    assert "solution" not in result.environment.program


def test_builder_rejects_an_objective_satisfied_at_reset() -> None:
    response = reach_build_response()
    response["environment"]["map"] = ["#####", "#AB.#", "#####"]
    response["environment"]["legend"]["A"]["properties"]["solid"] = False
    response["environment"]["legend"]["B"]["properties"]["solid"] = False
    response["environment"]["objectives"][0]["satisfied_when"] = {
        "operation": "at",
        "first": "explorer",
        "second": "explorer",
    }

    result = build("Already done", FakeProvider(response))

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "OBJECTIVE_SATISFIED_AT_RESET"


def test_builder_rejects_non_contract_fields_and_non_ascii_symbols() -> None:
    extra_field = reach_build_response()
    extra_field["explanation"] = "not part of the contract"
    invalid_symbol = reach_build_response()
    invalid_symbol["environment"]["legend"]["A"]["properties"]["symbol"] = "🤖"

    extra_result = build("Reach it", FakeProvider(extra_field))
    symbol_result = build("Reach it", FakeProvider(invalid_symbol))

    assert isinstance(extra_result, GenerationFailed)
    assert extra_result.diagnostics[0].code == "INVALID_BUILD_RESPONSE"
    assert isinstance(symbol_result, GenerationFailed)
    assert symbol_result.diagnostics[0].code == "INVALID_ENTITY_PROPERTIES"
