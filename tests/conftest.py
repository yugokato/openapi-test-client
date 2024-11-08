import os
import sys
from typing import Any

import pytest
from common_libs.utils import clean_obj_name
from pytest import Item, TempPathFactory
from pytest_mock import MockerFixture


def pytest_make_parametrize_id(val: Any, argname: str):
    return f"{argname}={repr(val)}"


def pytest_runtest_setup(item: Item):
    if item.config.option.capture == "no":
        # Improve the readability of console logs
        print()


@pytest.fixture(autouse=True)
def _mock_sys_path_and_modules(mocker: MockerFixture):
    """Mock sys.path and sys.modules

    Code generation tests will add sys.path and sys.modules. This mock will remove these added ones after
    each test so that a test won't interfere others
    """
    mocker.patch.object(sys, "path", sys.path.copy())
    mocker.patch.dict(sys.modules, sys.modules.copy())


@pytest.fixture
def temp_dir(tmp_path_factory: TempPathFactory):
    current_test_name = os.environ["PYTEST_CURRENT_TEST"].rsplit(" ", 1)[0]
    return tmp_path_factory.mktemp(clean_obj_name(current_test_name))
