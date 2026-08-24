from __future__ import annotations

from collections.abc import Iterable

from foundora.agents.schema import AgentSchemaError

CEO_AGENT_ID = "founder-ceo"
PLANNING_AGENT_ID = "chief-of-staff-planning"
EXECUTIVE_AGENT_IDS = frozenset({CEO_AGENT_ID, PLANNING_AGENT_ID})

_ALLOWED_DELEGATION_TARGETS = frozenset({"founder", PLANNING_AGENT_ID, "future-specialist"})
_ALLOWED_CANDIDATE_AGENTS = frozenset(
    {"founder", CEO_AGENT_ID, PLANNING_AGENT_ID, "future-specialist"}
)
_RISK_LEVELS = frozenset({"R0", "R1", "R2", "R3", "R4", "R5"})
_TASK_PRIORITIES = frozenset({"critical", "high", "normal", "low"})


def _object_list(output: dict[str, object], key: str) -> list[dict[str, object]]:
    value = output.get(key)
    if not isinstance(value, list) or not value:
        raise AgentSchemaError(f"$.{key} must contain at least one item")
    if not all(isinstance(item, dict) for item in value):
        raise AgentSchemaError(f"$.{key} must contain objects")
    return value


def _string_list(value: object, path: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AgentSchemaError(f"{path} must contain strings")
    if required and not value:
        raise AgentSchemaError(f"{path} must contain at least one item")
    return value


def _context_references(structured_input: dict[str, object]) -> frozenset[str]:
    context = structured_input.get("business_context")
    if not isinstance(context, dict):
        raise AgentSchemaError("Executive input is missing business context")
    sources = context.get("sources")
    if not isinstance(sources, list):
        raise AgentSchemaError("Executive business context sources are invalid")
    references: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise AgentSchemaError("Executive business context contains an invalid source")
        reference = source.get("source_reference")
        if not isinstance(reference, str) or not reference:
            raise AgentSchemaError("Executive business context source reference is invalid")
        references.add(reference)
    if not references:
        raise AgentSchemaError("Executive planning requires at least one included source")
    return frozenset(references)


def _current_task_references(structured_input: dict[str, object]) -> frozenset[str]:
    context = structured_input.get("business_context")
    if not isinstance(context, dict) or not isinstance(context.get("sources"), list):
        raise AgentSchemaError("Executive business context sources are invalid")
    return frozenset(
        reference
        for source in context["sources"]
        if isinstance(source, dict)
        and source.get("source_type") == "current_tasks"
        and isinstance((reference := source.get("source_reference")), str)
    )


def _validate_trace(
    structured_input: dict[str, object], output: dict[str, object]
) -> frozenset[str]:
    context_id = structured_input.get("context_id")
    if output.get("context_id") != context_id:
        raise AgentSchemaError("Executive output context_id does not match the run snapshot")
    return _context_references(structured_input)


def _validate_evidence(
    items: Iterable[dict[str, object]], references: frozenset[str], path: str
) -> None:
    for index, item in enumerate(items):
        evidence = _string_list(
            item.get("evidence_refs"), f"$.{path}[{index}].evidence_refs", required=True
        )
        unknown = sorted(set(evidence).difference(references))
        if unknown:
            raise AgentSchemaError(
                f"$.{path}[{index}].evidence_refs contains unknown sources: {', '.join(unknown)}"
            )


def _unique_item_ids(items: list[dict[str, object]], key: str, path: str) -> set[str]:
    identifiers: list[str] = []
    for index, item in enumerate(items):
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise AgentSchemaError(f"$.{path}[{index}].{key} is invalid")
        identifiers.append(value)
    if len(identifiers) != len(set(identifiers)):
        raise AgentSchemaError(f"$.{path} contains duplicate {key} values")
    return set(identifiers)


def _validate_ceo(structured_input: dict[str, object], output: dict[str, object]) -> None:
    references = _validate_trace(structured_input, output)
    priorities = _object_list(output, "priorities")
    _unique_item_ids(priorities, "priority_id", "priorities")
    _validate_evidence(priorities, references, "priorities")
    for index, priority in enumerate(priorities):
        target = priority.get("delegation_target")
        if target not in _ALLOWED_DELEGATION_TARGETS:
            raise AgentSchemaError(
                f"$.priorities[{index}].delegation_target is not an available advisory target"
            )
        risk_level = priority.get("risk_level")
        if risk_level not in _RISK_LEVELS:
            raise AgentSchemaError(f"$.priorities[{index}].risk_level is invalid")
        approval_required = priority.get("approval_required")
        if not isinstance(approval_required, bool):
            raise AgentSchemaError(f"$.priorities[{index}].approval_required must be a boolean")
        if risk_level in {"R3", "R4", "R5"} and not approval_required:
            raise AgentSchemaError(
                f"$.priorities[{index}] cannot waive approval for {risk_level} work"
            )
    if output.get("plan_status") != "proposed":
        raise AgentSchemaError("Executive plans must remain proposed")


def _has_dependency_cycle(dependencies: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        for dependency_id in dependencies[task_id]:
            if visit(dependency_id):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    return any(visit(task_id) for task_id in dependencies)


def _validate_planning(structured_input: dict[str, object], output: dict[str, object]) -> None:
    references = _validate_trace(structured_input, output)
    tasks = _object_list(output, "tasks")
    task_ids = _unique_item_ids(tasks, "task_id", "tasks")
    _validate_evidence(tasks, references, "tasks")
    dependencies: dict[str, list[str]] = {}
    for index, task in enumerate(tasks):
        priority = task.get("priority")
        if priority not in _TASK_PRIORITIES:
            raise AgentSchemaError(f"$.tasks[{index}].priority is invalid")
        candidate = task.get("candidate_agent")
        if candidate not in _ALLOWED_CANDIDATE_AGENTS:
            raise AgentSchemaError(
                f"$.tasks[{index}].candidate_agent is not an available advisory target"
            )
        depends_on = _string_list(task.get("depends_on"), f"$.tasks[{index}].depends_on")
        unknown = sorted(set(depends_on).difference(task_ids))
        if unknown:
            raise AgentSchemaError(
                f"$.tasks[{index}].depends_on contains unknown tasks: {', '.join(unknown)}"
            )
        task_id = task["task_id"]
        assert isinstance(task_id, str)
        if task_id in depends_on:
            raise AgentSchemaError(f"$.tasks[{index}] cannot depend on itself")
        dependencies[task_id] = depends_on
    if _has_dependency_cycle(dependencies):
        raise AgentSchemaError("$.tasks contains a dependency cycle")
    progress = output.get("progress_review")
    if not isinstance(progress, list) or not all(isinstance(item, dict) for item in progress):
        raise AgentSchemaError("$.progress_review must contain objects")
    _validate_evidence(progress, references, "progress_review")
    task_references = _current_task_references(structured_input)
    for index, item in enumerate(progress):
        if item.get("task_reference") not in task_references:
            raise AgentSchemaError(
                f"$.progress_review[{index}].task_reference is not a current task source"
            )
    if output.get("plan_status") != "proposed":
        raise AgentSchemaError("Planning output must remain proposed")


def validate_executive_output(
    agent_id: str,
    structured_input: dict[str, object],
    output: dict[str, object],
) -> None:
    if agent_id == CEO_AGENT_ID:
        _validate_ceo(structured_input, output)
    elif agent_id == PLANNING_AGENT_ID:
        _validate_planning(structured_input, output)


def executive_prompt_constraints(agent_id: str, structured_input: dict[str, object]) -> str:
    if agent_id not in EXECUTIVE_AGENT_IDS:
        return ""
    references = sorted(_context_references(structured_input))
    return (
        " This is advisory executive planning only. Return plan_status as proposed. "
        "Do not claim that a task, delegation, approval, tool call, spend, or external "
        "action occurred. Copy context_id exactly from the input. Evidence references "
        "must be exact source_reference values from this allowlist: "
        f"{references}. Treat unsupported statements as assumptions or limitations."
    )
