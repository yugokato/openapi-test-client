import json
import os
import random
import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
from _pytest.fixtures import SubRequest
from pytest import FixtureRequest, TempPathFactory
from pytest_mock import MockerFixture

from openapi_test_client import ENV_VAR_PACKAGE_DIR, get_config_dir
from openapi_test_client.clients import OpenAPIClient
from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.libraries.code_gen.client_generator import get_client_dir
from tests.conftest import temp_dir
from tests.integration import helper
from tests.integration.helper import DemoAppLifecycleManager

IS_TOX = os.environ.get("IS_TOX")


@pytest.fixture(scope="module")
def _default_port() -> Generator[int]:
    with DemoAppAPIClient() as client:
        cfg = json.loads((get_config_dir() / "urls.json").read_text())
        base_url = cfg[client.env][client.app_name]
        yield int(base_url.split(":")[-1])


@pytest.fixture(scope="module")
def port(demo_app_server: DemoAppLifecycleManager, _default_port: int) -> int:
    if IS_TOX:
        assert demo_app_server.port is not None
        return demo_app_server.port
    else:
        return _default_port


@pytest.fixture(scope="module", autouse=True)
def demo_app_server(
    request: FixtureRequest, tmp_path_factory: TempPathFactory, _default_port: int
) -> Generator[DemoAppLifecycleManager]:
    port = None if IS_TOX else _default_port
    with DemoAppLifecycleManager(request, tmp_path_factory, port=port) as app_manager:
        yield app_manager


@pytest.fixture
def unauthenticated_api_client(port: int) -> Generator[DemoAppAPIClient]:
    with DemoAppAPIClient() as client:
        if IS_TOX:
            helper.update_client_base_url(client, port)
        yield client


@pytest.fixture(scope="module")
def api_client(port: int) -> Generator[DemoAppAPIClient]:
    with DemoAppAPIClient() as client:
        if IS_TOX:
            helper.update_client_base_url(client, port)
        r = client.Auth.login(username="foo", password="bar")
        assert r.ok
        yield client
        client.Auth.logout()


@pytest.fixture
def random_app_name() -> str:
    return f"app_{random.choice(range(1, 1000))}"


@pytest.fixture
def demo_app_openapi_spec_url(unauthenticated_api_client: DemoAppAPIClient) -> str:
    base_url = unauthenticated_api_client.base_url
    doc_path = unauthenticated_api_client.api_spec.doc_path
    return f"{base_url}/{doc_path}"


@pytest.fixture(scope="module")
def petstore_openapi_spec_url() -> str:
    """OpenAPI spec URL for petstore v3

    See https://petstore3.swagger.io/
    """
    url = "https://petstore3.swagger.io/api/v3/openapi.json"
    httpx.get(url).raise_for_status()
    return url


@pytest.fixture(
    params=[
        pytest.param(
            False, marks=pytest.mark.skipif(bool(os.environ.get("IS_TOX")), reason="Not supported in tox env")
        ),
        True,
    ]
)
def external_dir(request: SubRequest, random_app_name: str) -> Generator[Path | None, Any, None]:
    temp_dir_: Path | None = None
    if request.param:
        temp_dir_ = request.getfixturevalue(temp_dir.__name__)
        external_dir = temp_dir_ / "my_clients"
    else:
        external_dir = None

    yield external_dir

    if temp_dir_:
        shutil.rmtree(temp_dir_)
    else:
        client_dir = get_client_dir(random_app_name)
        assert client_dir.name == random_app_name
        if client_dir.exists():
            # For non dry-run test
            shutil.rmtree(client_dir)


@pytest.fixture
def temp_app_client(
    temp_dir: Path, mocker: MockerFixture, demo_app_openapi_spec_url: str, port: int
) -> Generator[OpenAPIClient, Any, None]:
    """Temporary demo app API client that will be generated for a test"""
    app_name = f"{DemoAppLifecycleManager.app_name}_{random.choice(range(1, 1000))}"
    module_dir = temp_dir / "my_clients"

    args = f"generate -u {demo_app_openapi_spec_url} -a {app_name} --dir {module_dir} --quiet"
    _, stderr = helper.run_command(args)
    assert not stderr, stderr

    # In real life the env var will be set inside the top-level module's __init__.py when accessing the library.
    # This is needed for the library to determine if the generated client is an external one.
    # To simulate this we set the env var in here before instantiating the client
    mocker.patch.dict(os.environ, {ENV_VAR_PACKAGE_DIR: str(module_dir)})

    client = OpenAPIClient.get_client(app_name)
    if IS_TOX:
        helper.update_client_base_url(client, port)
    yield client

    shutil.rmtree(temp_dir)


@pytest.fixture(autouse=True)
def _stream_cmd_output(request: FixtureRequest) -> None:
    os.environ["IS_CAPTURING_OUTPUT"] = str(request.config.option.capture != "no").lower()
