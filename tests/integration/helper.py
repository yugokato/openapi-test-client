from __future__ import annotations

import shlex
import subprocess
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import EndpointFunc


def run_command(args: str) -> tuple[str, str]:
    """Run openapi-client command with given command args"""
    cmd = f"openapi-client {args}"
    print(f"Running command: {cmd}")
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    stdout, stderr = proc.communicate()
    print(stdout)
    return stdout, stderr


def do_test_invalid_params(
    *,
    endpoint_func: EndpointFunc,
    validation_mode: bool,
    invalid_params: dict[str, Any],
    num_expected_errors: int,
):
    """Test the endpoint with invalid parameters

    When validation mode is enabled, the client side should raise ValueError.
    When validation mode is not enabled, the server side should return a validation error
    (unless should_server_side_is_accepted=True is given).
    """
    with pytest.raises(ValueError) if validation_mode else nullcontext() as e:
        r = endpoint_func(**invalid_params, validate=validation_mode)

    if validation_mode:
        print(e.value)
        assert (
            f"Request parameter validation failed.\n"
            f"{num_expected_errors} validation error{'s' if num_expected_errors > 1 else ''} for "
            f"{endpoint_func.endpoint.model.__name__}" in str(e.value)
        )
    else:
        assert r.status_code == 400
        assert len(r.response["error"]["message"]) == num_expected_errors
