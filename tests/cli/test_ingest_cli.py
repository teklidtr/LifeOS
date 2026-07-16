import pytest
from unittest.mock import patch
from pathlib import Path
from lifeos.cli import main
from lifeos.ingestion.cli_service import IngestProposalResult
from lifeos.ingestion.backend import AnalysisBackendError

def test_cli_ingest_success_returns_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    config_yml = "vault_root: vault\nruntime_dir: runtime\n"
    (tmp_path / "lifeos.yml").write_text(config_yml)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    (tmp_path / "runtime").mkdir()

    with patch("lifeos.ingestion.backend_factory.get_analysis_backend") as mock_factory:
        with patch("lifeos.ingestion.cli_service.ingest_source") as mock_service:
            with patch("lifeos.proposals.schema.generate_proposal_id") as mock_id:
                mock_id.return_value = "prop-12345678T123456Z-abcdef12"
                mock_service.return_value = IngestProposalResult(
                    proposal_id="prop-12345678T123456Z-abcdef12",
                    proposal_path=tmp_path / "vault" / "proposals" / "prop-12345678T123456Z-abcdef12",
                    target_path="wiki/target.md"
                )
                
                # Use model via flag
                exit_code = main(["ingest", "test.md", "--target", "wiki/target.md", "--model", "openai:gpt-4o"])
                
                assert exit_code == 0
                out, err = capfd.readouterr()
                assert "Created draft proposal prop-12345678T123456Z-abcdef12 at proposals/prop-12345678T123456Z-abcdef12/" in out
                mock_factory.assert_called_once_with(vault_root=tmp_path / "vault", model_spec="openai:gpt-4o")

def test_cli_reads_model_from_env_and_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_yml = "vault_root: vault\nruntime_dir: runtime\n"
    (tmp_path / "lifeos.yml").write_text(config_yml)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    (tmp_path / "runtime").mkdir()
    monkeypatch.setenv("LIFEOS_AI_MODEL", "google:gemini-1.5-pro")

    with patch("lifeos.ingestion.backend_factory.get_analysis_backend") as mock_factory:
        with patch("lifeos.ingestion.cli_service.ingest_source"):
            with patch("lifeos.proposals.schema.generate_proposal_id"):
                exit_code = main(["ingest", "test.md", "--target", "wiki/target.md"])
                assert exit_code == 0
                mock_factory.assert_called_once_with(vault_root=tmp_path / "vault", model_spec="google:gemini-1.5-pro")

def test_cli_ingest_failure_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    config_yml = "vault_root: vault\nruntime_dir: runtime\n"
    (tmp_path / "lifeos.yml").write_text(config_yml)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    (tmp_path / "runtime").mkdir()
    
    with patch("lifeos.ingestion.backend_factory.get_analysis_backend"):
        with patch("lifeos.ingestion.cli_service.ingest_source") as mock_service:
            with patch("lifeos.proposals.schema.generate_proposal_id"):
                mock_service.side_effect = AnalysisBackendError("AI failed")
                
                exit_code = main(["ingest", "test.md", "--target", "wiki/target.md", "--model", "openai:gpt-4o"])
                
                assert exit_code == 1
                out, err = capfd.readouterr()
                assert "Analysis error: AI failed" in err

def test_cli_output_contains_no_host_paths_or_source_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    config_yml = "vault_root: vault\nruntime_dir: runtime\n"
    (tmp_path / "lifeos.yml").write_text(config_yml)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    (tmp_path / "runtime").mkdir()

    with patch("lifeos.ingestion.backend_factory.get_analysis_backend"):
        with patch("lifeos.ingestion.cli_service.ingest_source") as mock_service:
            with patch("lifeos.proposals.schema.generate_proposal_id") as mock_id:
                mock_id.return_value = "prop-12345678T123456Z-abcdef12"
                mock_service.return_value = IngestProposalResult(
                    proposal_id="prop-12345678T123456Z-abcdef12",
                    proposal_path=tmp_path / "vault" / "proposals" / "prop-12345678T123456Z-abcdef12",
                    target_path="wiki/target.md"
                )
                
                # Ensure the mock doesn't print any host path
                exit_code = main(["ingest", "test.md", "--target", "wiki/target.md", "--model", "openai:gpt-4o"])
                
                assert exit_code == 0
                out, err = capfd.readouterr()
                
                # Check that absolute paths are not in the output
                assert str(tmp_path) not in out
                assert str(tmp_path) not in err
                
                # Check that the output only contains relative vault paths
                assert "proposals/prop-12345678T123456Z-abcdef12/" in out

