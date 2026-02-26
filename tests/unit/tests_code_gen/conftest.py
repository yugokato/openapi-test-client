import json
import os
import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from openapi_test_client import ENV_VAR_PACKAGE_DIR
from openapi_test_client.clients.openapi import OpenAPIClient
from openapi_test_client.libraries.code_gen.client_generator import setup_external_directory
from openapi_test_client.libraries.core.api_spec import OpenAPISpec
from tests.unit.tests_code_gen import helper


@pytest.fixture
def temp_api_client(
    temp_dir: Path, mocker: MockerFixture, openapi_specs: dict[str, Any]
) -> Generator[OpenAPIClient, Any, None]:
    """Temporary API client needed for code generation"""
    app_name = "test_app"
    module_dir = temp_dir / "my_clients"

    mocker.patch.dict(os.environ, {ENV_VAR_PACKAGE_DIR: str(module_dir)})
    setup_external_directory(app_name, "http://localhost")

    client = OpenAPIClient(app_name, "/docs")
    mocker.patch.object(client.api_spec, "get_api_spec", return_value=openapi_specs)

    yield client

    shutil.rmtree(temp_dir)


@pytest.fixture(scope="session")
def openapi_specs() -> dict[str, Any]:
    """Sample OpenAPI specs created for testing"""
    openapi_specs = helper.load_test_data("openapi.json")
    return OpenAPISpec.parse(json.loads(openapi_specs))
