import pytest
from unittest.mock import patch
from pathlib import Path
from pydantic_ai.exceptions import UserError
from lifeos.ingestion.backend_factory import get_analysis_backend, AnalysisBackendConfigurationError
from lifeos.ingestion.pydantic_ai_backend import PydanticAIAnalysisBackend

def test_factory_uses_public_model_constructor(tmp_path: Path) -> None:
    with patch("pydantic_ai.models.infer_model") as mock_infer:
        mock_infer.return_value = "fake_model"
        backend = get_analysis_backend(vault_root=tmp_path, model_spec="openai:gpt-4o")
        mock_infer.assert_called_once_with("openai:gpt-4o")
        assert isinstance(backend, PydanticAIAnalysisBackend)
        assert backend.model == "fake_model"  # type: ignore
        assert backend.vault_root == tmp_path
        assert backend.model_id == "openai:gpt-4o"

def test_factory_raises_configuration_error_on_missing_provider(tmp_path: Path) -> None:
    with patch("pydantic_ai.models.infer_model", side_effect=ImportError("No openai")):
        with pytest.raises(AnalysisBackendConfigurationError, match="Missing required provider package: No openai"):
            get_analysis_backend(vault_root=tmp_path, model_spec="openai:gpt-4o")

def test_factory_raises_configuration_error_on_invalid_model(tmp_path: Path) -> None:
    with patch("pydantic_ai.models.infer_model", side_effect=UserError("Unknown model")):
        with pytest.raises(AnalysisBackendConfigurationError, match="Invalid AI model configuration"):
            get_analysis_backend(vault_root=tmp_path, model_spec="invalid")

def test_factory_raises_error_on_empty_spec(tmp_path: Path) -> None:
    with pytest.raises(AnalysisBackendConfigurationError, match="Model specification cannot be empty."):
        get_analysis_backend(vault_root=tmp_path, model_spec="   ")
