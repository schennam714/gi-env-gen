import json
import sys
from typing import Any

from gi_env_gen.openai_provider import StructuredResponseTrace
from gi_env_gen.structured_output import (
    MANIFEST_SCHEMA,
    build_response_schema,
    manifest_from_generated,
)
from scripts import smoke_builder_matrix

from .fixtures import bounded_repeat_build_response


class TraceProviderFake:
    def __init__(
        self,
        *,
        model: str,
        structured_response_observer: Any = None,
    ) -> None:
        self.observer = structured_response_observer

    def generate_build(self, request: Any) -> dict[str, Any]:
        response = bounded_repeat_build_response()
        manifest = manifest_from_generated(response)
        if self.observer is not None:
            self.observer(
                StructuredResponseTrace(
                    "builder_manifest",
                    MANIFEST_SCHEMA,
                    self.manifest_output(manifest),
                )
            )
            self.observer(
                StructuredResponseTrace(
                    "generated_build_response",
                    build_response_schema(manifest),
                    response,
                )
            )
        return response

    def manifest_output(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return manifest


def test_trace_reports_complete_live_shapes_and_private_replay(
    monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(smoke_builder_matrix, "OpenAIProvider", TraceProviderFake)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke_builder_matrix.py", "--case", "bounded_repeat", "--trace"],
    )

    assert smoke_builder_matrix.main() == 0

    report = json.loads(capsys.readouterr().out)
    case = report["cases"][0]
    trace = case["trace"]
    response = bounded_repeat_build_response()
    manifest = manifest_from_generated(response)
    assert trace["prompt"] == smoke_builder_matrix.CASES["bounded_repeat"]
    assert trace["physical_openai_calls"] == 2
    assert trace["structured_responses"] == [
        {
            "name": "builder_manifest",
            "schema": MANIFEST_SCHEMA,
            "output": manifest,
            "schema_error_count": 0,
            "schema_errors": [],
        },
        {
            "name": "generated_build_response",
            "schema": build_response_schema(manifest),
            "output": response,
            "schema_error_count": 0,
            "schema_errors": [],
        },
    ]
    assert trace["build_attempts"] == [{"response": response, "diagnostics": []}]
    evidence = trace["private_validation_evidence"]
    assert evidence["proposed_solution"] == response["solution"]
    assert evidence["replay"][0]["state"]["status"] == "success"
    assert evidence["replay"][0]["state"]["positions"]["explorer"] == [7, 1]
    assert evidence["final_state"] == evidence["replay"][-1]["state"]
    assert evidence["never_sent_to_acting_llm"] is True


def test_compact_report_omits_trace_evidence(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(smoke_builder_matrix, "OpenAIProvider", TraceProviderFake)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke_builder_matrix.py", "--case", "bounded_repeat"],
    )

    assert smoke_builder_matrix.main() == 0

    report = json.loads(capsys.readouterr().out)
    assert report["cases"] == [
        {
            "attempts": 1,
            "case": "bounded_repeat",
            "detail": None,
            "outcome": "first_attempt",
        }
    ]


class InvalidTraceProviderFake(TraceProviderFake):
    def manifest_output(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return {**manifest, "unexpected": True}


def test_trace_surfaces_local_schema_errors(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(smoke_builder_matrix, "OpenAIProvider", InvalidTraceProviderFake)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke_builder_matrix.py", "--case", "bounded_repeat", "--trace"],
    )

    assert smoke_builder_matrix.main() == 1

    report = json.loads(capsys.readouterr().out)
    manifest_call = report["cases"][0]["trace"]["structured_responses"][0]
    assert manifest_call["schema_error_count"] == 1
    assert manifest_call["schema_errors"][0]["path"] == []
    assert "Additional properties are not allowed" in manifest_call["schema_errors"][0][
        "message"
    ]


class FailedCallProviderFake(TraceProviderFake):
    def generate_build(self, request: Any) -> dict[str, Any]:
        self.observer(
            StructuredResponseTrace(
                "builder_manifest",
                MANIFEST_SCHEMA,
                None,
                "simulated provider failure",
            )
        )
        raise RuntimeError("simulated provider failure")


def test_trace_counts_and_reports_a_failed_physical_call(
    monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(smoke_builder_matrix, "OpenAIProvider", FailedCallProviderFake)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke_builder_matrix.py", "--case", "bounded_repeat", "--trace"],
    )

    assert smoke_builder_matrix.main() == 1

    report = json.loads(capsys.readouterr().out)
    case = report["cases"][0]
    assert case["outcome"] == "provider_failure"
    assert case["trace"]["physical_openai_calls"] == 1
    assert case["trace"]["structured_responses"] == [
        {
            "name": "builder_manifest",
            "schema": MANIFEST_SCHEMA,
            "output": None,
            "error": "simulated provider failure",
            "schema_error_count": None,
            "schema_errors": [],
        }
    ]
