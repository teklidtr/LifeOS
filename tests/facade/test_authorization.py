import pytest
from lifeos.facade.authorization import AuthorizedPrincipal, ConsequentialAuthorizer
import dataclasses
import inspect


def test_authorized_principal_is_frozen_and_slotted() -> None:
    assert getattr(AuthorizedPrincipal, "__slots__", None) is not None, "Must use slots"
    assert getattr(AuthorizedPrincipal, "__dataclass_params__").frozen is True, "Must be frozen"


def test_authorized_principal_rejects_non_string_actor() -> None:
    with pytest.raises(ValueError, match="actor_id must be a string"):
        AuthorizedPrincipal(actor_id=123)  # type: ignore


def test_authorized_principal_rejects_empty_actor() -> None:
    with pytest.raises(ValueError, match="actor_id must not be empty or whitespace"):
        AuthorizedPrincipal(actor_id="")
    with pytest.raises(ValueError, match="actor_id must not be empty or whitespace"):
        AuthorizedPrincipal(actor_id="   ")


def test_authorized_principal_rejects_surrounding_whitespace() -> None:
    with pytest.raises(ValueError, match="actor_id must not have surrounding whitespace"):
        AuthorizedPrincipal(actor_id=" user ")


def test_authorizer_is_required() -> None:
    from lifeos.facade.consequential_tools import (
        submit_proposal_tool,
        approve_proposal_tool,
        apply_proposal_tool,
    )

    sig_submit = inspect.signature(submit_proposal_tool)
    assert "authorizer" in sig_submit.parameters
    assert sig_submit.parameters["authorizer"].annotation is ConsequentialAuthorizer

    sig_approve = inspect.signature(approve_proposal_tool)
    assert "authorizer" in sig_approve.parameters
    assert sig_approve.parameters["authorizer"].annotation is ConsequentialAuthorizer

    sig_apply = inspect.signature(apply_proposal_tool)
    assert "authorizer" in sig_apply.parameters
    assert sig_apply.parameters["authorizer"].annotation is ConsequentialAuthorizer


def test_agent_request_models_contain_only_proposal_id() -> None:
    from lifeos.facade.consequential_tools import (
        SubmitProposalRequest,
        ApproveProposalRequest,
        ApplyProposalRequest,
    )

    for model in (SubmitProposalRequest, ApproveProposalRequest, ApplyProposalRequest):
        fields = dataclasses.fields(model)
        assert len(fields) == 1
        assert fields[0].name == "proposal_id"
