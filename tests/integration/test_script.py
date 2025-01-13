import inspect
from pathlib import Path

import pytest
from common_libs.utils import list_items
from pytest_lazy_fixtures import lf as lazy_fixture

from openapi_test_client import logger
from openapi_test_client.clients import OpenAPIClient
from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.clients.demo_app.api import API_CLASSES
from openapi_test_client.clients.demo_app.api.users import UsersAPI
from openapi_test_client.libraries.api.api_client_generator import (
    API_MODEL_CLASS_DIR_NAME,
    TAB,
    update_endpoint_functions,
)
from tests.integration import helper
from tests.integration.conftest import demo_app_openapi_spec_url, petstore_openapi_spec_url


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "url",
    [lazy_fixture(demo_app_openapi_spec_url.__name__), lazy_fixture(petstore_openapi_spec_url.__name__)],
)
def test_generate_client(
    url: str,
    random_app_name: str,
    dry_run: bool,
    external_dir: Path | None,
):
    """Check that a new API client can be generated with the "generate" command.

    This test covers the following two different use cases for the location of the generated client modules
    - in the same project
    - in an external project
    """
    args = f"generate -u {url} -a {random_app_name}"
    if external_dir:
        args += f" --dir {external_dir}"
    if dry_run:
        args += " -d"
    _, stderr = helper.run_command(args)
    assert not stderr

    if not dry_run:
        # Attempt to generate another client with the same name
        args = f"generate -u {url} -a {random_app_name}"
        if external_dir:
            args += f" --dir {external_dir}"
        _, stderr = helper.run_command(args)
        assert stderr
        assert f"API Client for '{random_app_name}' already exists in {external_dir}"

        if external_dir:
            # Generate another client in the same external directory. This is allowed
            args = f"generate -u {url} -a {random_app_name}_2 --dir {external_dir}"
            _, stderr = helper.run_command(args)
            assert not stderr

            # Attempt to generate another client in another location. We don't allow this scenario
            args = f"generate -u {url} -a {random_app_name} --dir {external_dir}_new"
            _, stderr = helper.run_command(args)
            assert stderr
            assert f"Detected the existing client setup in {external_dir}" in stderr


@pytest.mark.parametrize(
    "option",
    [
        None,
        *[pytest.param(f"{opt} {UsersAPI.TAGs[0]}", id=f"option={opt}") for opt in ["-t", "--tag"]],
        *[pytest.param(f'{opt} "{UsersAPI.create_user.endpoint}"', id=f"option={opt}") for opt in ["-e", "--endpoint"]],
        *[pytest.param(f"{opt} {UsersAPI.__name__}", id=f"option={opt}") for opt in ["-a", "--api-class"]],
        *[
            pytest.param(f"{opt} {UsersAPI.create_user.__name__}", id=f"option={opt}")
            for opt in ["-f", "--api-function"]
        ],
        *[pytest.param(f"{opt}", id=f"option={opt}") for opt in ["-A", "--add-api-class"]],
        *[pytest.param(f"{opt}", id=f"option={opt}") for opt in ["-m", "--model-only"]],
        *[pytest.param(f'{opt} "{UsersAPI.create_user.endpoint}"', id=f"option={opt}") for opt in ["-i", "--ignore"]],
        *[pytest.param(f"{opt}", id=f"option={opt}") for opt in ["-I", "--ignore-undefined-endpoints"]],
        *[pytest.param(f"{opt}", id=f"option={opt}") for opt in ["-q", "--quiet"]],
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_update_client(temp_app_client: OpenAPIClient, dry_run: bool, option: str | None):
    """Check that API client can be updated with various options.

    NOTE: temp_app_client is a temporary client generated for this test against the demo_app app.
          API class and model file code should be identical to DemoAppAPIClient's, except for API function names
    """
    users_api = getattr(temp_app_client, "USERS")
    assert users_api._unnamed_endpoint_1.endpoint == UsersAPI.create_user.endpoint
    users_api_class_file = Path(inspect.getabsfile(type(users_api)))
    assert users_api_class_file.exists()

    original_api_class_code = users_api_class_file.read_text()

    # First adjust the original code around the create_user API function to simulate some user customizations after
    # the initial client generation
    original_api_class_code = original_api_class_code.replace(
        # Change function name "_unnamed_endpoint_1" to "create_user" to simulate the real life scenario
        "_unnamed_endpoint_1",
        UsersAPI.create_user.__name__,
    )
    create_user_func_docstring = '"""Create a new user"""'
    original_api_class_code = original_api_class_code.replace(
        # Replace the placeholder with fake custom logic
        f"{TAB * 2}{create_user_func_docstring}\n{TAB * 2}...",
        (
            f"{TAB * 2}{create_user_func_docstring}\n"
            f"{TAB * 2}# fake custom func logic\n"
            f"{TAB * 2}params = dict(first_name=first_name, last_name=last_name, email=email, role=role, metadata=metadata)\n"  # noqa: E501
            f"{TAB * 2}return self.{UsersAPI.create_user.__name__}(**params)"
        ),
    )

    # Remove some code from the API class
    modified_api_class_code = original_api_class_code
    for code_to_delete in [
        "from ..models.users import Metadata\n",
        "metadata: Optional[Metadata] = Unset,\n",
        f"{TAB*2}{create_user_func_docstring}\n",
    ]:
        assert code_to_delete in original_api_class_code
        modified_api_class_code = modified_api_class_code.replace(code_to_delete, "")
    users_api_class_file.write_text(modified_api_class_code)

    # Delete model file
    users_model_file = users_api_class_file.parent.parent / API_MODEL_CLASS_DIR_NAME / users_api_class_file.name
    assert users_model_file.exists()
    original_model_code = users_model_file.read_text()
    users_model_file.unlink()

    args = f"update -c {temp_app_client.app_name}"
    if option:
        args += f" {option}"
    if dry_run:
        args += " -d"
    _, stderr = helper.run_command(args)
    if stderr:
        print(stderr)
    assert not stderr

    if dry_run or option and option.startswith(("-i ", "--ignore ")):
        # Code should not be actually updated
        assert users_api_class_file.read_text() == modified_api_class_code
        assert not users_model_file.exists()
    else:
        # Code should be updated within the specified scope
        if option in ["-m", "--model-only"]:
            assert users_api_class_file.read_text() == modified_api_class_code
        else:
            assert users_api_class_file.read_text() == original_api_class_code
        assert users_model_file.exists()
        assert users_model_file.read_text() == original_model_code


def test_demo_app_api_client_is_up_to_date(unauthenticated_api_client: DemoAppAPIClient):
    """Check that DemoAppAPIClient code is up-to-date"""
    api_spec = unauthenticated_api_client.api_spec.get_api_spec()
    update_required = []
    for api_class in API_CLASSES:
        result = update_endpoint_functions(api_class, api_spec, dry_run=True, verbose=True)
        if result is True:
            update_required.append(api_class)

    if update_required:
        logger.error(
            f"One or more API functions for the following API classes do not match with the latest OpenAPI specs.\n"
            f"{list_items(x.__name__ for x in update_required)}"
        )
    assert len(update_required) == 0
