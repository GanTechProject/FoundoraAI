from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

STEP_TYPES = frozenset({"tool", "agent", "approval", "wait"})
INTERNAL_TOOLS = frozenset(
    {"foundora.internal.echo", "foundora.internal.fail", "foundora.internal.discard"}
)


class WorkflowDefinitionError(Exception):
    pass


@dataclass(frozen=True)
class StepDefinition:
    key: str
    step_type: str
    depends_on: tuple[str, ...]
    max_retries: int
    config: dict[str, object]


def parse_definition(definition: dict[str, object]) -> list[StepDefinition]:
    raw_steps = definition.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowDefinitionError("Workflow definition requires at least one step")
    if len(raw_steps) > 100:
        raise WorkflowDefinitionError("Workflow definition exceeds 100 steps")
    steps: list[StepDefinition] = []
    keys: set[str] = set()
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise WorkflowDefinitionError("Every workflow step must be an object")
        item = cast(dict[str, object], raw)
        key = item.get("key")
        step_type = item.get("type")
        dependencies = item.get("depends_on", [])
        retries = item.get("max_retries", 0)
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 80
            or not all(character.isalnum() or character in "_-" for character in key)
        ):
            raise WorkflowDefinitionError("Workflow step key is invalid")
        if key in keys:
            raise WorkflowDefinitionError(f"Workflow step key {key} is duplicated")
        if step_type not in STEP_TYPES:
            raise WorkflowDefinitionError(f"Workflow step {key} has an unsupported type")
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) for value in dependencies
        ):
            raise WorkflowDefinitionError(f"Workflow step {key} dependencies are invalid")
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0 or retries > 10:
            raise WorkflowDefinitionError(f"Workflow step {key} retry budget is invalid")
        if step_type == "tool" and item.get("tool") not in INTERNAL_TOOLS:
            raise WorkflowDefinitionError(
                f"Workflow step {key} requests a tool outside the Phase 10 R0 allowlist"
            )
        if step_type == "agent":
            if not isinstance(item.get("agent_id"), str):
                raise WorkflowDefinitionError(f"Workflow agent step {key} requires agent_id")
            try:
                uuid.UUID(str(item.get("agent_version_id")))
            except (TypeError, ValueError) as error:
                raise WorkflowDefinitionError(
                    f"Workflow agent step {key} requires an immutable agent_version_id"
                ) from error
        condition = item.get("condition")
        if condition is not None:
            if not isinstance(condition, dict):
                raise WorkflowDefinitionError(f"Workflow step {key} condition is invalid")
            source = condition.get("source")
            path = condition.get("path")
            if source not in {"input", "steps"} or not isinstance(path, str) or not path:
                raise WorkflowDefinitionError(f"Workflow step {key} condition is invalid")
        keys.add(key)
        steps.append(
            StepDefinition(
                key=key,
                step_type=step_type,
                depends_on=tuple(cast(list[str], dependencies)),
                max_retries=retries,
                config=item,
            )
        )
    by_key = {step.key: step for step in steps}
    for step in steps:
        if step.key in step.depends_on or any(key not in by_key for key in step.depends_on):
            raise WorkflowDefinitionError(f"Workflow step {step.key} has an invalid dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise WorkflowDefinitionError("Workflow step dependencies contain a cycle")
        if key in visited:
            return
        visiting.add(key)
        for dependency in by_key[key].depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)
    return steps


def condition_matches(
    condition: object,
    structured_input: dict[str, object],
    step_outputs: dict[str, dict[str, object] | None],
) -> bool:
    if condition is None:
        return True
    if not isinstance(condition, dict):
        raise WorkflowDefinitionError("Workflow condition is invalid")
    source = structured_input if condition.get("source") == "input" else step_outputs
    path = condition.get("path")
    if not isinstance(path, str):
        raise WorkflowDefinitionError("Workflow condition path is invalid")
    value: object = source
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            value = None
            break
        value = value[component]
    return value == condition.get("equals")


def execute_internal_tool(tool: object, payload: object) -> dict[str, object]:
    if tool == "foundora.internal.fail":
        raise RuntimeError("The deterministic internal failure tool was requested")
    if tool == "foundora.internal.discard":
        return {"discarded": True}
    if tool != "foundora.internal.echo":
        raise WorkflowDefinitionError("Workflow tool is not authorized")
    if not isinstance(payload, dict):
        raise WorkflowDefinitionError("Internal tool input must be an object")
    return dict(payload)
