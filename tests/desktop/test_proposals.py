from pathlib import Path

import pytest

from lifeos.desktop import DesktopProposalService
from lifeos.facade.authorization import AuthorizationDeniedError, ConsequentialAction, ConsequentialAuthorizationRequest


def test_one_use_confirmation_is_bound_to_exact_action(tmp_path: Path) -> None:
    service=DesktopProposalService(vault_root=tmp_path,actor_id="me")
    token=service.authorizer.issue(action=ConsequentialAction.SUBMIT,proposal_id="p",review_digest=None)
    service.authorizer.activate(token)
    principal=service.authorizer.authorize(ConsequentialAuthorizationRequest(ConsequentialAction.SUBMIT,"p",None))
    assert principal.actor_id=="me"
    with pytest.raises(AuthorizationDeniedError):
        service.authorizer.authorize(ConsequentialAuthorizationRequest(ConsequentialAction.SUBMIT,"p",None))


def test_confirmation_cannot_be_reused_for_other_proposal(tmp_path: Path) -> None:
    service=DesktopProposalService(vault_root=tmp_path,actor_id="me")
    token=service.authorizer.issue(action=ConsequentialAction.APPLY,proposal_id="p",review_digest="d")
    service.authorizer.activate(token)
    with pytest.raises(AuthorizationDeniedError):
        service.authorizer.authorize(ConsequentialAuthorizationRequest(ConsequentialAction.APPLY,"other","d"))
