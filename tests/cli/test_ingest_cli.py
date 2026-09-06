from pathlib import Path

import pytest

from lifeos.cli import main


def test_cli_help_does_not_advertise_ingest(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "ingest" not in captured.out
    assert captured.err == ""


def test_cli_rejects_ingest_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["ingest", "study/example.md", "--target", "wiki/example.md"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "invalid choice: 'ingest'" in captured.err


def test_core_source_has_no_embedded_ingestion_agent_or_api_key_path() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "src" / "lifeos"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(source_root.rglob("*.py"))
    )

    assert "pydantic_ai" not in source
    assert "LIFEOS_AI_MODEL" not in source
    assert "OPENAI_API_KEY" not in source
    assert "get_analysis_backend" not in source
    assert "AnalysisBackend" not in source

    ingestion_root = source_root / "ingestion"
    for removed_name in (
        "backend.py",
        "backend_factory.py",
        "cli_service.py",
        "pydantic_ai_backend.py",
    ):
        assert not (ingestion_root / removed_name).exists()
    assert not list((source_root / "ai").glob("*.py"))

    pyproject = (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "pydantic-ai" not in pyproject
    assert "ai = [" not in pyproject
