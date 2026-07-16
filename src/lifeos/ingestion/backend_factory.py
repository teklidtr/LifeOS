from pathlib import Path
from lifeos.ingestion.backend import AnalysisBackend

class AnalysisBackendConfigurationError(RuntimeError):
    pass

def get_analysis_backend(*, vault_root: Path, model_spec: str) -> AnalysisBackend:
    if not model_spec or not model_spec.strip():
        raise AnalysisBackendConfigurationError("Model specification cannot be empty.")
    
    try:
        from pydantic_ai.models import infer_model
        from pydantic_ai.exceptions import UserError
    except ImportError as e:
        raise AnalysisBackendConfigurationError(f"Missing required AI package: {e}") from e

    try:
        model = infer_model(model_spec)
    except UserError as e:
        raise AnalysisBackendConfigurationError("Invalid AI model configuration") from e
    except ImportError as e:
        raise AnalysisBackendConfigurationError(f"Missing required provider package: {e}") from e
    
    from lifeos.ingestion.pydantic_ai_backend import PydanticAIAnalysisBackend
    return PydanticAIAnalysisBackend(model=model, vault_root=vault_root, model_id=model_spec)
