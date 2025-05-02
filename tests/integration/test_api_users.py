import pytest

from demo_app.api.user.user import USERS
from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.clients.demo_app.models.users import Metadata, Preferences, SocialLinks
from openapi_test_client.libraries.api.types import File
from tests.integration import helper

pytestmark = pytest.mark.xdist_group("integration/api")


@pytest.mark.parametrize("validation_mode", [False, True])
def test_create_user(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check basic client/server functionality of create user API"""
    r = api_client.Users.create_user(
        first_name="test",
        last_name="test",
        email="test@demo.app.net",
        role="admin",
        metadata=Metadata(
            preferences=Preferences(theme="dark", font_size=10),
            social_links=SocialLinks(github="https://github.com/foo/bar"),
        ),
        validate=validation_mode,
    )
    assert r.status_code == 201
    assert r.response["id"] > len(USERS)


@pytest.mark.parametrize("validation_mode", [False, True])
def test_get_user(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check basic client/server functionality of get user API"""
    user_id = 5
    r = api_client.Users.get_user(user_id, validate=validation_mode)
    assert r.status_code == 200
    assert r.response["id"] == user_id


@pytest.mark.parametrize("validation_mode", [False, True])
def test_get_users(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check basic client/server functionality of get users API"""
    role = "support"
    r = api_client.Users.get_users(role=role, validate=validation_mode)
    assert r.status_code == 200
    assert len(r.response) == len([x for x in USERS if x.role.value == role])


@pytest.mark.parametrize("validation_mode", [False, True])
def test_upload_image(api_client: DemoAppAPIClient, validation_mode: bool, image_data: bytes) -> None:
    """Check basic client/server functionality of upload user image API"""
    file = File(filename="test_image.png", content=image_data, content_type="image/png")
    r = api_client.Users.upload_image(file=file, description="test image", validate=validation_mode)
    assert r.status_code == 201
    assert r.response["message"] == f"Image '{file.filename}' uploaded"


@pytest.mark.parametrize("validation_mode", [False, True])
def test_delete_user(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check basic client/server functionality of delete user API"""
    user_id = 1 + bool(validation_mode)
    r = api_client.Users.delete_user(user_id, validate=validation_mode)
    assert r.status_code == 200
    assert r.response["message"] == f"Deleted user {user_id}"


@pytest.mark.parametrize("validation_mode", [False, True])
def test_create_user_with_invalid_params(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check validation for create user API

    The request contains the following 7 errors
    - first_name: invalid type
    - last_name:  missing required param
    - email: Invalid email format
    - role: Invalid enum value
    - metadata.preferences.theme: Invalid enum value
    - metadata.preferences.font_size: Violation of min_len
    - metadata.social_links.github: Invalid URL format

    """
    helper.do_test_invalid_params(
        endpoint_func=api_client.Users.create_user,
        validation_mode=validation_mode,
        invalid_params=dict(
            first_name=123,
            email="test",
            role="test",
            metadata=Metadata(
                preferences=Preferences(theme="test", font_size=3),
                social_links=SocialLinks(github="test"),
            ),
        ),
        num_expected_errors=7,
    )


@pytest.mark.parametrize("validation_mode", [False, True])
def test_get_users_with_invalid_params(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check validation for get users API

    The request contains the following 2 errors
    - id: invalid type
    - role: Invalid enum value
    """
    helper.do_test_invalid_params(
        endpoint_func=api_client.Users.get_users,
        validation_mode=validation_mode,
        invalid_params=dict(id="test", role="test"),
        num_expected_errors=2,
    )


@pytest.mark.parametrize(
    "validation_mode", [pytest.param(False, marks=pytest.mark.skip(reason="Not applicable")), True]
)
def test_upload_image_with_invalid_params(api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check validation for upload user image API

    The request contains the following error
    - file: invalid type

    NOTE: The annotated param type `File` is only applicable for the client side. Server side won't care as long as
          the content is properly uploaded with the multipart/form-data Content-Type header
    """
    helper.do_test_invalid_params(
        endpoint_func=api_client.Users.upload_image,
        validation_mode=validation_mode,
        invalid_params=dict(file="test"),
        num_expected_errors=1,
    )
