from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from demo_app.handlers.error_handlers import add_exception_handlers
from demo_app.handlers.request_handlers import add_request_handlers
from demo_app.patch import APIRouter

security = HTTPBearer()
router = APIRouter(prefix="/v1")
_active_tokens: set[str] = set()


async def login_required(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]) -> str:
    """Validate the bearer token is active.

    :param credentials: HTTP bearer credentials from the Authorization header
    :returns: The validated token string
    :raises HTTPException: 401 if the token is not in the active token store
    """
    token = credentials.credentials
    if token not in _active_tokens:
        raise HTTPException(status_code=401, detail="Login required")
    return token


def create_app() -> FastAPI:
    app = FastAPI(
        title=__name__,
        openapi_tags=[
            {"name": "Auth", "description": "Auth APIs"},
            {"name": "Users", "description": "User APIs"},
            {"name": "_Test", "description": "Test APIs"},
        ],
    )
    return app


def init_app(app: FastAPI) -> FastAPI:
    add_request_handlers(app)
    add_exception_handlers(app)
    _register_routers(app)
    return app


def _register_routers(app: FastAPI) -> None:
    from demo_app.api._hidden import _hidden
    from demo_app.api._test import test
    from demo_app.api.auth import auth
    from demo_app.api.user import user

    router.include_router(test.router)
    router.include_router(auth.router)
    router.include_router(user.router)
    app.include_router(router)
    app.include_router(_hidden.router)


app = init_app(create_app())
