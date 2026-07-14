import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from harness import cli
from harness.dashboard import DASHBOARD_THEME


def reach_build_response() -> dict[str, Any]:
    """A provider-fake response, never a user-facing generated environment."""
    return {
        "status": "generated",
        "interpretation": ["Move the explorer to the beacon."],
        "environment": {
            "actor": "explorer",
            "map": ["#####", "#A.B#", "#####"],
            "legend": {
                "A": {
                    "id": "explorer",
                    "properties": {"symbol": "@", "solid": True},
                },
                "B": {
                    "id": "beacon",
                    "properties": {"symbol": "X", "solid": False},
                },
            },
            "values": {},
            "actions": [
                {
                    "name": "TRAVEL",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [
                        {
                            "operation": "can_move",
                            "entity": "explorer",
                            "direction": "$heading",
                        }
                    ],
                    "effects": [
                        {
                            "operation": "move",
                            "entity": "explorer",
                            "direction": "$heading",
                        }
                    ],
                }
            ],
            "after_action": [],
            "objectives": [
                {
                    "id": "reach_beacon",
                    "description": "Reach the beacon.",
                    "satisfied_when": {
                        "operation": "at",
                        "first": "explorer",
                        "second": "beacon",
                    },
                }
            ],
            "failures": [],
        },
        "solution": [
            {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
            {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
        ],
    }


class ReviewerProviderFake:
    def __init__(self) -> None:
        self._build_response = reach_build_response()
        self._actions = deepcopy(self._build_response["solution"])
        self.observations: list[dict[str, Any]] = []

    def generate_build(self, request: Any) -> dict[str, Any]:
        return deepcopy(self._build_response)

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return self._actions[len(self.observations) - 1]


def test_reviewer_cli_separates_program_proof_and_independent_acting_evidence(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    provider = ReviewerProviderFake()
    monkeypatch.setattr(cli, "OpenAIProvider", lambda **_: provider)
    evidence_dir = tmp_path / "reviewer-evidence"

    exit_code = cli.main(
        [
            "Reach the beacon",
            "--model",
            "reviewer-fake",
            "--max-steps",
            "5",
            "--evidence-dir",
            str(evidence_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Generating with reviewer-fake..." in output
    assert "accepted after 1 builder attempt" in output
    assert "Acting: success · step 2/5" in output
    assert "Objectives: 1/1 complete · Failures: none triggered" in output
    assert f"Evidence: {evidence_dir}" in output
    assert "\x1b[" not in output
    assert '"environment"' not in output

    generation = _read_json(evidence_dir / "generation.json")
    accepted = _read_json(evidence_dir / "accepted-environment.json")
    validation = _read_json(evidence_dir / "private-validation.json")
    acting = _read_json(evidence_dir / "acting-rollout.json")
    summary = _read_json(evidence_dir / "summary.json")

    assert generation["original_prompt"] == "Reach the beacon"
    assert generation["model"] == "reviewer-fake"
    assert generation["attempts"][0]["diagnostics"] == []
    assert "solution" not in json.dumps(generation)
    assert accepted["environment_hash"] == validation["environment_hash"] == acting["environment_hash"]
    assert "solution" not in accepted
    assert validation["proposed_solution"] == reach_build_response()["solution"]
    assert validation["outcome"] == "success"
    assert acting["steps"][0]["observation"] == json.loads(
        json.dumps(provider.observations[0])
    )
    assert acting["steps"][0]["response_attempts"][0]["response"] == reach_build_response()["solution"][0]
    assert acting["steps"][0]["action"] == reach_build_response()["solution"][0]
    assert acting["steps"][0]["applicability_result"] is True
    assert acting["steps"][0]["direct_effects"]
    assert acting["steps"][0]["automatic_effects"] == []
    assert acting["steps"][-1]["objective_changes"] == ["reach_beacon"]
    assert acting["steps"][-1]["resulting_state"]["status"] == "success"
    assert acting["final_status"] == summary["final_status"] == "success"
    assert "solution" not in repr(provider.observations)
    assert "proposed_solution" not in json.dumps(acting)


def test_reviewer_evidence_distinguishes_invalid_attempts_from_retry_exhaustion(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    rejected = reach_build_response()
    rejected["environment"]["actions"][0]["effects"][0]["entity"] = "missing"

    class RejectedProviderFake:
        def generate_build(self, request: Any) -> dict[str, Any]:
            return deepcopy(rejected)

    monkeypatch.setattr(cli, "OpenAIProvider", lambda **_: RejectedProviderFake())
    evidence_dir = tmp_path / "rejected-evidence"

    exit_code = cli.main(
        ["Reach the beacon", "--evidence-dir", str(evidence_dir)]
    )

    assert exit_code == 3
    generation = _read_json(evidence_dir / "generation.json")
    summary = _read_json(evidence_dir / "summary.json")
    assert generation["outcome"] == "retry_exhaustion"
    assert [attempt["outcome"] for attempt in generation["attempts"]] == [
        "invalid_generated_program",
        "invalid_generated_program",
        "invalid_generated_program",
    ]
    assert summary["final_status"] == "retry_exhaustion"


def test_terminal_dashboard_uses_normal_buffer_and_leaves_final_frame(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    provider = ReviewerProviderFake()
    monkeypatch.setattr(cli, "OpenAIProvider", lambda **_: provider)
    monkeypatch.chdir(tmp_path)
    terminal_output = StringIO()
    terminal_console = Console(
        file=terminal_output,
        width=72,
        height=24,
        force_terminal=True,
        color_system="standard",
        theme=DASHBOARD_THEME,
    )
    monkeypatch.setattr(cli, "Console", lambda **_: terminal_console)

    exit_code = cli.main(
        [
            "Reach the beacon",
            "--model",
            "reviewer-fake",
            "--max-steps",
            "5",
            "--evidence-dir",
            "evidence",
        ]
    )

    assert exit_code == 0
    output = terminal_output.getvalue()
    assert "\x1b[?1049h" not in output
    assert "\x1b[?1049l" not in output
    final_frame = output[output.rfind("Reviewer dashboard") :]
    assert "reviewer-fake" in final_frame
    assert "success" in final_frame
    assert "Evidence" in final_frame
    assert "evidence" in final_frame
    assert (tmp_path / "evidence" / "acting-rollout.json").exists()


def test_reviewer_cli_fails_clearly_before_generation_when_credential_is_missing(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["Reach the beacon"])

    assert exit_info.value.code == 2
    assert "OPENAI_API_KEY is required for live generation and acting" in capsys.readouterr().err


def test_reviewer_evidence_keeps_unusable_actor_attempts_and_unchanged_state(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class UnusableActorProviderFake:
        def generate_build(self, request: Any) -> dict[str, Any]:
            return reach_build_response()

        def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
            return {"action": "UNKNOWN", "arguments": {}}

    monkeypatch.setattr(cli, "OpenAIProvider", lambda **_: UnusableActorProviderFake())
    evidence_dir = tmp_path / "unusable-actor-evidence"

    exit_code = cli.main(
        ["Reach the beacon", "--evidence-dir", str(evidence_dir)]
    )

    assert exit_code == 4
    acting = _read_json(evidence_dir / "acting-rollout.json")
    assert acting["final_status"] == "unusable_actor_output"
    assert len(acting["steps"][0]["response_attempts"]) == 3
    assert "formatting_recovery" not in acting["steps"][0]["response_attempts"][0]["observation"]
    recovery = acting["steps"][0]["response_attempts"][1]["observation"][
        "formatting_recovery"
    ]
    assert recovery["previous_response"] == {"action": "UNKNOWN", "arguments": {}}
    assert "unknown generated action" in recovery["error"]
    assert acting["steps"][0]["action"] is None
    assert acting["steps"][0]["applicability_result"] is None
    assert acting["steps"][0]["resulting_state"]["step"] == 0


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as evidence_file:
        return json.load(evidence_file)
