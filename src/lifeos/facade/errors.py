class ToolFacadeError(RuntimeError):
    pass

class ToolValidationError(ToolFacadeError):
    pass

class ToolNotFoundError(ToolFacadeError):
    pass

class ToolConflictError(ToolFacadeError):
    pass

class ToolOwnershipConflictError(ToolConflictError):
    """A bounded ownership conflict whose message is safe to show to an MCP caller."""

    pass

class ToolUnavailableError(ToolFacadeError):
    pass

class ToolRecoveryRequiredError(ToolUnavailableError):
    pass

class ToolAuthorizationError(ToolFacadeError):
    pass

class ToolExecutionError(ToolFacadeError):
    pass
