import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from gi_env_gen.builder import AcceptedBuild, BuildRequest, Diagnostic, build
from gi_env_gen.openai_provider import BUILDER_INSTRUCTIONS, OpenAIProvider
from gi_env_gen.structured_output import (
    CONDITION_OPERATIONS,
    EFFECT_OPERATIONS,
    MANIFEST_SCHEMA,
    build_response_schema,
    manifest_from_generated,
)

from .fixtures import (
    bounded_repeat_build_response,
    possession_prerequisite_build_response,
    pursuit_build_response,
    push_trigger_build_response,
    reach_build_response,
    timed_build_response,
)


class FakeResponses:
    def __init__(self, *outputs: dict[str, Any]) -> None:
        self.outputs = list(outputs)
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        output = self.outputs.pop(0) if self.outputs else {
            "action": "TRAVEL",
            "arguments": {"heading": "RIGHT"},
        }
        return SimpleNamespace(output_text=json.dumps(output))


class FailingResponses:
    def create(self, **request: Any) -> SimpleNamespace:
        raise RuntimeError("simulated provider failure")


def test_json_mode_is_declared_in_the_request_input() -> None:
    responses = FakeResponses()
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    provider.choose_action({"available_actions": []})

    request = responses.requests[0]
    assert "JSON" in request["input"]
    assert request["text"] == {"format": {"type": "json_object"}}


def test_builder_sends_complete_stateless_repair_context() -> None:
    response = reach_build_response()
    responses = FakeResponses(manifest_from_generated(response), response)
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))
    previous = {"status": "generated", "interpretation": ["Reach it."]}
    request = BuildRequest(
        "original request",
        ("Reach it.",),
        previous,
        (Diagnostic("references", "UNKNOWN_ENTITY", "environment.actor", "Unknown."),),
    )

    provider.generate_build(request)

    assert len(responses.requests) == 2
    sent = responses.requests[0]["input"]
    assert '"original_prompt": "original request"' in sent
    assert '"previous_response"' in sent
    assert '"UNKNOWN_ENTITY"' in sent

    manifest_format = responses.requests[0]["text"]["format"]
    assert manifest_format["type"] == "json_schema"
    assert manifest_format["name"] == "builder_manifest"
    assert manifest_format["strict"] is True

    build_format = responses.requests[1]["text"]["format"]
    assert build_format["type"] == "json_schema"
    assert build_format["name"] == "generated_build_response"
    assert build_format["strict"] is True
    assert build_format["schema"] == build_response_schema(manifest_from_generated(response))


def test_builder_can_observe_complete_structured_response_evidence() -> None:
    response = reach_build_response()
    manifest = manifest_from_generated(response)
    responses = FakeResponses(manifest, response)
    observed: list[Any] = []
    provider = OpenAIProvider(
        client=SimpleNamespace(responses=responses),
        structured_response_observer=observed.append,
    )

    assert provider.generate_build(BuildRequest("Reach it", None, None, ())) == response

    assert len(observed) == 2
    assert observed[0].name == "builder_manifest"
    assert observed[0].schema == MANIFEST_SCHEMA
    assert observed[0].output == manifest
    assert observed[1].name == "generated_build_response"
    assert observed[1].schema == build_response_schema(manifest)
    assert observed[1].output == response


def test_builder_observes_a_failed_physical_structured_call() -> None:
    observed: list[Any] = []
    provider = OpenAIProvider(
        client=SimpleNamespace(responses=FailingResponses()),
        structured_response_observer=observed.append,
    )

    with pytest.raises(RuntimeError, match="simulated provider failure"):
        provider.generate_build(BuildRequest("Reach it", None, None, ()))

    assert len(observed) == 1
    assert observed[0].name == "builder_manifest"
    assert observed[0].schema == MANIFEST_SCHEMA
    assert observed[0].output is None
    assert observed[0].error == "simulated provider failure"


def test_every_supported_fixture_satisfies_its_generated_strict_schema() -> None:
    event_response = reach_build_response()
    event_response["environment"]["actions"][0]["effects"].append(
        {"operation": "emit", "event": "arrived", "target": "beacon"}
    )
    event_response["environment"]["objectives"][0]["satisfied_when"] = {
        "operation": "event_occurred",
        "event": "arrived",
        "target": "beacon",
        "scope": "current_step",
    }
    responses = (
        reach_build_response(),
        push_trigger_build_response(),
        possession_prerequisite_build_response(),
        bounded_repeat_build_response(),
        pursuit_build_response(),
        timed_build_response(),
        event_response,
    )
    observed_conditions: set[str] = set()
    observed_effects: set[str] = set()
    for response in responses:
        validator = Draft202012Validator(build_response_schema(manifest_from_generated(response)))

        assert list(Draft202012Validator(MANIFEST_SCHEMA).iter_errors(manifest_from_generated(response))) == []
        assert list(validator.iter_errors(response)) == []
        _collect_operations(response["environment"], observed_conditions, observed_effects)
    assert observed_conditions == CONDITION_OPERATIONS
    assert observed_effects == EFFECT_OPERATIONS


def test_manifest_schema_rejects_reserved_entity_tokens() -> None:
    manifest = manifest_from_generated(reach_build_response())
    manifest["plan"]["entities"][0]["token"] = "#"

    assert list(Draft202012Validator(MANIFEST_SCHEMA).iter_errors(manifest))


def test_strict_schema_rejects_malformed_operation_fields_and_unknown_operations() -> None:
    response = bounded_repeat_build_response()
    validator = Draft202012Validator(build_response_schema(manifest_from_generated(response)))
    malformed = deepcopy(response)
    malformed["environment"]["actions"][0]["effects"][0]["unexpected"] = True
    wrong_type = deepcopy(response)
    wrong_type["environment"]["actions"][0]["effects"][0]["effects"] = "move"
    unknown = deepcopy(response)
    unknown["environment"]["actions"][0]["effects"][0]["operation"] = "slide"
    extra_top_level = deepcopy(response)
    extra_top_level["explanation"] = "not part of the contract"
    missing_field = deepcopy(response)
    del missing_field["solution"]
    empty_interpretation = deepcopy(response)
    empty_interpretation["interpretation"] = []

    assert list(validator.iter_errors(malformed))
    assert list(validator.iter_errors(wrong_type))
    assert list(validator.iter_errors(unknown))
    assert list(validator.iter_errors(extra_top_level))
    assert list(validator.iter_errors(missing_field))
    assert list(validator.iter_errors(empty_interpretation))


def test_unsupported_response_uses_its_own_strict_schema() -> None:
    manifest = {
        "interpretation": ["The request requires unsupported continuous physics."],
        "plan": {
            "status": "unsupported",
            "reason": "Continuous physics is outside the rule language.",
        },
    }
    response = {
        "status": "unsupported",
        "interpretation": manifest["interpretation"],
        "reason": manifest["plan"]["reason"],
    }
    responses = FakeResponses(manifest, response)
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    assert provider.generate_build(BuildRequest("fluid", None, None, ())) == response
    output_format = responses.requests[1]["text"]["format"]
    assert output_format["name"] == "unsupported_build_response"
    assert output_format["strict"] is True
    invalid = deepcopy(response)
    invalid["reason"] = ""
    assert list(Draft202012Validator(output_format["schema"]).iter_errors(invalid))


def test_semantic_reference_validation_and_repair_still_run_after_structured_output() -> None:
    rejected = reach_build_response()
    rejected["environment"]["actions"][0]["effects"][0]["entity"] = "missing"
    repaired = reach_build_response()
    responses = FakeResponses(
        manifest_from_generated(rejected),
        rejected,
        manifest_from_generated(repaired),
        repaired,
    )
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    result = build("Reach the beacon", provider)

    assert isinstance(result, AcceptedBuild)
    assert len(result.attempts) == 2
    assert '"UNKNOWN_ENTITY"' in responses.requests[2]["input"]
    assert result.validation.replay[-1].state.status == "success"


def test_schema_valid_manifest_name_errors_enter_the_existing_repair_loop() -> None:
    rejected = reach_build_response()
    rejected["environment"]["actions"].append(
        deepcopy(rejected["environment"]["actions"][0])
    )
    repaired = reach_build_response()
    responses = FakeResponses(
        manifest_from_generated(rejected),
        rejected,
        manifest_from_generated(repaired),
        repaired,
    )
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    result = build("Reach the beacon", provider)

    assert isinstance(result, AcceptedBuild)
    assert result.attempts[0].diagnostics[0].code == "MANIFEST_DRIFT"
    assert len(result.attempts) == 2


def test_omitting_a_manifest_action_enters_the_existing_repair_loop() -> None:
    planned = bounded_repeat_build_response()
    incomplete = deepcopy(planned)
    incomplete["environment"]["actions"].pop()
    repaired = bounded_repeat_build_response()
    responses = FakeResponses(
        manifest_from_generated(planned),
        incomplete,
        manifest_from_generated(repaired),
        repaired,
    )
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    result = build("Create repeated movement", provider)

    assert isinstance(result, AcceptedBuild)
    assert result.attempts[0].diagnostics[0].code == "MANIFEST_DRIFT"
    assert len(result.attempts) == 2


def test_schema_covers_every_optional_operation_variant() -> None:
    possession = possession_prerequisite_build_response()
    possession_validator = Draft202012Validator(
        build_response_schema(manifest_from_generated(possession))
    )
    for destination in (None, "goal", [2, 1]):
        candidate = deepcopy(possession)
        candidate["environment"]["actions"][1]["effects"][0]["destination"] = destination
        assert list(possession_validator.iter_errors(candidate)) == []

    directed = push_trigger_build_response()
    directed_validator = Draft202012Validator(
        build_response_schema(manifest_from_generated(directed))
    )
    without_direction = deepcopy(directed)
    del without_direction["environment"]["actions"][1]["allowed_when"][0]["direction"]
    without_target = deepcopy(directed)
    del without_target["environment"]["actions"][1]["effects"][2]["target"]
    assert list(directed_validator.iter_errors(without_direction)) == []
    assert list(directed_validator.iter_errors(without_target)) == []

    repeated = bounded_repeat_build_response()
    repeated_validator = Draft202012Validator(
        build_response_schema(manifest_from_generated(repeated))
    )
    targeted_emit = deepcopy(repeated)
    targeted_emit["environment"]["actions"][1]["effects"][0]["effects"][0][
        "target"
    ] = "explorer"
    assert list(repeated_validator.iter_errors(targeted_emit)) == []


def test_builder_instructions_do_not_duplicate_the_json_schema() -> None:
    assert "additionalProperties" not in BUILDER_INSTRUCTIONS
    assert '"required"' not in BUILDER_INSTRUCTIONS
    assert "$defs" not in BUILDER_INSTRUCTIONS


def _collect_operations(value: Any, conditions: set[str], effects: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_operations(item, conditions, effects)
        return
    if not isinstance(value, dict):
        return
    operation = value.get("operation")
    if isinstance(operation, str):
        if operation in EFFECT_OPERATIONS:
            effects.add(operation)
        if operation in CONDITION_OPERATIONS:
            conditions.add(operation)
    for child in value.values():
        _collect_operations(child, conditions, effects)
