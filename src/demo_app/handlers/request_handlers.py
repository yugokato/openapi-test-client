import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response


def add_request_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def before_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id_header = "X-Request-ID"
        if not request.headers.get(request_id_header):
            headers = request.headers.mutablecopy()
            headers[request_id_header] = str(uuid.uuid4())
            request.scope.update(headers=headers.raw)
            request._headers = headers
        response = await call_next(request)
        return response
