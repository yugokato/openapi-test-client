import asyncio

from quart import Blueprint, Response, jsonify, redirect, url_for
from quart_schema import tag

bp_test = Blueprint("Test", __name__, url_prefix="/test")
tag_test = tag(["Test"])


@bp_test.get("/echo/<int:number>")
@tag_test
async def echo(number: int) -> tuple[Response, int]:
    """Test endpoint that just echos the specified number"""
    return jsonify(number), 200


@bp_test.get("/wait/<float:delay>")
@tag_test
async def wait(delay: float) -> tuple[Response, int]:
    """Test endpoint that returns a response after waiting for the specified delay"""
    await asyncio.sleep(delay)
    return jsonify("ok"), 200


@bp_test.get("/redirect")
@tag_test
async def redirect_() -> Response:
    """Test endpoint that redirects to /redirected"""
    return redirect(url_for(f".{redirected.__name__}"), code=301)


@bp_test.get("/redirected")
@tag_test
async def redirected() -> tuple[Response, int]:
    """Test endpoint for the redirected route"""
    return jsonify("ok"), 200
