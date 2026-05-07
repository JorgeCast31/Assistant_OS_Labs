from .models import (
    AgentPermission,
    PoliceCheckRequest,
    PoliceEvaluation,
    PoliceEvaluationType,
    PoliceViolation,
    RiskLevel,
)


class PoliceEnforcer:
    """Declarative permission evaluation for Police Core v0."""

    def evaluate(
        self,
        request: PoliceCheckRequest,
        agent_permission: AgentPermission,
    ) -> PoliceEvaluation:
        violations: list[PoliceViolation] = []
        denied_tools: list[str] = []
        denied_environments: list[str] = []
        risk_level = _risk_level_from_signals(request.risk_signals)

        if request.requested_tool and request.requested_tool not in agent_permission.allowed_tools:
            denied_tools.append(request.requested_tool)
            violations.append(
                PoliceViolation(
                    code="TOOL_NOT_PERMITTED",
                    message=f"Tool is outside the agent permission set: {request.requested_tool}",
                    field="requested_tool",
                    severity=RiskLevel.HIGH,
                )
            )

        if (
            request.requested_environment
            and request.requested_environment not in agent_permission.allowed_environments
        ):
            denied_environments.append(request.requested_environment)
            violations.append(
                PoliceViolation(
                    code="ENVIRONMENT_NOT_PERMITTED",
                    message=(
                        "Environment is outside the agent permission set: "
                        f"{request.requested_environment}"
                    ),
                    field="requested_environment",
                    severity=RiskLevel.HIGH,
                )
            )

        missing_capabilities = [
            capability
            for capability in request.requested_capabilities
            if capability not in agent_permission.capability_scope
        ]
        if missing_capabilities:
            violations.append(
                PoliceViolation(
                    code="CAPABILITY_NOT_PERMITTED",
                    message="Requested capabilities are outside the agent scope.",
                    field="requested_capabilities",
                    severity=RiskLevel.HIGH,
                )
            )

        if risk_level is RiskLevel.CRITICAL:
            violations.append(
                PoliceViolation(
                    code="CRITICAL_RISK_SIGNAL",
                    message="Critical risk signal present.",
                    field="risk_signals",
                    severity=RiskLevel.CRITICAL,
                )
            )

        if violations:
            blocked = "; ".join(violation.message for violation in violations)
            return PoliceEvaluation(
                request_id=request.request_id,
                outcome=PoliceEvaluationType.DENY,
                reason="Request denied by Police declarative enforcement check.",
                why_blocked=blocked,
                violations=violations,
                allowed_tools=list(agent_permission.allowed_tools),
                denied_tools=denied_tools,
                allowed_environments=list(agent_permission.allowed_environments),
                denied_environments=denied_environments,
                capability_scope=list(agent_permission.capability_scope),
                risk_level=risk_level,
            )

        if agent_permission.requires_review:
            return PoliceEvaluation(
                request_id=request.request_id,
                outcome=PoliceEvaluationType.REQUIRES_CONFIRMATION,
                reason="Request requires review by Police declarative enforcement check.",
                required_confirmation_reason="Agent permission requires review.",
                allowed_tools=list(agent_permission.allowed_tools),
                allowed_environments=list(agent_permission.allowed_environments),
                capability_scope=list(agent_permission.capability_scope),
                risk_level=risk_level,
            )

        return PoliceEvaluation(
            request_id=request.request_id,
            outcome=PoliceEvaluationType.ALLOW,
            reason="Request allowed by Police declarative enforcement check.",
            allowed_tools=list(agent_permission.allowed_tools),
            allowed_environments=list(agent_permission.allowed_environments),
            capability_scope=list(agent_permission.capability_scope),
            risk_level=risk_level,
        )


def _risk_level_from_signals(risk_signals: list[str]) -> RiskLevel:
    normalized = {signal.strip().lower() for signal in risk_signals}
    if "critical" in normalized:
        return RiskLevel.CRITICAL
    if "high" in normalized:
        return RiskLevel.HIGH
    if "medium" in normalized:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
