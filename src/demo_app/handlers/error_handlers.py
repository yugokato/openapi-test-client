from dataclasses import asdict, dataclass
from typing import Any

from common_libs.logging import get_logger
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = get_logger(__name__)


@dataclass
class Error:
    code: int
    message: Any
    request_id: str


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def handle_http_errors(request: Request, error: HTTPException) -> Response:
        err = Error(code=error.status_code, message=error.detail, request_id=request.headers.get("X-Request-ID"))
        return JSONResponse(
            status_code=error.status_code,
            content={"error": asdict(err)},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, error: RequestValidationError) -> Response:
        err = Error(
            code=status.HTTP_400_BAD_REQUEST,
            message=error.errors(),
            request_id=request.headers.get("X-Request-ID"),
        )
        return JSONResponse(status_code=err.code, content={"error": asdict(err)})

    @app.exception_handler(Exception)
    async def handle_internal_server_error(request: Request, error: Exception) -> Response:
        logger.exception(error)
        err = Error(
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred while processing your request",
            request_id=request.headers.get("X-Request-ID"),
        )
        return JSONResponse(status_code=err.code, content={"error": asdict(err)})
