"""harness 顶层主循环；各阶段实现位于 `src.orchestration.phases`。"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from src.config import HarnessConfig
from src.agents.edit_planner import refresh_atomic_edit_plan
from src.agents.planner import recover_trace_proven_planner_checkpoint
from src.orchestration.checkpoints import (
    CheckpointTransaction,
    ResumeError,
    reconcile_completed_evaluation,
    restore_resume_state,
)
from src.orchestration.cost_tracker import CostTracker
from src.orchestration.atomic_edit_plan import write_atomic_edit_plan
from src.orchestration.accepted_tapes import stage_prior_accepted_tapes
from src.orchestration.file_comm import FileComm
from src.orchestration.edit_task_contract import (
    normalize_target_routes,
    prepare_edit_task_contract,
    read_edit_task_contract,
    resolve_task_mode,
)
from src.orchestration.edit_card import materialize_edit_card
from src.orchestration.edit_risk_tests import materialize_edit_risk_tests
from src.orchestration.phases import (
    HarnessContext,
    Verdict,
    run_build_phase,
    run_design_phase,
    run_evaluate_phase,
    run_planner_phase,
)
from src.orchestration.hidden_oracle_checks import write_hidden_oracle_checks
from src.orchestration.preimplementation_validation import (
    freeze_preimplementation_validation,
)
from src.orchestration.sprint_state import SprintState
from src.orchestration.target_profile import detect_target_profile
from src.orchestration.task_inputs import (
    stage_task_inputs,
    task_input_source_hashes,
    task_inputs_match,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _round_limit_for_task(
    config: HarnessConfig, *, task_mode: str, total_sprints: int
) -> int:
    """Return a ceiling, never a target number of rounds.

    Edit receives a wider recovery allowance because every failed round must be
    evidence-driven. Acceptance still exits immediately. Generate retains its
    smaller default and final-project mode only reserves enough room for its
    planned milestones plus a bounded recovery allowance.
    """
    if task_mode == "edit":
        return max(1, int(config.edit_max_rounds))
    # Preserve the existing Generate control where ``0`` is a deliberate
    # plan/design-only run.  The ten-round ceiling is specific to Edit.
    limit = max(0, int(config.max_rounds))
    if config.final_project_mode:
        limit = max(limit, int(total_sprints) + 3)
    return limit


def _next_round_cost_reserve(phase_metrics: dict[str, dict[str, Any]]) -> float:
    """Estimate the minimum spend needed to make the next round decision-useful.

    Once a run has measured both phases, starting another generator without
    enough budget to also evaluate it only creates an unusable partial trace.
    """
    def recorded_cost(metric: dict[str, Any]) -> float:
        value = metric.get("cost_usd")
        return float(value) if isinstance(value, (int, float)) else 0.0

    generator_costs = [
        recorded_cost(metric)
        for key, metric in phase_metrics.items()
        if key.startswith("generator_r") and isinstance(metric, dict)
    ]
    evaluator_costs = [
        recorded_cost(metric)
        for key, metric in phase_metrics.items()
        if key.startswith("evaluator_r") and isinstance(metric, dict)
    ]
    if not generator_costs or not evaluator_costs:
        return 0.0
    return max(0.50, generator_costs[-1] + evaluator_costs[-1])


def _is_planner_checkpoint(phase: str | None) -> bool:
    return _phase_kind(phase) in {"plan", "design", "build", "evaluate"}


def _reset_generate_edit_frames(file_comm: FileComm) -> None:
    """Remove baselines from an older run before a fresh Generate roadmap."""
    (file_comm.dir / "edit_dom_baseline.json").unlink(missing_ok=True)
    for path in file_comm.dir.glob("edit_dom_source_sprint_*.json"):
        path.unlink(missing_ok=True)


async def run_harness(
    user_prompt: str,
    workdir: Path,
    config: HarnessConfig,
    plan_only: bool = False,
    resume: bool = False,
    keep_frontend: bool = False,
    task_mode: str = "auto",
    input_paths: list[Path] | None = None,
    target_routes: list[str] | None = None,
    atomic_plan: dict[str, Any] | None = None,
    hidden_oracle_checks: list[dict[str, Any]] | None = None,
    prior_accepted_checks: list[list[dict[str, Any]]] | None = None,
    chain_metadata: dict[str, Any] | None = None,
) -> None:
    """执行 Planner → target-blind Validate → Generator → Evaluator 主循环。"""
    start = time.time()
    workdir.mkdir(parents=True, exist_ok=True)
    input_paths = list(input_paths or [])
    target_routes = normalize_target_routes(target_routes or [])
    if resume and (atomic_plan is not None or hidden_oracle_checks or prior_accepted_checks or chain_metadata):
        raise ResumeError(
            "structured Edit plan/oracle inputs are staged only on a fresh run"
        )
    # Validate external inputs before a fresh-run reset can discard prior
    # harness artifacts. Staging happens only after the task mode is accepted.
    if input_paths:
        task_input_source_hashes(input_paths)
    file_comm = FileComm(workdir / ".harness")
    cost_tracker = CostTracker(config.max_budget_usd)

    existing_state = file_comm.read_state()
    resumed_plan_changed = False
    if resume and not existing_state:
        recovered_planner = recover_trace_proven_planner_checkpoint(file_comm, config)
        if recovered_planner is not None:
            recovered_metrics = {"planner": recovered_planner.to_dict()}
            edit_freeze = None
            edit_contract = read_edit_task_contract(workdir)
            if edit_contract is not None:
                materialize_edit_card(
                    harness_dir=file_comm.dir,
                    instruction_delta=user_prompt,
                    edit_contract=edit_contract,
                    sprint_plan=file_comm.read_sprint_plan() or {},
                    verification_plan=file_comm.read_ui_verification_plan() or {},
                )
                materialize_edit_risk_tests(
                    workdir=workdir,
                    instruction_delta=user_prompt,
                )
                edit_freeze = freeze_preimplementation_validation(
                    workdir=workdir,
                    file_comm=file_comm,
                    instruction_delta=user_prompt,
                )
            CheckpointTransaction(
                file_comm=file_comm,
                prompt=user_prompt,
                costs={"planner": recovered_planner.cost_usd},
                phase_metrics=recovered_metrics,
            ).record_plan_completed(edit_freeze=edit_freeze)
            existing_state = file_comm.read_state()
            logger.info(
                "[bold blue]Planner[/] recovered a valid trace-proven planning bundle; "
                "no duplicate model call made."
            )
    if resume and existing_state:
        user_prompt = existing_state.get("prompt", user_prompt)
        _restore_costs(cost_tracker, existing_state.get("costs", {}))
        restore_resume_state(file_comm, existing_state)
        existing_state = reconcile_completed_evaluation(file_comm, existing_state)
        contract = read_edit_task_contract(workdir)
        resolved_task_mode = (
            "edit"
            if contract is not None or (workdir / "seed_manifest.json").is_file()
            else "generate"
        )
        if task_mode not in {"auto", resolved_task_mode}:
            raise ResumeError(
                f"resume task mode {task_mode!r} conflicts with persisted {resolved_task_mode!r} run"
            )
        if input_paths:
            if not task_inputs_match(workdir, input_paths):
                raise ResumeError("resume inputs differ from the persisted task input manifest")
        if target_routes:
            persisted_routes = list((contract or {}).get("requested_target_routes") or [])
            if target_routes != persisted_routes:
                raise ResumeError("resume target routes differ from the persisted Edit contract")
        if resolved_task_mode == "edit":
            atomic_plan_path = file_comm.dir / "atomic_edit_plan.json"
            plan_before = (
                atomic_plan_path.read_bytes() if atomic_plan_path.is_file() else b""
            )
            refresh_atomic_edit_plan(
                file_comm=file_comm,
                user_prompt=user_prompt,
                config=config,
            )
            resumed_plan_changed = (
                atomic_plan_path.is_file()
                and atomic_plan_path.read_bytes() != plan_before
            )
        phase_metrics = _copy_metrics(existing_state.get("phase_metrics"))
        skip_until_phase = existing_state.get("last_completed_phase")
        logger.info(f"[bold]Harness resuming[/] from '{skip_until_phase}'")
    else:
        if resume:
            logger.warning("[bold]Resume requested but no checkpoint found.[/]")
        file_comm.reset_run_artifacts()
        resolved_task_mode = resolve_task_mode(workdir, task_mode)
        if resolved_task_mode == "edit":
            edit_contract = prepare_edit_task_contract(
                workdir, requested_target_routes=target_routes, chain_metadata=chain_metadata
            )
            if atomic_plan is not None:
                write_atomic_edit_plan(
                    file_comm.dir, atomic_plan, instruction_delta=user_prompt
                )
            if hidden_oracle_checks:
                oracle_routes = list(edit_contract.get("requested_target_routes") or [])
                if not oracle_routes:
                    oracle_routes = sorted({
                        str(item.get("route") or "/")
                        for item in hidden_oracle_checks
                        if isinstance(item, dict)
                    })
                write_hidden_oracle_checks(
                    file_comm.dir,
                    hidden_oracle_checks,
                    target_routes=oracle_routes,
                )
            if prior_accepted_checks:
                stage_prior_accepted_tapes(file_comm.dir, prior_accepted_checks)
            keep_frontend = True
        elif target_routes:
            raise ValueError("--target-route is valid only for Edit tasks")
        elif atomic_plan is not None or hidden_oracle_checks or prior_accepted_checks or chain_metadata:
            raise ValueError("structured Edit plan/oracle inputs require task_mode=edit")
        else:
            _reset_generate_edit_frames(file_comm)
        stage_task_inputs(workdir, input_paths)
        file_comm.write_target_profile(detect_target_profile(user_prompt))
        if not keep_frontend:
            _reset_frontend_dir(workdir)
        phase_metrics = {}
        skip_until_phase = None
        existing_state = None
        logger.info(f"[bold]Harness started[/] — prompt: {user_prompt[:80]}...")

    logger.info(f"Workdir: {workdir}")

    if file_comm.read_target_profile() is None:
        file_comm.write_target_profile(detect_target_profile(user_prompt))

    sprint_state = SprintState.load(file_comm)
    ctx = HarnessContext(
        workdir=workdir,
        config=config,
        file_comm=file_comm,
        cost_tracker=cost_tracker,
        sprint_state=sprint_state,
        phase_metrics=phase_metrics,
        user_prompt=user_prompt,
    )

    if not _is_planner_checkpoint(skip_until_phase):
        await run_planner_phase(ctx)
        if plan_only:
            logger.info("[bold]--plan-only mode:[/] stopping after planner")
            _print_summary(cost_tracker, time.time() - start, 0, True)
            return
        if cost_tracker.is_over_budget():
            logger.warning("[bold red]Budget exceeded after planning. Stopping.[/]")
            return
        if _phase_budget_exhausted(ctx, "planner"):
            logger.warning(
                "[bold red]Planner phase budget exhausted after planning. Stopping.[/]"
            )
            return
    else:
        logger.info("[bold cyan]PHASE 1: PLAN[/] — [dim]skipped (checkpoint)[/]")

    requested_design_mode = (
        str(existing_state.get("requested_design_mode") or config.design_mode)
        if resume and existing_state
        else config.design_mode
    )
    if requested_design_mode == "image-first":
        ctx.config.design_mode = requested_design_mode
        if _phase_kind(skip_until_phase) not in {"design", "build", "evaluate"}:
            await run_design_phase(ctx)
        else:
            logger.info("[bold magenta]PHASE 2: DESIGN[/] — [dim]skipped (checkpoint)[/]")

    ctx.sprint_state = SprintState.load(file_comm)

    max_rounds = _round_limit_for_task(
        config,
        task_mode=resolved_task_mode,
        total_sprints=ctx.sprint_state.total_sprints,
    )

    start_round = _resolve_start_round(skip_until_phase, existing_state)
    if (
        resumed_plan_changed
        and existing_state
        and existing_state.get("last_verdict") == "failed_review"
    ):
        skip_until_phase = f"build_r{start_round}"
        logger.info(
            "[bold cyan]Edit contract normalization changed on resume; "
            "re-evaluating the existing candidate before another paid Repair.[/]"
        )
    if ctx.sprint_state.current_target > ctx.sprint_state.total_sprints > 0:
        logger.info("[bold green]All sprints already accepted.[/]")
        _print_summary(cost_tracker, time.time() - start, max(start_round - 1, 0), True)
        return
    if start_round > max_rounds:
        logger.info(f"[bold]All rounds completed (max_rounds={max_rounds}).[/]")
        _print_summary(cost_tracker, time.time() - start, max_rounds, False)
        return

    for round_num in range(start_round, max_rounds + 1):
        logger.info(f"[bold cyan]═" * 40)
        logger.info(f"[bold cyan]ROUND {round_num}/{max_rounds}")

        reserve = _next_round_cost_reserve(ctx.phase_metrics)
        if reserve and cost_tracker.remaining() < reserve:
            logger.warning(
                "[bold yellow]Budget reserve prevents an unevaluable new round. "
                f"Remaining ${cost_tracker.remaining():.2f}; observed minimum "
                f"generator+evaluator cost ${reserve:.2f}. Stopping.[/]"
            )
            break

        if _phase_budget_exhausted(ctx, "generator"):
            logger.warning(
                "[bold red]Generator phase budget exhausted before starting another build.[/]"
            )
            break

        if skip_until_phase != f"build_r{round_num}":
            await run_build_phase(ctx, round_num, resume_state=existing_state)
            if cost_tracker.is_over_budget():
                logger.warning("[bold red]Budget exceeded after build. Stopping.[/]")
                break
            if _phase_budget_exhausted(ctx, "generator"):
                logger.warning(
                    "[bold red]Generator phase budget exhausted after build. Stopping before evaluation.[/]"
                )
                break
        else:
            logger.info("[bold green]BUILD phase[/] — [dim]skipped (checkpoint)[/]")

        if skip_until_phase == f"evaluate_r{round_num}":
            logger.info("[bold yellow]EVALUATE phase[/] — [dim]skipped (checkpoint)[/]")
            verdict = _verdict_from_state(existing_state)
            if verdict is Verdict.completed:
                logger.info(f"[bold green]✓ Round {round_num} already completed the final sprint.[/]")
                _print_summary(cost_tracker, time.time() - start, round_num, True)
                return
            elif verdict is Verdict.accepted_review:
                logger.info(
                    f"[bold green]✓ Round {round_num} evaluation was already accepted.[/] "
                    "Continuing with the next sprint."
                )
            else:
                logger.info(
                    f"[bold red]✗ Round {round_num} previously failed review.[/] "
                    "Continuing with repair on the same sprint."
                )
            skip_until_phase = None
        else:
            if _phase_budget_exhausted(ctx, "evaluator"):
                logger.warning(
                    "[bold red]Evaluator phase budget exhausted before evaluation. Stopping.[/]"
                )
                break
            verdict = await run_evaluate_phase(ctx, round_num)
            if verdict is Verdict.completed:
                logger.info(f"[bold green]✓ Final sprint accepted in round {round_num}![/]")
                _print_summary(cost_tracker, time.time() - start, round_num, True)
                return
            if cost_tracker.is_over_budget():
                logger.warning("[bold red]Budget exceeded after evaluate. Stopping.[/]")
                break
            if _phase_budget_exhausted(ctx, "evaluator"):
                logger.warning(
                    "[bold red]Evaluator phase budget exhausted after evaluation. Stopping.[/]"
                )
                break
            if verdict is Verdict.accepted_review:
                logger.info(
                    f"[bold green]✓ Sprint accepted.[/] Advancing to sprint {ctx.sprint_state.current_target}."
                )
            else:
                logger.info(
                    "[bold red]✗ Sprint requires repair.[/] "
                    "The next round will continue on the same sprint."
                )

        if skip_until_phase == f"build_r{round_num}":
            skip_until_phase = None

    _print_summary(cost_tracker, time.time() - start, max_rounds, False)


def _restore_costs(tracker: CostTracker, costs: dict[str, float]) -> None:
    for name, cost in costs.items():
        tracker.add(name, cost)


def _copy_metrics(existing: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(existing, dict):
        return {}
    return {k: dict(v) for k, v in existing.items() if isinstance(v, dict)}


def _phase_budget_exhausted(ctx: HarnessContext, phase: str) -> bool:
    if phase == "planner":
        return ctx.cost_tracker.phase_budget_exceeded(
            ctx.config.planner_budget_usd, "planner"
        )
    if phase == "generator":
        return ctx.cost_tracker.phase_budget_exceeded(
            ctx.config.generator_budget_usd, "generator"
        )
    if phase == "evaluator":
        return ctx.cost_tracker.phase_budget_exceeded(
            ctx.config.evaluator_budget_usd, "evaluator", "visual_score"
        )
    raise ValueError(f"unknown phase budget: {phase}")


def _phase_kind(phase: str | None) -> str | None:
    if not phase:
        return None
    if phase == "plan":
        return "plan"
    if phase == "design":
        return "design"
    if phase.startswith("build_r"):
        return "build"
    if phase.startswith("evaluate_r"):
        return "evaluate"
    return phase


def _resolve_start_round(resume_phase: str | None, state: dict[str, Any] | None) -> int:
    if not resume_phase or not state:
        return 1
    if resume_phase.startswith("build_r"):
        return int(state["round_num"])
    if resume_phase.startswith("evaluate_r"):
        if state.get("last_verdict") == "completed":
            return int(state["round_num"])
        return int(state["round_num"]) + 1
    return 1


def _verdict_from_state(state: dict[str, Any] | None) -> Verdict:
    if not state:
        return Verdict.failed_review
    last = state.get("last_verdict")
    if last == "completed":
        return Verdict.completed
    if last == "accepted_review":
        return Verdict.accepted_review
    return Verdict.failed_review


def _print_summary(cost: CostTracker, elapsed: float, rounds: int, success: bool) -> None:
    status = "[bold green]SUCCESS[/]" if success else "[bold red]INCOMPLETE[/]"
    logger.info(f"\n[bold]{'═' * 40}[/]")
    logger.info(f"[bold]Harness {status}[/]")
    logger.info(f"Duration: {elapsed / 60:.1f} min")
    logger.info(f"Rounds: {rounds}")
    logger.info(cost.summary())


def _reset_frontend_dir(workdir: Path) -> None:
    frontend_dir = workdir / "frontend"
    if not frontend_dir.exists() or not frontend_dir.is_dir():
        return
    shutil.rmtree(frontend_dir)
    logger.info("[bold]Frontend cleared[/] — pass --keep-frontend to preserve it.")
