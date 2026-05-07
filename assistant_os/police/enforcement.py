from .gate_models import PoliceDecision, PoliceGateRequest


def check(request: PoliceGateRequest) -> PoliceDecision:
    raise NotImplementedError(
        "Token-bound Police gate is not implemented until S-POLICE-CORE-03"
    )
