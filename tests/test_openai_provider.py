from types import SimpleNamespace
from typing import Any

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
