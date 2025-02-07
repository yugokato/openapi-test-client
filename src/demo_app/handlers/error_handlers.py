import json
from dataclasses import dataclass

from quart import Blueprint, Response, jsonify, make_response, request
from quart import current_app as app
from quart_schema import RequestSchemaValidationError
from werkzeug.exceptions import NotFound

bp_error_handler = Blueprint("error_handler", __name__)


@dataclass
class Error:
    code: int
    message: str
    request_id: str


@bp_error_handler.app_errorhandler(400)
async def handle_bad_request_error(error) -> Response:
    err = Error(code=400, message=str(error), request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), 400)


@bp_error_handler.app_errorhandler(401)
async def handle_unauthorized_request(error) -> Response:
    err = Error(code=401, message="Login required", request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), 401)


@bp_error_handler.app_errorhandler(404)
async def handle_not_found_error(error: NotFound) -> Response:
    err = Error(code=404, message=error.description, request_id=request.headers["X-Request-ID"])
    return await make_response(jsonify({"error": err}), 404)


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
