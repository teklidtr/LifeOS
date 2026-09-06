import hashlib
import json
import sys
import pytest
from pathlib import Path

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from lifeos.config import LifeOSConfig
from lifeos.registry import Registry
from lifeos.scanner import VaultFile
from lifeos.registry.file_tracking import register_scan
from lifeos.proposals.loader import load_proposal_directory
from lifeos.status import ProposalStatus


@pytest.fixture
def mcp_server_helper_path() -> Path:
    return Path(__file__).parent / "_mcp_lifecycle_server.py"


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "proposals").mkdir()
    (root / "wiki").mkdir()
    (root / "system").mkdir()
    (root / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )
    return root


@pytest.fixture
def config_path(tmp_path: Path, vault_root: Path) -> Path:
    path = tmp_path / "lifeos.yml"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    path.write_text(f"vault_root: '{vault_root}'\nruntime_dir: '{runtime_dir}'\n")
    return path


@pytest.fixture
def config(config_path: Path) -> LifeOSConfig:
    from lifeos.config import load_config

    return load_config(config_path)


@pytest.fixture
def registry(config: LifeOSConfig) -> Registry:
    reg = Registry(config.runtime_dir / "registry.db")
    reg.initialize()
    return reg


@pytest.fixture
def setup_source(registry: Registry, vault_root: Path) -> None:
    source_path = vault_root / "sources" / "test.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"Canonical candidate content.\n")

    vf = VaultFile(
        path=Path("sources/test.md"),
        file_type="text/markdown",
        size_bytes=len(b"Canonical candidate content.\n"),
    )
    register_scan(registry, vault_root, [vf])


@pytest.mark.anyio
async def test_mcp_ingestion_lifecycle_applies_reviewed_proposal_end_to_end(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth.jsonl"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Step 1: Create
            create_result = await session.call_tool(
                "ingestion_create_wiki_proposal",
                arguments={
                    "source_path": "sources/test.md",
                    "target_path": "wiki/target.md",
                    "title": "Test Title",
                    "body": "Canonical candidate content.\n",
                },
            )
            assert not create_result.isError
            create_data = json.loads(create_result.content[0].text)
            assert create_data["status"] == "draft"
            proposal_id = create_data["proposal_id"]

            # Target should be absent
            target_path = vault_root / "wiki" / "target.md"
            assert not target_path.exists()

            # Step 2: Submit
            submit_result = await session.call_tool(
                "proposal_submit", arguments={"proposal_id": proposal_id}
            )
            assert not submit_result.isError
            submit_data = json.loads(submit_result.content[0].text)
            assert submit_data["status"] == "pending"
            submit_digest = submit_data["review_digest"]
            assert submit_digest is not None

            assert not target_path.exists()

            # Step 3: Approve
            approve_result = await session.call_tool(
                "proposal_approve", arguments={"proposal_id": proposal_id}
            )
            assert not approve_result.isError
            approve_data = json.loads(approve_result.content[0].text)
            assert approve_data["status"] == "approved"
            assert approve_data["review_digest"] == submit_digest

            assert not target_path.exists()

            # Step 4: Apply
            apply_result = await session.call_tool(
                "proposal_apply", arguments={"proposal_id": proposal_id}
            )
            assert not apply_result.isError
            apply_data = json.loads(apply_result.content[0].text)
            assert apply_data["status"] == "applied"
            assert apply_data["changed_paths"] == ["wiki/target.md"]

            assert target_path.exists()

    # Check authorization log
    auth_records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(auth_records) == 3

    assert auth_records[0]["action"] == "submit"
    assert auth_records[0]["proposal_id"] == proposal_id
    assert auth_records[0]["review_digest"] is None

    assert auth_records[1]["action"] == "approve"
    assert auth_records[1]["proposal_id"] == proposal_id
    assert auth_records[1]["review_digest"] == submit_digest

    assert auth_records[2]["action"] == "apply"
    assert auth_records[2]["proposal_id"] == proposal_id
    assert auth_records[2]["review_digest"] == submit_digest

    # Check Canonical Persisted State
    proposal_dir = vault_root / "proposals" / proposal_id
    proposal_load = load_proposal_directory(proposal_dir, proposals_root=vault_root / "proposals")
    assert proposal_load.proposal.metadata.status == ProposalStatus.APPLIED
    assert proposal_load.proposal.metadata.submitted_by == "integration-human"
    assert proposal_load.proposal.metadata.approved_by == "integration-human"
    assert proposal_load.proposal.metadata.applied_by == "integration-human"

    assert (proposal_dir / "proposal.md").exists()
    assert (proposal_dir / "patches.json").exists()

    assert b"Canonical candidate content.\n" in target_path.read_bytes()

    source_path = vault_root / "sources" / "test.md"
    assert source_path.read_bytes() == b"Canonical candidate content.\n"


@pytest.mark.anyio
async def test_mcp_ingestion_updates_one_existing_wiki_section_end_to_end(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth-update.jsonl"
    target_path = vault_root / "wiki" / "first-aid.md"
    original = (
        "---\nid: first-aid\ntitle: First Aid\n---\n\n"
        "# First Aid\n\n"
        "## Equipment notes\n\nOld incomplete list.\n\n"
        "## Safety\n\nKeep this section unchanged.\n"
    )
    target_path.write_text(original)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            update_result = await session.call_tool(
                "ingestion_update_wiki_section_proposal",
                arguments={
                    "source_path": "sources/test.md",
                    "target_path": "wiki/first-aid.md",
                    "heading": "Equipment notes",
                    "body": "Verified complete list with reasons.",
                },
            )
            assert not update_result.isError
            update_data = json.loads(update_result.content[0].text)
            assert update_data["status"] == "draft"
            assert update_data["heading"] == "Equipment notes"
            proposal_id = update_data["proposal_id"]
            assert target_path.read_text() == original

            submit = await session.call_tool("proposal_submit", {"proposal_id": proposal_id})
            assert not submit.isError
            approve = await session.call_tool("proposal_approve", {"proposal_id": proposal_id})
            assert not approve.isError
            apply = await session.call_tool("proposal_apply", {"proposal_id": proposal_id})
            assert not apply.isError

    assert target_path.read_text() == original.replace(
        "Old incomplete list.", "Verified complete list with reasons."
    )
    source_path = vault_root / "sources" / "test.md"
    assert source_path.read_bytes() == b"Canonical candidate content.\n"


@pytest.mark.anyio
async def test_mcp_ingestion_updates_generated_owned_wiki_section_end_to_end(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth-generated-update.jsonl"
    target_path = vault_root / "wiki" / "generated.md"
    original = (
        "# Generated\n\n"
        "## Equipment notes\n\nOld incomplete list.\n\n"
        "## Safety\n\nKeep this section unchanged.\n"
    )
    target_path.write_text(original)
    ownership = {
        "schema_version": 1,
        "owned_files": {
            "wiki/generated.md": {
                "generator_id": "lifeos.facade.external_agent",
                "generator_version": "1",
                "content_hash": hashlib.sha256(original.encode()).hexdigest(),
                "created_at": "2026-08-22T10:00:00Z",
                "updated_at": "2026-08-22T10:00:00Z",
            }
        },
    }
    (vault_root / "system" / "generated-ownership.json").write_text(json.dumps(ownership))

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            update_result = await session.call_tool(
                "ingestion_update_wiki_section_proposal",
                arguments={
                    "source_path": "sources/test.md",
                    "target_path": "wiki/generated.md",
                    "heading": "Equipment notes",
                    "body": "Verified complete list with reasons.",
                },
            )
            assert not update_result.isError
            proposal_id = json.loads(update_result.content[0].text)["proposal_id"]
            loaded = load_proposal_directory(
                vault_root / "proposals" / proposal_id,
                proposals_root=vault_root / "proposals",
            ).proposal
            assert loaded is not None
            assert loaded.patch_document.operations[0].op == "replace_generated_file"

            assert not (
                await session.call_tool("proposal_submit", {"proposal_id": proposal_id})
            ).isError
            assert not (
                await session.call_tool("proposal_approve", {"proposal_id": proposal_id})
            ).isError
            assert not (
                await session.call_tool("proposal_apply", {"proposal_id": proposal_id})
            ).isError

    assert target_path.read_text() == original.replace(
        "Old incomplete list.", "Verified complete list with reasons."
    )
    manifest = json.loads((vault_root / "system" / "generated-ownership.json").read_text())
    assert manifest["owned_files"]["wiki/generated.md"]["content_hash"] == (
        hashlib.sha256(target_path.read_bytes()).hexdigest()
    )


@pytest.mark.anyio
async def test_mcp_compound_ingestion_applies_two_operations_atomically(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth-compound.jsonl"
    update_target = vault_root / "wiki" / "first-aid.md"
    original = (
        "# First Aid\n\n"
        "## Equipment notes\n\nOld incomplete list.\n\n"
        "## Safety\n\nKeep this section unchanged.\n"
    )
    update_target.write_text(original)
    create_target = vault_root / "wiki" / "equipment.md"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            compound = await session.call_tool(
                "ingestion_create_wiki_and_update_section_proposal",
                arguments={
                    "source_path": "sources/test.md",
                    "create_target_path": "wiki/equipment.md",
                    "create_title": "Equipment",
                    "create_body": "Verified detailed equipment list.\n",
                    "update_target_path": "wiki/first-aid.md",
                    "update_heading": "Equipment notes",
                    "update_body": "See [[equipment]] for the verified detailed list.",
                },
            )
            assert not compound.isError
            compound_data = json.loads(compound.content[0].text)
            proposal_id = compound_data["proposal_id"]
            assert compound_data["status"] == "draft"
            assert not create_target.exists()
            assert update_target.read_text() == original

            submit = await session.call_tool("proposal_submit", {"proposal_id": proposal_id})
            assert not submit.isError
            approve = await session.call_tool("proposal_approve", {"proposal_id": proposal_id})
            assert not approve.isError
            apply = await session.call_tool("proposal_apply", {"proposal_id": proposal_id})
            assert not apply.isError
            apply_data = json.loads(apply.content[0].text)
            assert apply_data["status"] == "applied"
            assert set(apply_data["changed_paths"]) == {
                "wiki/equipment.md",
                "wiki/first-aid.md",
            }

    assert create_target.exists()
    assert "Verified detailed equipment list." in create_target.read_text()
    assert update_target.read_text() == original.replace(
        "Old incomplete list.",
        "See [[equipment]] for the verified detailed list.",
    )
    source_path = vault_root / "sources" / "test.md"
    assert source_path.read_bytes() == b"Canonical candidate content.\n"

    loaded = load_proposal_directory(
        vault_root / "proposals" / proposal_id,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    assert [operation.op for operation in loaded.patch_document.operations] == [
        "create_generated_file",
        "patch_human_file",
    ]


@pytest.mark.anyio
async def test_mcp_approval_denial_leaves_proposal_pending(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth.jsonl"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
            "--deny-action",
            "approve",
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            create_res = await session.call_tool(
                "ingestion_create_wiki_proposal",
                {
                    "source_path": "sources/test.md",
                    "target_path": "wiki/target.md",
                    "title": "Test Title",
                    "body": "Canonical candidate content.\n",
                },
            )
            proposal_id = json.loads(create_res.content[0].text)["proposal_id"]

            await session.call_tool("proposal_submit", {"proposal_id": proposal_id})

            approve_res = await session.call_tool("proposal_approve", {"proposal_id": proposal_id})
            assert approve_res.isError
            assert "Consequential operation was not authorized" in approve_res.content[0].text
            assert "Traceback" not in approve_res.content[0].text

            target_path = vault_root / "wiki" / "target.md"
            assert not target_path.exists()

            proposal_dir = vault_root / "proposals" / proposal_id
            proposal_load = load_proposal_directory(
                proposal_dir, proposals_root=vault_root / "proposals"
            )
            assert proposal_load.proposal.metadata.status == ProposalStatus.PENDING

            auth_records = [
                json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
            ]
            assert len(auth_records) == 2
            assert auth_records[1]["action"] == "approve"


@pytest.mark.anyio
async def test_mcp_application_denial_leaves_proposal_approved(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth.jsonl"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
            "--deny-action",
            "apply",
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            create_res = await session.call_tool(
                "ingestion_create_wiki_proposal",
                {
                    "source_path": "sources/test.md",
                    "target_path": "wiki/target.md",
                    "title": "Test Title",
                    "body": "Canonical candidate content.\n",
                },
            )
            proposal_id = json.loads(create_res.content[0].text)["proposal_id"]

            await session.call_tool("proposal_submit", {"proposal_id": proposal_id})
            await session.call_tool("proposal_approve", {"proposal_id": proposal_id})

            apply_res = await session.call_tool("proposal_apply", {"proposal_id": proposal_id})
            assert apply_res.isError
            assert "Consequential operation was not authorized" in apply_res.content[0].text
            assert "Traceback" not in apply_res.content[0].text

            target_path = vault_root / "wiki" / "target.md"
            assert not target_path.exists()

            proposal_dir = vault_root / "proposals" / proposal_id
            proposal_load = load_proposal_directory(
                proposal_dir, proposals_root=vault_root / "proposals"
            )
            assert proposal_load.proposal.metadata.status == ProposalStatus.APPROVED


@pytest.mark.anyio
async def test_mcp_consequential_schemas_reject_agent_controlled_fields(
    mcp_server_helper_path: Path,
    config: LifeOSConfig,
    config_path: Path,
    vault_root: Path,
    registry: Registry,
    setup_source: None,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "auth.jsonl"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(mcp_server_helper_path),
            "--config",
            str(config_path),
            "--actor-id",
            "integration-human",
            "--authorization-log",
            str(log_path),
        ],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            create_res = await session.call_tool(
                "ingestion_create_wiki_proposal",
                {
                    "source_path": "sources/test.md",
                    "target_path": "wiki/target.md",
                    "title": "Test Title",
                    "body": "Canonical candidate content.\n",
                },
            )
            proposal_id = json.loads(create_res.content[0].text)["proposal_id"]

            res = await session.call_tool(
                "proposal_submit",
                {"proposal_id": proposal_id, "review_digest": "fake"},
            )
            assert res.isError

            res2 = await session.call_tool(
                "proposal_submit", {"proposal_id": proposal_id, "actor_id": "fake"}
            )
            assert res2.isError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
