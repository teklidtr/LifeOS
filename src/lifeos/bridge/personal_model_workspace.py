"""Thin desktop bridge contract for the evidence-backed Personal Model workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast

from lifeos.bridge.protocol import ProtocolError, strict_object
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.registry_tools import refresh_registry
from lifeos.patterns.artifact import PatternArtifactService, parse_pattern
from lifeos.patterns.context import (
    PersonalPatternContextError,
    _runtime_scan_filter,
    _snapshot_registry,
)
from lifeos.patterns.contracts import (
    EvidenceRole,
    OriginKind,
    PatternConfidence,
    PatternError,
    PatternEvidence,
    PatternOrigin,
)
from lifeos.patterns.model import (
    PersonalModelDocument,
    PersonalModelError,
    PersonalModelItem,
    PersonalModelService,
    build_personal_model_document,
)
from lifeos.patterns.proposals import (
    ArchivePatternRequest,
    CreatePatternSeedRequest,
    MarkPatternNeedsReviewRequest,
    PatternProposalRequest,
    PatternProposalService,
    PromotePatternRequest,
    ResolvePatternReviewRequest,
    RevisePatternRequest,
)
from lifeos.registry import FileTrackingError, Registry, RegistryError, register_scan
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.scanner import ScannerError, scan_vault
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.vault_paths import iter_vault_markdown_paths

PersonalModelAction = Literal["track", "adopt", "revise", "contest", "archive"]


def _moment(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError("invalid_params", "now must be an ISO datetime.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("invalid_params", "now must be an ISO datetime.") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProtocolError("invalid_params", "now must include a timezone.")
    return result


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("invalid_params", f"{field} must be a non-empty string.")
    return value.strip()


def _optional_string(data: dict[str, Any], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("invalid_params", f"{field} must be a non-empty string when present.")
    return value.strip()


def _string(data: dict[str, Any], field: str, default: str = "") -> str:
    value = data.get(field, default)
    if not isinstance(value, str):
        raise ProtocolError("invalid_params", f"{field} must be a string.")
    return value


def _local_allow_path(vault_root: Path) -> Callable[[str], bool]:
    """Apply ordinary local retrieval policy before opening Personal Model sources."""
    try:
        policy = load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ProtocolError(
            "personal_model_blocked",
            "Could not load the retrieval policy for the Personal Model workspace.",
        ) from exc
    scope = RetrievalScope()

    def allowed(path: str) -> bool:
        try:
            return scope_decision(path, scope=scope, policy=policy, mode="local").allowed
        except RetrievalError:
            return False

    return allowed


def _authorize_path(
    allow_path: Callable[[str], bool],
    path: str,
    *,
    subject: str,
) -> None:
    if allow_path(path):
        return
    raise ProtocolError(
        "authorization_denied",
        f"{subject} is outside the Personal Model workspace's authorized local scope.",
        {"path": path},
    )


def _authorize_evidence(
    allow_path: Callable[[str], bool],
    evidence: tuple[PatternEvidence, ...],
) -> None:
    for reference in evidence:
        _authorize_path(
            allow_path,
            reference.path,
            subject="Pattern evidence",
        )


def _origin_path(origin: PatternOrigin) -> str | None:
    source_ref = origin.source_ref
    if source_ref and source_ref.endswith(".md"):
        return source_ref
    return None


def _authorize_origin(
    allow_path: Callable[[str], bool],
    origin: PatternOrigin,
) -> None:
    path = _origin_path(origin)
    if path is not None:
        _authorize_path(allow_path, path, subject="Pattern origin")


def _evidence(value: object) -> tuple[PatternEvidence, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProtocolError("invalid_params", "evidence must be a list.")
    result: list[PatternEvidence] = []
    for index, item in enumerate(value):
        data = strict_object(
            item,
            allowed={"path", "content_hash", "role", "source_id", "observation_id", "event_id"},
            required={"path", "content_hash", "role"},
        )
        try:
            result.append(
                PatternEvidence(
                    path=_required_string(data, "path"),
                    content_hash=_required_string(data, "content_hash"),
                    role=cast(EvidenceRole, _required_string(data, "role")),
                    source_id=_optional_string(data, "source_id"),
                    observation_id=_optional_string(data, "observation_id"),
                    event_id=_optional_string(data, "event_id"),
                )
            )
        except PatternError as exc:
            raise ProtocolError(
                exc.code,
                exc.message,
                {"evidence_index": index, **exc.data},
            ) from exc
    return tuple(result)


def _origin(value: object) -> PatternOrigin:
    if value is None:
        return PatternOrigin("manual")
    data = strict_object(value, allowed={"kind", "source_ref"}, required={"kind"})
    try:
        return PatternOrigin(
            cast(OriginKind, _required_string(data, "kind")),
            source_ref=_optional_string(data, "source_ref"),
        )
    except PatternError as exc:
        raise ProtocolError(exc.code, exc.message, exc.data) from exc


def _review_reasons(value: object, fallback: str) -> tuple[str, ...]:
    if value is None:
        return (fallback,)
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ProtocolError(
            "invalid_params",
            "review_reasons must be a non-empty list of non-empty strings.",
        )
    return tuple(dict.fromkeys(item.strip() for item in value))


def _related_paths(
    item: PersonalModelItem,
    allow_path: Callable[[str], bool],
) -> list[dict[str, str]]:
    related: dict[str, str] = {}

    def add(path: str, kind: str) -> None:
        if allow_path(path):
            related[path] = kind

    origin = _origin_path(item.origin)
    if origin is not None:
        if origin.startswith("reviews/"):
            add(origin, "review")
        elif origin.startswith("experiments/"):
            add(origin, "experiment")
    for evidence in item.evidence:
        if evidence.path.startswith("reviews/"):
            add(evidence.path, "review")
        elif evidence.path.startswith("experiments/"):
            add(evidence.path, "experiment")
    for diagnostic in item.evidence_diagnostics:
        path = diagnostic.current_path
        if not path:
            continue
        if path.startswith("reviews/"):
            add(path, "review")
        elif path.startswith("experiments/"):
            add(path, "experiment")
    return [{"path": path, "kind": related[path]} for path in sorted(related)]


def _workspace_item(
    item: PersonalModelItem,
    artifacts: PatternArtifactService,
    allow_path: Callable[[str], bool],
) -> dict[str, object]:
    artifact = artifacts.load(item.pattern_path)
    if artifact.content_hash != item.pattern_content_hash:
        raise ProtocolError(
            "stale_target",
            "The pattern changed while the Personal Model workspace was loading. "
            "Refresh and review it again.",
            {"path": item.pattern_path},
        )
    result = asdict(item)
    origin = asdict(item.origin)
    origin_path = _origin_path(item.origin)
    if origin_path is not None and not allow_path(origin_path):
        origin["source_ref"] = None
    result["origin"] = origin
    result["statement"] = artifact.metadata.statement
    result["related_paths"] = _related_paths(item, allow_path)
    result["evidence_changes"] = [
        {
            "role": diagnostic.reference.role,
            "reviewed_path": diagnostic.reference.path,
            "reviewed_content_hash": diagnostic.reference.content_hash,
            "state": diagnostic.state,
            "current_path": diagnostic.current_path,
            "current_content_hash": diagnostic.current_content_hash,
        }
        for diagnostic in item.evidence_diagnostics
        if diagnostic.state != "unchanged"
    ]
    return result


def _workspace_document(
    document: PersonalModelDocument,
    artifacts: PatternArtifactService,
    allow_path: Callable[[str], bool],
) -> dict[str, object]:
    return {
        "schema_version": document.schema_version,
        "source_hash": document.source_hash,
        "runtime_state": "ready",
        "groups": {
            "active": [
                _workspace_item(item, artifacts, allow_path) for item in document.active
            ],
            "needs_review": [
                _workspace_item(item, artifacts, allow_path)
                for item in document.needs_review
            ],
            "seeds": [
                _workspace_item(item, artifacts, allow_path) for item in document.seeds
            ],
            "archived": [
                _workspace_item(item, artifacts, allow_path) for item in document.archived
            ],
        },
        "diagnostics": [asdict(item) for item in document.diagnostics],
    }


class _ScopedPatternArtifactService(PatternArtifactService):
    """List only authorized pattern bytes for Track duplicate-identity checks."""

    def __init__(
        self,
        *,
        vault_root: Path,
        allow_path: Callable[[str], bool],
    ) -> None:
        super().__init__(vault_root=vault_root)
        self.allow_path = allow_path

    def list(self):  # type: ignore[no-untyped-def]
        def allowed_pattern_path(path: str) -> bool:
            candidate = path.rstrip("/")
            if candidate != "patterns" and not candidate.startswith("patterns/"):
                return False
            return self.allow_path(candidate)

        try:
            paths = iter_vault_markdown_paths(
                self.vault_root,
                path_filter=allowed_pattern_path,
            )
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return ()
            raise PatternError(exc.code, str(exc)) from exc

        artifacts = []
        by_id: dict[str, str] = {}
        for relative_path in paths:
            try:
                source = read_vault_markdown(self.vault_root, relative_path)
            except VaultAccessError as exc:
                raise PatternError(exc.code, str(exc), {"path": relative_path}) from exc
            artifact = parse_pattern(source.path, source.relative_path, source.content)
            if artifact is None:
                continue
            previous = by_id.get(artifact.metadata.pattern_id)
            if previous is not None:
                raise PatternError(
                    "duplicate_identity",
                    "Pattern identity must resolve to exactly one canonical artifact.",
                    {
                        "pattern_id": artifact.metadata.pattern_id,
                        "paths": [previous, artifact.path],
                    },
                )
            by_id[artifact.metadata.pattern_id] = artifact.path
            artifacts.append(artifact)
        return tuple(sorted(artifacts, key=lambda item: (item.metadata.pattern_id, item.path)))


def _current_document(
    *,
    vault_root: Path,
    runtime_dir: Path,
    allow_path: Callable[[str], bool],
    now: datetime | None,
) -> PersonalModelDocument:
    """Refresh evidence facts in a disposable registry snapshot, never persisted runtime."""
    try:
        with TemporaryDirectory(prefix="lifeos-personal-model-workspace-") as temporary:
            registry = _snapshot_registry(runtime_dir=runtime_dir, temporary=temporary)
            runtime_filter = _runtime_scan_filter(vault_root, runtime_dir)

            def scan_allow_path(path: str) -> bool:
                return runtime_filter(path) and allow_path(path)

            entries = scan_vault(vault_root, path_filter=scan_allow_path)
            register_scan(
                registry,
                vault_root,
                entries,
                identity_allow_path=allow_path,
            )
            return build_personal_model_document(
                vault_root=vault_root,
                registry=registry,
                allow_path=allow_path,
                now=now,
            )
    except (PersonalPatternContextError, FileTrackingError, RegistryError, ScannerError) as exc:
        raise PersonalModelError(
            f"Could not refresh current Personal Model evidence facts safely: {exc}"
        ) from exc


class PersonalModelWorkspaceBridge:
    """Expose only presentation/rebuild/proposal seams needed by the Obsidian workspace."""

    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id
        self.artifacts = PatternArtifactService(vault_root=vault_root)

    def dispatch(self, method: str, params: object) -> object:
        if method == "personal-model.workspace.get":
            data = strict_object(params, allowed={"now"})
            return self.load(now=_moment(data.get("now")))
        if method == "personal-model.rebuild":
            data = strict_object(params, allowed={"now"})
            return self.rebuild(now=_moment(data.get("now")))
        if method in {"personal-model.proposal.preview", "personal-model.proposal.create"}:
            allow_path = _local_allow_path(self.vault_root)
            request, expected_hash, now = self._proposal_request(
                params,
                allow_path=allow_path,
            )
            self._check_expected_target(
                request,
                expected_hash,
                allow_path=allow_path,
            )
            proposals = PatternProposalService(
                vault_root=self.vault_root,
                actor_id=self.actor_id,
            )
            proposals.artifacts = _ScopedPatternArtifactService(
                vault_root=self.vault_root,
                allow_path=allow_path,
            )
            try:
                if method.endswith("preview"):
                    preview, _, _ = proposals.preview(request, now=now)
                    return {"preview": preview.to_dict()}
                return proposals.publish(request, now=now)
            except PatternError as exc:
                raise ProtocolError(exc.code, exc.message, exc.data) from exc
        raise ProtocolError(
            "method_not_found",
            "Unknown Personal Model bridge method.",
            {"method": method},
        )

    def load(self, *, now: datetime | None = None) -> dict[str, object]:
        allow_path = _local_allow_path(self.vault_root)
        registry = Registry(self.runtime_dir / "registry.db")
        model = PersonalModelService(
            vault_root=self.vault_root,
            runtime_dir=self.runtime_dir,
            registry=registry,
            allow_path=allow_path,
        )
        try:
            if model.active_path() is None or registry.schema_version == 0:
                raise ProtocolError(
                    "personal_model_rebuild_required",
                    "The disposable Personal Model is missing. Rebuild it from canonical patterns.",
                    {"recovery": "rebuild"},
                )
            document = _current_document(
                vault_root=self.vault_root,
                runtime_dir=self.runtime_dir,
                allow_path=allow_path,
                now=now,
            )
            return _workspace_document(document, self.artifacts, allow_path)
        except ProtocolError:
            raise
        except RegistryError as exc:
            raise ProtocolError(
                "personal_model_rebuild_required",
                "The Personal Model registry state is unavailable. Rebuild derived state.",
                {"recovery": "rebuild"},
            ) from exc
        except PersonalModelError as exc:
            raise ProtocolError(
                "personal_model_recovery_required",
                "The Personal Model runtime generation is not safe to read.",
                {"recovery": "rebuild", "detail": str(exc)},
            ) from exc
        except PatternError as exc:
            raise ProtocolError(exc.code, exc.message, exc.data) from exc

    def rebuild(self, *, now: datetime | None = None) -> dict[str, object]:
        allow_path = _local_allow_path(self.vault_root)
        registry = Registry(self.runtime_dir / "registry.db")
        try:
            refresh_registry(
                vault_root=self.vault_root,
                registry=registry,
                identity_allow_path=allow_path,
            )
            model = PersonalModelService(
                vault_root=self.vault_root,
                runtime_dir=self.runtime_dir,
                registry=registry,
                allow_path=allow_path,
            )
            document = model.rebuild(now=now)
            return _workspace_document(document, self.artifacts, allow_path)
        except (RegistryError, ToolExecutionError, PersonalModelError) as exc:
            raise ProtocolError(
                "personal_model_rebuild_failed",
                "Could not rebuild the disposable Personal Model from canonical sources.",
                {"detail": str(exc)},
            ) from exc
        except PatternError as exc:
            raise ProtocolError(exc.code, exc.message, exc.data) from exc

    def _proposal_request(
        self,
        params: object,
        *,
        allow_path: Callable[[str], bool],
    ) -> tuple[PatternProposalRequest, str | None, datetime | None]:
        data = strict_object(
            params,
            allowed={
                "action",
                "target_path",
                "expected_target_hash",
                "pattern_id",
                "title",
                "description",
                "statement",
                "confidence",
                "origin",
                "evidence",
                "transition_reason",
                "review_reasons",
                "now",
            },
            required={"action", "target_path", "transition_reason"},
        )
        action = _required_string(data, "action")
        if action not in {"track", "adopt", "revise", "contest", "archive"}:
            raise ProtocolError(
                "invalid_params",
                "action is not supported by the Personal Model workspace.",
            )
        target_path = _required_string(data, "target_path")
        _authorize_path(allow_path, target_path, subject="Pattern target")
        reason = _required_string(data, "transition_reason")
        now = _moment(data.get("now"))
        expected_hash = _optional_string(data, "expected_target_hash")

        try:
            if action == "track":
                if expected_hash not in {None, "absent"}:
                    raise ProtocolError(
                        "invalid_params",
                        "Track expects an absent target rather than a content hash.",
                    )
                confidence = cast(PatternConfidence, _required_string(data, "confidence"))
                evidence = _evidence(data.get("evidence"))
                origin = _origin(data.get("origin"))
                _authorize_evidence(allow_path, evidence)
                _authorize_origin(allow_path, origin)
                request: PatternProposalRequest = CreatePatternSeedRequest(
                    target_path=target_path,
                    pattern_id=_required_string(data, "pattern_id"),
                    title=_required_string(data, "title"),
                    description=_string(data, "description"),
                    statement=_required_string(data, "statement"),
                    confidence=confidence,
                    origin=origin,
                    evidence=evidence,
                    transition_reason=reason,
                )
                return request, expected_hash, now

            if expected_hash is None:
                raise ProtocolError(
                    "invalid_params",
                    "Existing-pattern actions require expected_target_hash from the inspected "
                    "workspace item.",
                )
            current = self.artifacts.load(target_path)
            _authorize_origin(allow_path, current.metadata.origin)
            _authorize_evidence(allow_path, current.metadata.evidence)
            if action == "adopt":
                request = (
                    PromotePatternRequest(target_path=target_path, transition_reason=reason)
                    if current.metadata.status == "seed"
                    else ResolvePatternReviewRequest(
                        target_path=target_path,
                        transition_reason=reason,
                        target_status="active",
                    )
                )
            elif action == "revise":
                statement = _optional_string(data, "statement")
                confidence_value = _optional_string(data, "confidence")
                evidence_value = data.get("evidence")
                revised_evidence = (
                    None if evidence_value is None else _evidence(evidence_value)
                )
                if revised_evidence is not None:
                    _authorize_evidence(allow_path, revised_evidence)
                request = RevisePatternRequest(
                    target_path=target_path,
                    transition_reason=reason,
                    statement=statement,
                    evidence=revised_evidence,
                    confidence=(
                        None
                        if confidence_value is None
                        else cast(PatternConfidence, confidence_value)
                    ),
                )
            elif action == "contest":
                request = MarkPatternNeedsReviewRequest(
                    target_path=target_path,
                    transition_reason=reason,
                    review_reasons=_review_reasons(data.get("review_reasons"), reason),
                )
            else:
                request = ArchivePatternRequest(
                    target_path=target_path,
                    transition_reason=reason,
                )
            return request, expected_hash, now
        except PatternError as exc:
            raise ProtocolError(exc.code, exc.message, exc.data) from exc

    def _check_expected_target(
        self,
        request: PatternProposalRequest,
        expected_hash: str | None,
        *,
        allow_path: Callable[[str], bool],
    ) -> None:
        if isinstance(request, CreatePatternSeedRequest):
            return
        assert expected_hash is not None
        _authorize_path(allow_path, request.target_path, subject="Pattern target")
        try:
            artifact = self.artifacts.load(request.target_path)
        except PatternError as exc:
            raise ProtocolError(exc.code, exc.message, exc.data) from exc
        if artifact.content_hash != expected_hash:
            raise ProtocolError(
                "stale_target",
                "The pattern changed after it was inspected. Refresh before creating a proposal.",
                {
                    "path": request.target_path,
                    "expected_hash": expected_hash,
                    "current_hash": artifact.content_hash,
                },
            )
