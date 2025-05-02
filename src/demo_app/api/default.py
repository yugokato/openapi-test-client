from quart import Blueprint
from quart_schema import hide

bp_default = Blueprint("Default", __name__)


@bp_default.get("/")
@hide
async def hello() -> str:
    return "hello"
