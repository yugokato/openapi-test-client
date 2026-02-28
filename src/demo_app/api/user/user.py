from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.security import HTTPBearer

from .models import User, UserQuery, UserRequest, UserRole

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(HTTPBearer())])

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


@router.post("", status_code=201)
async def create_user(data: UserRequest) -> User:
    """Create a new user"""
    global _next_user_id  # noqa: PLW0603
    user = User(id=_next_user_id, **data.model_dump(mode="json"))
    _next_user_id += 1
    # This is just a demo app. There's no fancy lock here
    USERS.append(user)
    return user


@router.get("/{user_id}")
async def get_user(user_id: int) -> User:
    """Get user"""
    if users := _filter_users(UserQuery(id=user_id)):
        return users[0]
    raise HTTPException(404, f"User ID {user_id} does not exist")


@router.get("")
async def get_users(query_args: Annotated[UserQuery, Query()]) -> list[User]:
    """Get users"""
    return _filter_users(query_args)


@router.post("/images", status_code=201)
async def upload_image(file: UploadFile, description: Annotated[str | None, Form()] = None) -> dict[str, str]:
    """Upload user image"""
    # This won't actually save anything. Just return a fake response
    return {"message": f"Image '{file.filename}' uploaded"}


@router.delete("/{user_id}")
async def delete_user(user_id: int) -> dict[str, str]:
    """Delete user"""
    if users := _filter_users(UserQuery(id=user_id)):
        USERS.remove(users[0])
        return {"message": f"Deleted user {user_id}"}
    raise HTTPException(404, f"User ID {user_id} does not exist")


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
