import secrets

from quart import Blueprint, Quart
from quart_auth import QuartAuth
from quart_schema import Info, QuartSchema

auth_manager = QuartAuth()


def create_app(version: int = 1) -> Quart:
    app = Quart(__name__)
    QuartSchema(
        app,
        info=Info(title="Demo app API", version="0.1.0"),
        tags=[
            {"name": "Auth", "description": "Auth APIs"},
            {"name": "Users", "description": "User APIs"},
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


def _register_blueprints(app, version: int):
    from demo_app.api.auth.auth import bp_auth
    from demo_app.api.user.user import bp_user
    from demo_app.handlers.error_handlers import bp_error_handler
    from demo_app.handlers.request_handlers import bp_request_handler

    bp_api = Blueprint(f"demo_app", __name__, url_prefix=f"/v{version}")
    bp_api.register_blueprint(bp_auth, name=bp_auth.name)
    bp_api.register_blueprint(bp_user, name=bp_user.name)

    app.register_blueprint(bp_api, name=bp_api.name)
    app.register_blueprint(bp_request_handler, name=bp_request_handler.name)
    app.register_blueprint(bp_error_handler, name=bp_error_handler.name)


app = create_app()
