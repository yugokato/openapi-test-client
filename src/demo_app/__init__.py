import secrets
from typing import ClassVar

from quart import Blueprint, Quart, request
from quart_auth import AuthUser
from quart_auth import QuartAuth as _QuartAuth
from quart_schema import Info, QuartSchema


class QuartAuth(_QuartAuth):
    """QuartAuth subclass that rejects revoked bearer tokens at resolution time.

    Overrides resolve_user() so that quart_auth.login_required natively denies revoked tokens.
    """

    _revoked_tokens: ClassVar[set[str]] = set()

    def resolve_user(self) -> AuthUser:
        """Resolve the current request user, returning unauthenticated for revoked tokens."""
        raw = request.headers.get("Authorization", "")
        if raw.lower().startswith("bearer "):
            token = raw[7:].strip()
            if QuartAuth.is_token_revoked(token):
                return self.user_class(None)
        return super().resolve_user()

    @staticmethod
    def revoke_token(token: str) -> None:
        """Add a token to the revocation set.

        :param token: The bearer token to revoke.
        """
        QuartAuth._revoked_tokens.add(token)

    @staticmethod
    def is_token_revoked(token: str) -> bool:
        """Check if a token has been revoked.

        :param token: The bearer token to check.
        """
        return token in QuartAuth._revoked_tokens


auth_manager = QuartAuth()


def create_app(version: int = 1) -> Quart:
    """Create and configure the demo Quart application.

    :param version: API version number used as a URL prefix.
    """
    app = Quart(__name__)
    QuartSchema(
        app,
        info=Info(title="Demo app API", version="0.1.0"),
        tags=[
            {"name": "Auth", "description": "Auth APIs"},
            {"name": "Users", "description": "User APIs"},
            {"name": "_Test", "description": "Test APIs"},
        ],
        security=[{"bearerAuth": []}],
        security_schemes={"bearerAuth": {"type": "http", "scheme": "bearer"}},
    )
    app.config["QUART_AUTH_MODE"] = "bearer"
    app.secret_key = secrets.token_urlsafe(16)
    app.json.sort_keys = False
    auth_manager.init_app(app)
    _register_blueprints(app, version=version)
    return app


def _register_blueprints(app: Quart, version: int) -> None:
    from demo_app.api._test.test import bp_test
    from demo_app.api.auth.auth import bp_auth
    from demo_app.api.default import bp_default
    from demo_app.api.user.user import bp_user
    from demo_app.handlers.error_handlers import bp_error_handler
    from demo_app.handlers.request_handlers import bp_request_handler

    bp_api = Blueprint("demo_app", __name__, url_prefix=f"/v{version}")
    bp_api.register_blueprint(bp_test, name=bp_test.name)
    bp_api.register_blueprint(bp_auth, name=bp_auth.name)
    bp_api.register_blueprint(bp_user, name=bp_user.name)

    app.register_blueprint(bp_api, name=bp_api.name)
    app.register_blueprint(bp_default, name=bp_default.name)
    app.register_blueprint(bp_request_handler, name=bp_request_handler.name)
    app.register_blueprint(bp_error_handler, name=bp_error_handler.name)


app = create_app()
