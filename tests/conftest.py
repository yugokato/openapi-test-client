import json
import os
import random
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest
import requests
from _pytest.fixtures import SubRequest
from pytest import Config, Item

from openapi_test_client import _CONFIG_DIR, _PACKAGE_DIR, ENV_VAR_PACKAGE_DIR, logger
from openapi_test_client.clients import OpenAPIClient
from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.libraries.api.api_client_generator import get_client_dir
from openapi_test_client.libraries.api.types import ParamModel
from tests import helper


def pytest_make_parametrize_id(config: Config, val, argname):
    return f"{argname}={val}"


def pytest_runtest_setup(item: Item):
    if item.config.option.capture == "no":
        # Improve the readability of console logs
        print()


@pytest.fixture(scope="session", autouse=True)
def demo_app_server():
    script_path = _PACKAGE_DIR.parent / "demo_app" / "main.py"
    proc = subprocess.Popen(
        ["python", str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    time.sleep(2)
    if proc.poll():
        logger.error(proc.stderr.read())
    assert not proc.poll(), proc.stdout.read()
    yield
    proc.terminate()
    stdout, stderr = proc.communicate()
    logger.info(f"Server logs:\n{stderr or stdout}")


@pytest.fixture
def unauthenticated_api_client() -> DemoAppAPIClient:
    return DemoAppAPIClient()


@pytest.fixture(scope="session")
def api_client(demo_app_server) -> DemoAppAPIClient:
    client = DemoAppAPIClient()
    r = client.AUTH.login(username="foo", password="bar")
    assert r.ok
    yield client
    client.AUTH.logout()


@pytest.fixture
def random_app_name() -> str:
    return f"app_{random.choice(range(1,1000))}"


@pytest.fixture
def demo_app_openapi_spec_url(unauthenticated_api_client) -> str:
    url_cfg = json.loads((_CONFIG_DIR / "urls.json").read_text())
    base_url = url_cfg[unauthenticated_api_client.env][unauthenticated_api_client.app_name]
    doc_path = unauthenticated_api_client.api_spec.doc_path
    return f"{base_url}/{doc_path}"


@pytest.fixture(scope="session")
def petstore_openapi_spec_url() -> str:
    """OpenAPI spec URL for petstore v3

    See https://petstore3.swagger.io/
    """
    url = "https://petstore3.swagger.io/api/v3/openapi.json"
    requests.get(url).raise_for_status()
    return url


@pytest.fixture(params=[False, True])
def external_dir(request: SubRequest, random_app_name) -> Optional[Path]:
    temp_dir: Optional[Path] = None
    if request.param:
        temp_dir = request.getfixturevalue("tmp_path")
        external_dir = temp_dir / "my_clients"
    else:
        external_dir = None

    yield external_dir

    if temp_dir:
        shutil.rmtree(temp_dir)
    else:
        client_dir = get_client_dir(random_app_name)
        assert client_dir.name == random_app_name
        if client_dir.exists():
            # For non dry-run test
            shutil.rmtree(client_dir)


@pytest.fixture
def temp_app_client(tmp_path_factory, demo_app_openapi_spec_url):
    """Temporary demo app API client that will be generated for a test"""
    app_name = f"demo_app_{random.choice(range(1,1000))}"
    temp_dir = tmp_path_factory.mktemp("MyPackage")
    module_dir = temp_dir / "my_clients"
    args = f"generate -u {demo_app_openapi_spec_url} -a {app_name} --dir {module_dir} --quiet"
    _, stderr = helper.run_command(args)
    if stderr:
        print(stderr)
    assert not stderr

    # In real life the env var will be set inside the top-level module's __init__.py when accessing the library.
    # This is needed for the library to determine if the generated client is an external one.
    # To simulate this we set the env var in here before instantiating the client
    os.environ[ENV_VAR_PACKAGE_DIR] = str(module_dir)

    yield OpenAPIClient.get_client(app_name)

    os.environ.pop(ENV_VAR_PACKAGE_DIR, None)
    shutil.rmtree(temp_dir)


@pytest.fixture(scope="session")
def EmptyParamModel():
    @dataclass
    class Model(ParamModel):
        ...

    return Model


@pytest.fixture(scope="session")
def RegularParamModel(InnerParamModel):
    @dataclass
    class Model(ParamModel):
        param1: str = ...
        param2: str = ...
        param3: InnerParamModel = ...

    return Model


@pytest.fixture(scope="session")
def InnerParamModel():
    @dataclass
    class Model(ParamModel):
        inner_param1: str = ...
        inner_param2: str = ...

    return Model
