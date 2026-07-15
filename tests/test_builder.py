from copy import deepcopy
from typing import Any

from harness.builder import (
    AcceptedBuild,
    BuildRequest,
    GenerationFailed,
    ProviderFailed,
    UnsupportedBuild,
    build,
)

from .fixtures import reach_build_response


class FakeProvider:
    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[BuildRequest] = []

    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        self.requests.append(deepcopy(request))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


def invalid_reference_response() -> dict[str, Any]:
    response = reach_build_response()
    response["environment"]["actions"][0]["effects"][0]["entity"] = "missing"
    return response


def test_builder_repairs_rejected_program_with_complete_stateless_request() -> None:
    rejected = invalid_reference_response()
    repaired = reach_build_response()
    provider = FakeProvider(rejected, repaired)

    result = build("Make a tiny world where I reach a beacon.", provider)

    assert isinstance(result, AcceptedBuild)
    assert len(result.environment.content_hash) == 64
    assert result.validation.replay[-1].state.status == "success"
    assert "solution" not in result.environment.program
    assert len(result.attempts) == 2
    repair = provider.requests[1]
    assert repair.original_prompt == "Make a tiny world where I reach a beacon."
    assert repair.frozen_interpretation == ("Move the explorer to the beacon.",)
    assert repair.previous_response == rejected
    assert repair.diagnostics[0].path == "environment.actions[0].effects[0].entity"
    assert repair.diagnostics[0].phase == "references"


def test_builder_rejects_interpretation_drift_and_keeps_original_frozen() -> None:
    first = invalid_reference_response()
    drifted = reach_build_response()
    drifted["interpretation"] = ["A weakened request."]
    provider = FakeProvider(first, drifted, reach_build_response())

    result = build("Reach it", provider)

    assert isinstance(result, AcceptedBuild)
    assert result.interpretation == ("Move the explorer to the beacon.",)
    assert provider.requests[2].diagnostics[0].code == "INTERPRETATION_DRIFT"
    assert provider.requests[2].previous_response == drifted


def test_repair_cannot_evade_frozen_interpretation_by_switching_to_unsupported() -> None:
    unsupported = {
        "status": "unsupported",
        "interpretation": ["A weakened request."],
        "reason": "Cannot do it.",
    }
    provider = FakeProvider(invalid_reference_response(), unsupported, reach_build_response())

    result = build("Reach it", provider)

    assert isinstance(result, AcceptedBuild)
    assert provider.requests[2].diagnostics[0].code == "INTERPRETATION_DRIFT"


def test_builder_stops_after_five_rejections_with_attempt_attribution() -> None:
    provider = FakeProvider(
        invalid_reference_response(),
        invalid_reference_response(),
        invalid_reference_response(),
        invalid_reference_response(),
        invalid_reference_response(),
    )

    result = build("Reach it", provider)

    assert isinstance(result, GenerationFailed)
    assert result.reason == "retry_exhausted"
    assert len(result.attempts) == 5
    assert len(provider.requests) == 5


def test_builder_stops_immediately_on_unsupported_and_preserves_explanation() -> None:
    response = {
        "status": "unsupported",
        "interpretation": ["The request requires continuous fluid physics."],
        "reason": "The declared operation vocabulary cannot represent fluids exactly.",
    }
    provider = FakeProvider(response, reach_build_response())

    result = build("Simulate an ocean", provider)

    assert isinstance(result, UnsupportedBuild)
    assert result.interpretation == tuple(response["interpretation"])
    assert result.reason == response["reason"]
    assert len(provider.requests) == 1
    assert len(result.attempts) == 1


def test_malformed_unsupported_response_has_an_exact_shape_path() -> None:
    malformed = {
        "status": "unsupported",
        "interpretation": ["Cannot represent it."],
        "reason": 42,
    }
    provider = FakeProvider(malformed, reach_build_response())

    result = build("Cannot represent it", provider)

    assert isinstance(result, AcceptedBuild)
    assert provider.requests[1].diagnostics[0].path == "reason"


def test_builder_attributes_provider_failure_without_retrying() -> None:
    provider = FakeProvider(RuntimeError("service unavailable"), reach_build_response())

    result = build("Reach it", provider)

    assert isinstance(result, ProviderFailed)
    assert result.reason == "service unavailable"
    assert result.attempts == ()
    assert len(provider.requests) == 1


def test_shape_errors_are_path_specific_and_do_not_freeze_interpretation() -> None:
    malformed = reach_build_response()
    del malformed["environment"]["map"]
    provider = FakeProvider(malformed, reach_build_response())

    result = build("Reach it", provider)

    assert isinstance(result, AcceptedBuild)
    assert provider.requests[1].frozen_interpretation is None
    diagnostic = provider.requests[1].diagnostics[0]
    assert diagnostic.phase == "shape"
    assert diagnostic.path == "environment.map"


def test_extra_and_wrong_typed_fields_have_exact_shape_paths() -> None:
    extra = reach_build_response()
    extra["explanation"] = "not in the contract"
    wrong_type = reach_build_response()
    wrong_type["environment"] = []
    provider = FakeProvider(extra, wrong_type, reach_build_response())

    result = build("Reach it", provider)

    assert isinstance(result, AcceptedBuild)
    assert provider.requests[1].diagnostics[0].path == "explanation"
    assert provider.requests[2].diagnostics[0].path == "environment"


def test_builder_never_repairs_geometry_or_rules_itself() -> None:
    malformed = reach_build_response()
    malformed["environment"]["map"][1] += "."
    provider = FakeProvider(*([malformed] * 5))

    result = build("Reach it", provider)

    assert isinstance(result, GenerationFailed)
    assert all(attempt.response == malformed for attempt in result.attempts)
    assert all(request.previous_response == malformed for request in provider.requests[1:])
