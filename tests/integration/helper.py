from __future__ import annotations

import os
import shlex
import subprocess
import sys
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

import pytest
from common_libs.logging import get_logger

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import EndpointFunc


logger = get_logger("openapi_test_client")


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
