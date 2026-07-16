"""Provider-neutral optional experiment-design assistance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, Sequence

from lifeos.retrieval.contracts import CancellationToken, ProviderCapabilities, ProviderError

from .contracts import ExperimentProtocol
from .design import DesignWarning, evaluate_design


@dataclass(frozen=True, slots=True)
class AssistanceRequest:
    purpose: str
    protocol: ExperimentProtocol
    selected_sources: tuple[str, ...] = ()
    redactions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssistanceResult:
    state: str
    suggestions: tuple[str, ...]
    warnings: tuple[DesignWarning, ...]
    provider_disclosure: dict[str, object]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "suggestions": list(self.suggestions),
            "warnings": [item.to_dict() for item in self.warnings],
            "provider_disclosure": dict(self.provider_disclosure),
            "diagnostics": list(self.diagnostics),
        }


class ExperimentAssistanceProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def assist(
        self,
        request: AssistanceRequest,
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> Sequence[str]: ...


class DeterministicExperimentAssistance:
    def __init__(self, suggestions: Sequence[str] = ()) -> None:
        self._suggestions = tuple(suggestions)
        self._capabilities = ProviderCapabilities("generation", "deterministic-fixture", "experiment-design-v1", True, 1)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def assist(self, request: AssistanceRequest, *, timeout_seconds: float | None, cancellation: CancellationToken) -> Sequence[str]:
        del request, timeout_seconds
        cancellation.checkpoint()
        return self._suggestions


def assist_design(
    request: AssistanceRequest,
    *,
    provider: ExperimentAssistanceProvider | None,
    timeout_seconds: float | None = 30,
    cancellation: CancellationToken | None = None,
) -> AssistanceResult:
    warnings = evaluate_design(request.protocol)
    if provider is None:
        return AssistanceResult("no-model", (), warnings, {"configured": False, "sent_paths": []})
    token = cancellation or CancellationToken()
    disclosure = {
        "configured": True,
        "adapter_key": provider.capabilities.adapter_key,
        "model_key": provider.capabilities.model_key,
        "local_only": provider.capabilities.local_only,
        "sent_paths": list(request.selected_sources),
        "redactions": list(request.redactions),
    }
    try:
        suggestions = tuple(str(item).strip() for item in provider.assist(request, timeout_seconds=timeout_seconds, cancellation=token) if str(item).strip())
    except ProviderError as exc:
        state = "timeout" if exc.code == "timeout" else "provider-unavailable"
        return AssistanceResult(state, (), warnings, disclosure, (str(exc),))
    except (TypeError, ValueError) as exc:
        return AssistanceResult("malformed-output", (), warnings, disclosure, (str(exc),))
    if any(len(item) > 2000 for item in suggestions):
        return AssistanceResult("malformed-output", (), warnings, disclosure, ("Provider suggestion exceeded the bounded output size.",))
    return AssistanceResult("ready", suggestions, warnings, disclosure)
