from types import SimpleNamespace
from typing import Any

from gi_env_gen.builder import BuildRequest, Diagnostic
from gi_env_gen.openai_provider import OpenAIProvider


class FakeResponses:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    def create(self, **request: Any) -> SimpleNamespace:
        self.request = request
        return SimpleNamespace(output_text='{"action":"TRAVEL","arguments":{"heading":"RIGHT"}}')


def test_json_mode_is_declared_in_the_request_input() -> None:
    responses = FakeResponses()
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    provider.choose_action({"available_actions": []})

    assert responses.request is not None
    assert "JSON" in responses.request["input"]
    assert responses.request["text"] == {"format": {"type": "json_object"}}


def test_builder_sends_complete_stateless_repair_context() -> None:
    responses = FakeResponses()
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))
    previous = {"status": "generated", "interpretation": ["Reach it."]}
    request = BuildRequest(
        "original request",
        ("Reach it.",),
        previous,
        (Diagnostic("references", "UNKNOWN_ENTITY", "environment.actor", "Unknown."),),
    )

    provider.generate_build(request)

    assert responses.request is not None
    sent = responses.request["input"]
    assert '"original_prompt": "original request"' in sent
    assert '"previous_response"' in sent
    assert '"UNKNOWN_ENTITY"' in sent
