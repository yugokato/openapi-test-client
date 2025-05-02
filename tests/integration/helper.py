from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any, Self

import pytest
import requests
from common_libs.network import is_port_in_use
from common_libs.utils import wait_until
from filelock import FileLock
from pytest import TempPathFactory
from requests.exceptions import ConnectionError

from openapi_test_client import _CONFIG_DIR, _PACKAGE_DIR, logger

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import EndpointFunc


URL_CONFIG_PATH = _CONFIG_DIR / "urls.json"


class DemoAppLifecycleManager:
    """Demo app manager that handles the lifecycle of demo app

    This also handles parallel testing using pyest-xdist to make sure only one worker starts/stops the app
    """

    app_name = "demo_app"

    def __init__(self, tmp_path_factory: TempPathFactory):
        if os.environ.get("IS_TOX"):
            self.port = int(os.environ["APP_PORT"])
        else:
            self.port = int(self.base_url.split(":")[-1])
        self.tmp_path_factory = tmp_path_factory
        self.worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
        self.proc: subprocess.Popen | None = None
        if self.is_xdist:
            xdist_run_uuid = os.environ["PYTEST_XDIST_TESTRUNUID"]
            self.xdist_session_dir = self.tmp_path_factory.getbasetemp().parent / xdist_run_uuid
            with FileLock(self.xdist_session_dir / "check_num_workers.lock"):
                self.xdist_session_dir.mkdir(exist_ok=True)
                (self.xdist_session_dir / self.worker_id).touch()
                self.is_starter = self.get_num_active_workers() == 1
        else:
            self.xdist_session_dir = None
            self.is_starter = True

    def __enter__(self) -> Self:
        if self.is_starter:
            try:
                self.start_app()
                if os.environ.get("IS_TOX"):
                    # For tox parallel testing, modify the original URL config to match with the actual app port
                    if not self.base_url.endswith(f":{self.port}"):
                        url_cfg = json.loads(URL_CONFIG_PATH.read_text())
                        url_cfg["dev"][self.app_name] = re.sub(r"(.+):\d+", rf"\1:{self.port}", self.base_url)
                        URL_CONFIG_PATH.write_text(json.dumps(url_cfg))
            except Exception:
                self.stop_app()
                raise
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if self.is_xdist:
                (self.xdist_session_dir / self.worker_id).unlink()
                if self.is_starter:
                    self.wait_for_all_workers_to_complete()
        finally:
            self.stop_app()

    @property
    def is_xdist(self) -> bool:
        return self.worker_id.startswith("gw")

    @property
    def base_url(self) -> str:
        url_cfg = json.loads(URL_CONFIG_PATH.read_text())
        return url_cfg["dev"][DemoAppLifecycleManager.app_name]

    def start_app(self) -> None:
        script_path = _PACKAGE_DIR.parent / self.app_name / "main.py"
        args = ["python", str(script_path), "-p", str(self.port)]
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
        ret_code = self.proc.poll()
        if ret_code:
            logger.error(self.proc.stderr.read())
        assert not ret_code, self.proc.stdout.read()

    def stop_app(self) -> None:
        if self.proc:
            logger.warning("Stopping the app...")
            self.proc.terminate()
            stdout, stderr = self.proc.communicate()
            logger.info(f"App logs:\n{stderr or stdout}")

    def get_num_active_workers(self) -> int:
        return len([f for f in self.xdist_session_dir.iterdir() if f.name.startswith("gw")])

    def wait_for_app_to_start(self) -> None:
        logger.warning(f"Waiting for the app to start with port {self.port}...")
        wait_until(is_port_in_use, func_args=(self.port,), stop_condition=lambda x: x is True, timeout=5)

    def wait_for_app_ready(self) -> None:
        def is_app_ready() -> bool:
            try:
                return requests.get(self.base_url).ok
            except ConnectionError:
                return False

        self.wait_for_app_to_start()
        logger.warning("Waiting for app to become ready...")
        wait_until(is_app_ready, stop_condition=lambda x: x is True, interval=1, timeout=5)

    def wait_for_all_workers_to_complete(self, timeout: float = 60 * 60) -> None:
        logger.warning("Waiting for all xdist workers to complete tests...")
        wait_until(self.get_num_active_workers, stop_condition=lambda x: x == 0, timeout=timeout)
        logger.warning("All xdist workers completed tests")


def run_command(args: str) -> tuple[str, str]:
    """Run openapi-client command with given command args"""
    cmd = f"openapi-client {args}"
    logger.info(f"Running command: {cmd}")
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    if os.environ["IS_CAPTURING_OUTPUT"] == "true":
        stdout, stderr = proc.communicate()
        print(stdout)  # noqa: T201
        # if stderr:
        #     print(stderr)
        return stdout, stderr
    else:
        return stream_output(proc)


def stream_output(proc: subprocess.Popen) -> tuple[str, str]:
    stdout_lines = []
    stderr_lines = []
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        stdout_lines.append(line)

    for line in proc.stderr:
        # sys.stderr.write(line)
        # sys.stderr.flush()
        stderr_lines.append(line)

    proc.wait()
    return "".join(stdout_lines), "".join(stderr_lines)


def do_test_invalid_params(
    *,
    endpoint_func: EndpointFunc,
    validation_mode: bool,
    invalid_params: dict[str, Any],
    num_expected_errors: int,
) -> None:
    """Test the endpoint with invalid parameters

    When validation mode is enabled, the client side should raise ValueError.
    When validation mode is not enabled, the server side should return a validation error
    (unless should_server_side_is_accepted=True is given).
    """
    with pytest.raises(ValueError) if validation_mode else nullcontext() as e:
        r = endpoint_func(**invalid_params, validate=validation_mode)

    if validation_mode:
        print(e.value)  # noqa: T201
        assert (
            f"Request parameter validation failed.\n"
            f"{num_expected_errors} validation error{'s' if num_expected_errors > 1 else ''} for "
            f"{endpoint_func.endpoint.model.__name__}" in str(e.value)
        )
    else:
        assert r.status_code == 400
        assert len(r.response["error"]["message"]) == num_expected_errors
