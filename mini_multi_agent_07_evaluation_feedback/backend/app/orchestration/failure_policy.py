def classify_failure(error: Exception, retryable_error_names: set[str] | None = None) -> str:
    if getattr(error, "retryable", False):
        return "retry"
    if isinstance(error, PermissionError):
        return "block"
    if isinstance(error, ValueError):
        return "replan"
    configured_names = retryable_error_names if retryable_error_names is not None else {"TimeoutError", "ConnectionError"}
    if type(error).__name__ in configured_names:
        return "retry"
    if retryable_error_names is None and ("timeout" in type(error).__name__.lower() or "connect" in type(error).__name__.lower()):
        return "retry"
    return "human_escalation"
