from quart import Blueprint, Response, jsonify
from quart_schema import tag

bp_test = Blueprint("_Test", __name__, url_prefix="/test")
tag_test = tag(["_Test"])


@bp_test.get("/<int:some_id>")
@tag_test
async def test(some_id: int) -> tuple[Response, int]:
    """Test endpoint that just echos the specified ID value"""
    return jsonify(some_id), 200
