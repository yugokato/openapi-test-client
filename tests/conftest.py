import os
import sys
from pathlib import Path
from typing import Any

import pytest
from common_libs.utils import clean_obj_name
from pytest import Item, TempPathFactory
from pytest_mock import MockerFixture

from openapi_test_client.libraries.api.types import File


def pytest_make_parametrize_id(val: Any, argname: str) -> str:
    return f"{argname}={val!r}"


def pytest_runtest_setup(item: Item) -> None:
    if item.config.option.capture == "no":
        # Improve the readability of console logs
        sys.stdout.write("\n")


@pytest.fixture(autouse=True)
def _mock_sys_path_and_modules(mocker: MockerFixture) -> None:
    """Mock sys.path and sys.modules

    Code generation tests will add sys.path and sys.modules. This mock will remove these added ones after
    each test so that a test won't interfere others
    """
    mocker.patch.object(sys, "path", sys.path.copy())
    mocker.patch.dict(sys.modules, sys.modules.copy())


@pytest.fixture
def temp_dir(tmp_path_factory: TempPathFactory) -> Path:
    current_test_name = os.environ["PYTEST_CURRENT_TEST"].rsplit(" ", 1)[0]
    return tmp_path_factory.mktemp(clean_obj_name(current_test_name))


@pytest.fixture(scope="session")
def image_data() -> bytes:
    return (  # https://evanhahn.com/worlds-smallest-png/
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x01\x00\x00\x00\x007n\xf9$\x00\x00\x00\nIDATx"
        b"\x01c`\x00\x00\x00\x02\x00\x01su\x01\x18\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.fixture(scope="session")
def image_file(image_data: bytes) -> File:
    return File(filename="test_image.png", content=image_data, content_type="image/png")
