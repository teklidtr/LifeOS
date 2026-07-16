from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ConsequentialAction(str, Enum):
    SUBMIT = "submit"
    APPROVE = "approve"
    APPLY = "apply"


@dataclass(frozen=True, slots=True)
class ConsequentialAuthorizationRequest:
    action: ConsequentialAction
    proposal_id: str
    review_digest: str | None


@dataclass(frozen=True, slots=True)
class AuthorizedPrincipal:
    actor_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str):
            raise ValueError("actor_id must be a string")
        if not self.actor_id or not self.actor_id.strip():
            raise ValueError("actor_id must not be empty or whitespace-only")
        if self.actor_id != self.actor_id.strip():
            raise ValueError("actor_id must not have surrounding whitespace")


class ConsequentialAuthorizer(Protocol):
    def authorize(
        self,
        request: ConsequentialAuthorizationRequest,
        /,
    ) -> AuthorizedPrincipal:
        ...


class ConsequentialAuthorizationError(RuntimeError):
    pass


class AuthorizationDeniedError(ConsequentialAuthorizationError):
    pass


class AuthorizationUnavailableError(ConsequentialAuthorizationError):
    pass
