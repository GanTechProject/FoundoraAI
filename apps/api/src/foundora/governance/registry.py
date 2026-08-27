from __future__ import annotations

from dataclasses import dataclass

RISK_CLASSES = ("R0", "R1", "R2", "R3", "R4", "R5")
RISK_RANK = {value: index for index, value in enumerate(RISK_CLASSES)}


class GovernanceClassificationError(Exception):
    pass


@dataclass(frozen=True)
class ActionDescriptor:
    action_type: str
    display_name: str
    risk_class: str
    description: str


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    display_name: str
    risk_class: str
    internal: bool


ACTION_CATALOG = {
    item.action_type: item
    for item in (
        ActionDescriptor(
            "internal.analysis", "Internal analysis", "R0", "Read-only internal analysis."
        ),
        ActionDescriptor(
            "internal.content.create",
            "Internal content creation",
            "R1",
            "Creates an internal draft without external publication.",
        ),
        ActionDescriptor(
            "internal.code.execute",
            "Isolated code execution",
            "R2",
            "Executes approved generated code in the isolated sandbox runtime.",
        ),
        ActionDescriptor(
            "external.reversible",
            "Reversible external action",
            "R2",
            "A reversible external change such as a preview.",
        ),
        ActionDescriptor(
            "external.communication",
            "External communication",
            "R3",
            "Sends a message outside Foundora.",
        ),
        ActionDescriptor(
            "external.publication",
            "Public publication",
            "R3",
            "Publishes content to a public audience.",
        ),
        ActionDescriptor(
            "financial.spend",
            "Financial spend",
            "R4",
            "Commits money or changes a paid resource.",
        ),
        ActionDescriptor(
            "destructive.delete",
            "Destructive deletion",
            "R4",
            "Deletes durable business or customer data.",
        ),
        ActionDescriptor(
            "privileged.configuration",
            "Privileged configuration",
            "R4",
            "Changes credentials, billing, security, or production configuration.",
        ),
        ActionDescriptor(
            "security.bypass",
            "Security bypass",
            "R5",
            "Attempts to bypass a security or governance control.",
        ),
        ActionDescriptor(
            "workflow.checkpoint",
            "Workflow owner checkpoint",
            "R0",
            "A workflow-defined manual owner checkpoint.",
        ),
    )
}

TOOL_CATALOG = {
    item.tool_id: item
    for item in (
        ToolDescriptor("foundora.internal.echo", "Internal echo", "R0", True),
        ToolDescriptor("foundora.internal.fail", "Internal deterministic failure", "R0", True),
        ToolDescriptor("foundora.internal.discard", "Internal discard", "R0", True),
        ToolDescriptor("foundora.repository.website", "Controlled website repository", "R1", True),
        ToolDescriptor("foundora.filesystem.website", "Controlled website filesystem", "R1", True),
        ToolDescriptor(
            "foundora.dependencies.website", "Reviewed website dependencies", "R1", True
        ),
        ToolDescriptor("foundora.checks.website", "Website build checks", "R1", True),
        ToolDescriptor("foundora.sandbox.website", "Isolated website sandbox", "R2", True),
    )
}


def classify_action(
    action_type: str,
    *,
    tool_id: str | None,
    requested_spend_microusd: int,
    minimum_risk_class: str | None = None,
) -> str:
    descriptor = ACTION_CATALOG.get(action_type)
    if descriptor is None:
        raise GovernanceClassificationError("Action type is not in the code-reviewed catalog")
    risks = [descriptor.risk_class]
    if tool_id is not None:
        tool = TOOL_CATALOG.get(tool_id)
        if tool is None:
            raise GovernanceClassificationError("Tool is not in the code-reviewed catalog")
        risks.append(tool.risk_class)
    if requested_spend_microusd > 0:
        risks.append("R4")
    if minimum_risk_class is not None:
        if minimum_risk_class not in RISK_RANK:
            raise GovernanceClassificationError("Minimum risk class is invalid")
        risks.append(minimum_risk_class)
    return max(risks, key=RISK_RANK.__getitem__)
