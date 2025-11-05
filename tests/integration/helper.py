from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import weakref
from contextlib import nullcontext
from functools import cached_property, wraps
from typing import TYPE_CHECKING, Any, Self

import pytest
import requests
from common_libs.decorators import singleton
from common_libs.lock import Lock
from common_libs.network import find_open_port, is_port_in_use
from common_libs.utils import wait_until
from pytest import FixtureRequest, TempPathFactory
from requests.exceptions import ConnectionError

from openapi_test_client import _CONFIG_DIR, logger
from openapi_test_client.clients.base import OpenAPIClient
from openapi_test_client.clients.demo_app import DemoAppAPIClient

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import EndpointFunc


URL_CONFIG_PATH = _CONFIG_DIR / "urls.json"


@singleton
class DemoAppPortManager(Lock):
    """Demo app port manager."""

    @wraps(Lock.__init__)
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.port_file = self._lock_file.parent / f"{self.name}.json"
        weakref.finalize(self, self._cleanup)

    def assign_port(self) -> int:
        with self:
            port = None
            if self.port_file.exists():
                port = json.loads(self.port_file.read_text())
            if not port:
                port = find_open_port()
                self.port_file.write_text(json.dumps(port))
        return int(port)

    def _cleanup(self) -> None:
        self.port_file.unlink(missing_ok=True)


class DemoAppLifecycleManager:
    """Demo app manager that handles the lifecycle of demo app

    If port is not explicitly given, it will dynamically find an open port, or reuse the existing one for the same
    identifier.
    This also handles parallel testing using pyest-xdist to make sure only one worker starts/stops the app
    """

    app_name = "demo_app"

    def __init__(
        self,
        request: FixtureRequest,
        tmp_path_factory: TempPathFactory,
        host: str = "127.0.0.1",
        port: int | None = None,
    ):
        self._request = request
        self.host = host
        self.port = port
        self.tmp_path_factory = tmp_path_factory
        self.test_session_id = os.environ["CURRENT_TEST_SESSION_UUID"]
        self.worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
        self.proc: subprocess.Popen | None = None
        self.port_manager = None
        if self.is_xdist:
            with Lock("check_num_workers"):
                xdist_run_uuid = os.environ["PYTEST_XDIST_TESTRUNUID"]
                self.xdist_session_dir = (
                    self.tmp_path_factory.getbasetemp().parent / xdist_run_uuid / str(port or self.identifier)
                )
                if not self.xdist_session_dir.exists():
                    self.xdist_session_dir.mkdir(parents=True, exist_ok=True)
                (self.xdist_session_dir / self.worker_id).touch()
                self.is_starter = self.get_num_active_workers() == 1
        else:
            self.xdist_session_dir = None
            self.is_starter = True

    def __enter__(self) -> Self:
        with Lock("start_demo_app"):
            if self.port is None:
                self.port_manager = DemoAppPortManager(self.identifier)
                self.port = self.port_manager.assign_port()
            if self.is_starter:
                try:
                    self._start_app()
                except Exception:
                    self.stop_app()
                    raise
            self._wait_for_app_to_start()
        self._wait_for_app_ready()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if self.is_xdist:
                (self.xdist_session_dir / self.worker_id).unlink()
                if self.is_starter:
                    self._wait_for_all_workers_to_complete()
        finally:
            self.stop_app()

    @cached_property
    def identifier(self) -> str:
        """App identifier that is unique per test session and the fixture request scope"""
        request_scope = self._request.scope or "function"
        if self._request.scope == "function":
            return f"{self.test_session_id}-{self._request.function.__name__}"
        elif self._request.scope == "module":
            return f"{self.test_session_id}-{self._request.module.__name__}"
        elif self._request.scope == "session":
            return self.test_session_id
        else:
            raise NotImplementedError(f"Unsupported request scope {request_scope}")

    @property
    def is_xdist(self) -> bool:
        return self.worker_id.startswith("gw")

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _start_app(self) -> None:
        args = ["quart", "-A", self.app_name, "run", "--host", self.host, "--port", str(self.port)]
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
            logger.info("Stopping the app...")
            self.proc.terminate()
            stdout, stderr = self.proc.communicate()
            logger.info(f"App logs:\n{stderr or stdout}")

    def get_num_active_workers(self) -> int:
        return len([f for f in self.xdist_session_dir.iterdir() if f.name.startswith("gw")])

    def _wait_for_app_to_start(self) -> None:
        logger.info(f"Waiting for the app to start on {self.host}:{self.port}...")
        wait_until(
            is_port_in_use,
            func_args=(self.port,),
            func_kwargs={"host": self.host},
            stop_condition=lambda x: x is True,
            interval=0.5,
            timeout=10,
        )

    def _wait_for_app_ready(self) -> None:
        def is_app_ready() -> bool:
            try:
                return requests.get(self.base_url).ok
            except ConnectionError:
                return False

        logger.info("Waiting for app to become ready...")
        wait_until(is_app_ready, stop_condition=lambda x: x is True, interval=0.5, timeout=10)

    def _wait_for_all_workers_to_complete(self, timeout: float = 60 * 60) -> None:
        logger.info("Waiting for all xdist workers to complete tests...")
        wait_until(self.get_num_active_workers, stop_condition=lambda x: x == 0, timeout=timeout)
        logger.info("All xdist workers completed tests")


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


def update_client_base_url(client: OpenAPIClient | DemoAppAPIClient, port: int) -> None:
    base_url = client.base_url
    client.base_url = re.sub(r"(.+):\d+", rf"\1:{port}", base_url)
