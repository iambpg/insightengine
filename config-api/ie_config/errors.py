"""Error envelope shared with the Settings UI: {error: {code, message, details}}."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def error_body(exc: ApiError) -> dict:
    return {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
