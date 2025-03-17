import uuid

from quart import Blueprint, Response, request

bp_request_handler = Blueprint("request_handler", __name__)


@bp_request_handler.before_app_request
async def before_request() -> None:
    if not request.headers.get("X-Request-ID"):
        request.headers["X-Request-ID"] = str(uuid.uuid4())


@bp_request_handler.after_app_request
async def after_request(response: Response) -> Response:
    # TODO: Add something
    return response
