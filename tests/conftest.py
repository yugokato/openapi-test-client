import os
import sys
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

import pytest
from common_libs.ansi_colors import ColorCodes
from common_libs.utils import clean_obj_name, log_section
from pytest import Config, Item, Session, Subtests, TempPathFactory
from pytest_mock import MockerFixture
from xdist import is_xdist_worker

from openapi_test_client.libraries.core.types import File


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: Config) -> None:
    # --log-level (Avoid showing logs in "Captured log" section since our logging uses stdout)
    config.option.log_level = "99"


def pytest_make_parametrize_id(val: Any, argname: str) -> str:
    return f"{argname}={val!r}"


def pytest_sessionstart(session: Session) -> None:
    if not is_xdist_worker(session) and not session.config.option.collectonly:
        os.environ["CURRENT_TEST_SESSION_UUID"] = str(uuid.uuid4())


def pytest_runtest_setup(item: Item) -> None:
    if item.config.option.capture == "no":
        # Improve the readability of console logs
        sys.stdout.write("\n")


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish() -> None:
    _patch_pytest_logging_issue()


@pytest.fixture
def subtests(subtests: Subtests) -> Generator[Subtests]:
    """Add section logging to Pytest's subtests fixture"""

    def monkey_patch_subtest(f: Callable[..., Any]) -> Callable[..., Any]:
        @contextmanager
        @wraps(f)
        def wrapper(msg: str | None = None, **kwargs: Any) -> Generator[None]:
            with f(**kwargs):
                if msg is not None:
                    log_section(f"[subtest] {msg}", sub_section=True, color_code=ColorCodes.LIGHT_BLUE)
                yield

        return wrapper

    subtests.test = monkey_patch_subtest(subtests.test)
    yield subtests


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


def _patch_pytest_logging_issue() -> None:
    """Patch logging issue caused by pytest issue#5502 (https://github.com/pytest-dev/pytest/issues/5502)

    Pytest hijacks sys.stdout and replaces it with buffer (FileIO) when --capture=no or -s is not used, and closes
    it at the end. This implementation causes an issue where the stdout used by logging is also replaced by pytest,
    and "ValueError: I/O operation on closed file" error occurs when logging message is emit after the replaced stdout
    has been closed.
    """

    import logging

    loggers = [logging.getLogger(), *list(logging.Logger.manager.loggerDict.values())]
    for logger in loggers:
        if not hasattr(logger, "handlers"):
            continue
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def _mock_sys_path_and_modules(mocker: MockerFixture) -> None:
    """Mock sys.path and sys.modules

    Code generation tests will add sys.path and sys.modules. This mock will remove these added ones after
    each test so that a test won't interfere others
    """
    mocker.patch.object(sys, "path", sys.path.copy())
    mocker.patch.dict(sys.modules, sys.modules.copy())
