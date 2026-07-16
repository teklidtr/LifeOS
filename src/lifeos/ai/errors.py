class LifeOSAIError(RuntimeError):
    """Base class for all LifeOS AI runtime errors."""


class LifeOSAIValidationError(LifeOSAIError):
    """Raised when caller inputs or dependencies are invalid."""


class LifeOSAIModelError(LifeOSAIError):
    """Raised when the underlying AI provider or model execution fails."""


class LifeOSAIToolError(LifeOSAIError):
    """Raised when a tool execution fails and aborts the run."""
