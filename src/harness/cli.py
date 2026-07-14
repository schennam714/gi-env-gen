from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .acting import ActingUpdates, play
from .builder import (
    AcceptedBuild,
    BuildResult,
    GenerationFailed,
    ProviderFailed,
    UnsupportedBuild,
    build,
)
from .dashboard import (
    DASHBOARD_THEME,
    DashboardProjection,
    LiveDashboard,
    generation_waiting,
    log_summary,
    render_dashboard,
)
from .evidence import save_run_evidence
from .model import RunModels
from .openai_provider import DEFAULT_MODEL, MissingCredential, OpenAIProvider


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate, validate, freeze, and play a 2D world.")
    parser.add_argument("prompt", help="Freeform environment request")
    parser.add_argument(
        "--actor",
        default=DEFAULT_MODEL,
        metavar="MODEL",
        help=f"Acting model (builder is always {DEFAULT_MODEL})",
    )
    parser.add_argument("--max-steps", type=_positive_int, default=20)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Directory for this run's five machine-readable evidence artifacts",
    )
    args = parser.parse_args(argv)
    models = RunModels(builder=DEFAULT_MODEL, actor=args.actor)
    evidence_dir = args.evidence_dir or _default_evidence_directory()
    try:
        builder_provider = OpenAIProvider(model=models.builder)
        actor_provider = OpenAIProvider(model=models.actor)
    except MissingCredential as error:
        parser.error(str(error))
    console = Console(theme=DASHBOARD_THEME, highlight=False)
    live: Live | None = None
    if console.is_terminal:
        live = Live(
            generation_waiting(models),
            console=console,
            screen=False,
            transient=False,
            auto_refresh=False,
            vertical_overflow="crop",
        )
        live.start(refresh=True)
    else:
        console.print(f"Builder: {models.builder} · Actor: {models.actor}")
    try:
        result = build(args.prompt, builder_provider)
        if isinstance(result, UnsupportedBuild):
            return _finish_without_acting(
                result,
                final_status="unsupported",
                exit_code=2,
                evidence_dir=evidence_dir,
                original_prompt=args.prompt,
                models=models,
                max_steps=args.max_steps,
                console=console,
                live=live,
            )
        if isinstance(result, ProviderFailed):
            return _finish_without_acting(
                result,
                final_status="provider_failure",
                exit_code=5,
                evidence_dir=evidence_dir,
                original_prompt=args.prompt,
                models=models,
                max_steps=args.max_steps,
                console=console,
                live=live,
            )
        if isinstance(result, GenerationFailed):
            return _finish_without_acting(
                result,
                final_status="retry_exhaustion",
                exit_code=3,
                evidence_dir=evidence_dir,
                original_prompt=args.prompt,
                models=models,
                max_steps=args.max_steps,
                console=console,
                live=live,
            )
        assert isinstance(result, AcceptedBuild)
        projection = DashboardProjection(
            models=models,
            environment=result.environment,
            max_steps=args.max_steps,
            evidence_path=evidence_dir,
        )
        updates: ActingUpdates = projection
        if live is not None:
            live.update(
                render_dashboard(
                    projection.frame,
                    width=console.width,
                    height=console.height,
                ),
                refresh=True,
            )
            updates = LiveDashboard(projection, live, console)
        acting = play(
            args.prompt,
            result,
            actor_provider,
            max_steps=args.max_steps,
            updates=updates,
        )
        save_run_evidence(
            evidence_dir,
            original_prompt=args.prompt,
            models=models,
            max_steps=args.max_steps,
            build_result=result,
            acting_result=acting,
        )
        if live is not None:
            live.update(
                render_dashboard(
                    projection.frame,
                    width=console.width,
                    height=console.height,
                ),
                refresh=True,
            )
        else:
            for line in log_summary(projection.frame, builder_attempts=len(result.attempts)):
                console.print(line, soft_wrap=True)
        return 0 if acting.status == "success" else 4
    finally:
        if live is not None:
            live.stop()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _finish_without_acting(
    result: BuildResult,
    *,
    final_status: str,
    exit_code: int,
    evidence_dir: Path,
    original_prompt: str,
    models: RunModels,
    max_steps: int,
    console: Console,
    live: Live | None,
) -> int:
    save_run_evidence(
        evidence_dir,
        original_prompt=original_prompt,
        models=models,
        max_steps=max_steps,
        build_result=result,
    )
    reason = getattr(result, "reason", None)
    interpretation = getattr(result, "interpretation", ())
    lines = [
        f"Builder: {models.builder} · Actor: {models.actor}",
        f"Generation: {final_status} · {len(result.attempts)} builder attempts",
        *(f"- {item}" for item in interpretation),
    ]
    if reason is not None:
        lines.append(f"Reason: {reason}")
    lines.append(f"Evidence: {evidence_dir}")
    if live is None:
        for line in lines:
            console.print(line, soft_wrap=True)
    else:
        text = Text("\n".join(lines))
        live.update(
            Panel(Group(text), title="Generation stopped", border_style="red"),
            refresh=True,
        )
    return exit_code


def _default_evidence_directory() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return Path("run-evidence") / timestamp


if __name__ == "__main__":
    raise SystemExit(main())
