import asyncio

from quart import Blueprint, Response, jsonify
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
