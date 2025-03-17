import json
import os
import shutil
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pytest import FixtureRequest
from pytest_mock import MockerFixture

from openapi_test_client import ENV_VAR_PACKAGE_DIR
from openapi_test_client.clients.base import OpenAPIClient
from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.clients.demo_app.api.auth import AuthAPI
from openapi_test_client.libraries.api.api_client_generator import (
    setup_external_directory,
)
from openapi_test_client.libraries.api.api_spec import OpenAPISpec
from openapi_test_client.libraries.api.types import ParamModel, Unset
from tests.unit import helper


@pytest.fixture(scope="session")
def api_client() -> DemoAppAPIClient:
    """API client"""
    return DemoAppAPIClient()


@pytest.fixture(params=["instance", "class"])
def api_class_or_instance(request: FixtureRequest, api_client: DemoAppAPIClient) -> AuthAPI | type[AuthAPI]:
    """Parametrize fixture that returns the demo API client's AuthAPI class or an isntance of the class"""
    if request.param == "instance":
        return api_client.Auth
    else:
        return AuthAPI


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


@pytest.fixture(scope="session")
def EmptyParamModel() -> type[ParamModel]:
    """A ParamModel that has no attributes"""

    @dataclass
    class Model(ParamModel): ...

    return Model


@pytest.fixture(scope="session")
def RegularParamModel(InnerParamModel: type[ParamModel]) -> type[ParamModel]:
    """A ParamModel that has some attributes and a nested model"""

    @dataclass
    class Model(ParamModel):
        param1: str = Unset
        param2: str = Unset
        param3: InnerParamModel = Unset  # type: ignore[valid-type]

    return Model


@pytest.fixture(scope="session")
def InnerParamModel() -> type[ParamModel]:
    """A ParamModel used for a nested model"""

    @dataclass
    class Model(ParamModel):
        inner_param1: str = Unset
        inner_param2: str = Unset

    return Model
