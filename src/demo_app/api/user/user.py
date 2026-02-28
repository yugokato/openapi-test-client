from quart import Blueprint, Response, abort, jsonify
from quart_auth import login_required
from quart_schema import DataSource, tag, validate_querystring, validate_request

from .models import User, UserImage, UserQuery, UserRequest, UserRole

bp_user = Blueprint("User", __name__, url_prefix="/users")
tag_users = tag(["Users"])

USER_ROLES = list(UserRole._member_map_.values())
USERS = [
    User(
        id=i,
        first_name=f"first_name_{i}",
        last_name=f"last_name_{i}",
        email=f"user{i}@demo.app.net",
        role=USER_ROLES[i % len(USER_ROLES)].value,
    )
    for i in range(1, 11)
]
_next_user_id = len(USERS) + 1


@bp_user.post("")
@tag_users
@login_required
@validate_request(UserRequest)
async def create_user(data: UserRequest) -> tuple[Response, int]:
    """Create a new user"""
    global _next_user_id  # noqa: PLW0603
    user = User(id=_next_user_id, **data.model_dump(mode="json"))
    _next_user_id += 1
    # This is just a demo app. There's no fancy lock here
    USERS.append(user)
    return jsonify(user), 201


@bp_user.get("/<int:user_id>")
@tag_users
@login_required
async def get_user(user_id: int) -> tuple[Response, int]:
    """Get user"""
    if users := _filter_users(UserQuery(id=user_id)):
        return jsonify(users[0]), 200
    else:
        abort(404, f"User ID {user_id} does not exist")


@bp_user.get("")
@tag_users
@login_required
@validate_querystring(UserQuery)
async def get_users(query_args: UserQuery) -> tuple[Response, int]:
    """Get users"""
    users = _filter_users(query_args)
    return jsonify(users), 200


@bp_user.post("/images")
@tag_users
@login_required
@validate_request(UserImage, source=DataSource.FORM_MULTIPART)
async def upload_image(data: UserImage) -> tuple[Response, int]:
    """Upload user image"""
    # This won't actually save anything. Just return a fake response
    return jsonify({"message": f"Image '{data.file.filename}' uploaded"}), 201


@bp_user.delete("/<int:user_id>")
@tag_users
@login_required
async def delete_user(user_id: int) -> tuple[Response, int]:
    """Delete user"""
    if users := _filter_users(UserQuery(id=user_id)):
        USERS.remove(users[0])
    else:
        abort(404, f"User ID {user_id} does not exist")
    return jsonify({"message": f"Deleted user {user_id}"}), 200


def _filter_users(query: UserQuery) -> list[User]:
    filtered_users = []
    for user in USERS:
        if query.id is not None and user.id != query.id:
            continue
        if query.email is not None and user.email != query.email:
            continue
        if query.role is not None and user.role.value != query.role.value:
            continue
        filtered_users.append(user)
    return filtered_users
