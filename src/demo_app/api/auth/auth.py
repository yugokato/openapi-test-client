import uuid

from quart import Blueprint, Response, jsonify
from quart_auth import logout_user
from quart_schema import security_scheme, tag, validate_request

from demo_app import auth_manager

from .models import LoginData

bp_auth = Blueprint("Auth", __name__, url_prefix="/auth")
tag_auth = tag(["Auth"])


@bp_auth.post("/login")
@tag_auth
@security_scheme([])
@validate_request(LoginData)
async def login(data: LoginData) -> tuple[Response, int]:
    """Login"""
    # Just assign a random uuid for this user as there's no actual BE
    user_uuid = str(uuid.uuid4())
    token = auth_manager.dump_token(user_uuid)
    return jsonify({"token": token}), 201


@bp_auth.post("/logout")
@tag_auth
@security_scheme([])
async def logout() -> tuple[Response, int]:
    """Logout"""
    logout_user()
    return jsonify({"message": "logged out"}), 200
