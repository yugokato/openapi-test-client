import json
from dataclasses import dataclass
from typing import Any

from quart import Blueprint, Response, jsonify, make_response, request
from quart import current_app as app
from quart_schema import RequestSchemaValidationError
from werkzeug.exceptions import BadRequest, MethodNotAllowed, NotFound, Unauthorized

bp_error_handler = Blueprint("error_handler", __name__)


@dataclass
class Error:
    code: int
    message: Any
    request_id: str


@bp_error_handler.app_errorhandler(BadRequest)
async def handle_bad_request_error(error: BadRequest) -> Response:
    err = Error(code=BadRequest.code, message=str(error), request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), BadRequest.code)


@bp_error_handler.app_errorhandler(Unauthorized)
async def handle_unauthorized_request(error: Unauthorized) -> Response:
    err = Error(code=Unauthorized.code, message="Login required", request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), Unauthorized.code)


@bp_error_handler.app_errorhandler(NotFound)
async def handle_not_found_error(error: NotFound) -> Response:
    err = Error(code=NotFound.code, message=error.description, request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), NotFound.code)


@bp_error_handler.app_errorhandler(MethodNotAllowed)
async def handle_method_not_allowed_error(error: MethodNotAllowed) -> Response:
    err = Error(code=MethodNotAllowed.code, message=error.description, request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), MethodNotAllowed.code)


@bp_error_handler.app_errorhandler(RequestSchemaValidationError)
async def handle_request_validation_error(error: RequestSchemaValidationError) -> Response:
    app.logger.error(error)
    if isinstance(error.validation_error, TypeError):
        errors = error.validation_error
    else:
        errors = json.loads(error.validation_error.json())
    err = Error(code=400, message=errors, request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), 400)


@bp_error_handler.app_errorhandler(Exception)
async def handle_internal_server_error(error: Exception) -> Response:
    err = Error(
        code=500,
        message="An unexpected error occurred while processing your request",
        request_id=request.headers["X-Request-ID"],
    )
    app.logger.exception(error)
    return await make_response(jsonify({"error": err}), 500)
