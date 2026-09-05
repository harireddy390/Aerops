"""Domain exceptions -> clean API errors (never leak stack traces to clients)."""
from fastapi import Request
from fastapi.responses import JSONResponse


class AeroOpsError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(AeroOpsError):
    status_code = 404
    code = "not_found"


class Conflict(AeroOpsError):
    status_code = 409
    code = "conflict"


class PolicyDenied(AeroOpsError):
    status_code = 403
    code = "policy_denied"


async def aeroops_error_handler(_: Request, exc: AeroOpsError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "detail": exc.message})
