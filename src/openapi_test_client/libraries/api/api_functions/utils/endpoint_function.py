from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import MISSING
from typing import TYPE_CHECKING, Any

from common_libs.ansi_colors import ColorCodes, color
from common_libs.clients.rest_client.utils import get_supported_request_parameters
from common_libs.logging import get_logger
from common_libs.utils import list_items
from pydantic import ValidationError

import openapi_test_client.libraries.api.api_functions.utils.param_type as param_type_util
from openapi_test_client.libraries.api.multipart_form_data import MultipartFormData
from openapi_test_client.libraries.api.types import Alias, File
from openapi_test_client.libraries.common.json_encoder import CustomJsonEncoder

if TYPE_CHECKING:
    from common_libs.clients.rest_client.ext import JSONType

    from openapi_test_client.libraries.api import Endpoint, EndpointFunc

logger = get_logger(__name__)


def validate_path_and_params(
    endpoint_func: EndpointFunc,
    *path_params: Any,
    validate: bool = False,
    raw_options: dict[str, Any] | None,
    **body_or_query_params: dict[str, Any],
) -> str:
    """Validate path parameters and body/query parameters for an endpoint function call, and returns completed
    endpoint path

    :param endpoint_func: Endpoint function obj
    :param path_params: Path variables to fill the endpoint
    :param validate: Whether to perform Pydantic validation in strict mode against parameters
    :param raw_options: Raw request options passed to the httpx client
    :param body_or_query_params: Body or query parameters for the endpoint
    """
    endpoint = endpoint_func.endpoint
    if endpoint.is_deprecated:
        logger.warning(f"DEPRECATED: '{endpoint}' is deprecated")

    # Fill path variables
    try:
        completed_path = _complete_endpoint(endpoint, path_params)
    except ValueError as e:
        msg = str(e)
        if api_spec_definition := endpoint_func.get_usage():
            msg = f"{e!s}\n{color(api_spec_definition, color_code=ColorCodes.YELLOW)}"
        raise ValueError(msg) from None

    # Check if parameters used are expected for the endpoint. If not, it is an indication that the API function is
    # not up-to-date unless they are invalid parameters intentionally specified. We will log a warning message for this
    # case
    _check_params(endpoint, body_or_query_params, raw_options=raw_options)

    if validate:
        # Perform Pydantic validation in strict mode against parameters
        try:
            _validate_params(endpoint, path_params, body_or_query_params)
        except ValidationError as e:
            raise ValueError(color(f"Request parameter validation failed.\n{e}", color_code=ColorCodes.RED)) from None

    return completed_path


def is_json_request(
    endpoint: Endpoint,
    params: dict[str, Any],
    raw_options: dict[str, Any],
    session_headers: dict[str, str],
) -> bool:
    """Check if the endpoint call requires a JSON request

    Endpoints that match either of the following criteria are considered as non JSON request
    - The endpoint model contains at least one File dataclass field
    - At least one parameter value is an instance of File (in case swagger docs are not correct)
    - Content-Type request/session header was explicitly specified as anything other than application/json
    - Then endpoint function is marked with @endpoint.content_header() with any value than application/json
    """
    model = endpoint.model
    has_file = any(
        param_type_util.is_type_of(field_obj.type, File) for (_, field_obj) in model.__dataclass_fields__.items()
    ) or any(isinstance(v, File) for v in params.values())
    if has_file:
        return False
    else:
        specified_content_type_header = _get_specified_content_type_header(raw_options, session_headers)
        if content_type := (specified_content_type_header or endpoint.content_type):
            return content_type.split(";")[0] == "application/json"
        else:
            # Our default is application/json
            return True


def generate_rest_func_params(
    endpoint: Endpoint,
    endpoint_params: dict[str, JSONType],
    session_headers: dict[str, str],
    quiet: bool = False,
    use_query_string: bool = False,
    is_validation_mode: bool = False,
    **raw_options: Any,
) -> dict[str, JSONType]:
    """Convert params passed to an endpoint function to ones for a low-level rest call function.
    Also set Content-Type header if needed

    :param endpoint: Endpoint obj
    :param endpoint_params: Params passed to an endpoint function call
    :param session_headers: Request client's session headers
    :param quiet: quiet flag passed to an endpoint function call
    :param use_query_string: Force sends parameters as query strings
    :param is_validation_mode: Whether this request is in validation mode or not
    :param raw_options: Raw request options passed to the httpx client
    """
    json_ = {}
    data = {}
    query_params = {}
    files: dict[str, str | bytes | File] | MultipartFormData
    if is_json := is_json_request(endpoint, endpoint_params, raw_options, session_headers):
        files = {}
    else:
        files = MultipartFormData()
    dataclass_fields = endpoint.model.__dataclass_fields__
    rest_func_params: dict[str, Any] = dict(quiet=quiet, **raw_options)
    specified_content_type_header = _get_specified_content_type_header(raw_options, session_headers)
    for param_name, param_value in endpoint_params.items():
        if param_name == "raw_options":
            for k, v in raw_options.items():
                rest_func_params[k] = v
        else:
            if field_obj := dataclass_fields.get(param_name):
                if param_type_util.matches_type(param_value, field_obj.type):
                    # Check if Annotate[] type definition with "query" and/or Alias metadata exists
                    if annotated_type := param_type_util.get_annotated_type(
                        field_obj.type, metadata_filter=["query", Alias]
                    ):
                        if isinstance(annotated_type, list | tuple):
                            # This field has more than one Annotated[] as a union. We will try to find the right one for
                            # this request where the type of the given param value matches.
                            try:
                                annotated_type = next(
                                    t for t in annotated_type if param_type_util.matches_type(param_value, t)
                                )
                                should_check_annotated_meta = True
                            except StopIteration:
                                should_check_annotated_meta = False
                        else:
                            should_check_annotated_meta = param_type_util.matches_type(param_value, annotated_type)

                        if should_check_annotated_meta:
                            # Process alias name and query parameter
                            metadata = annotated_type.__metadata__
                            if alias_param := [x for x in metadata if isinstance(x, Alias)]:
                                assert len(alias_param) == 1
                                # Resolve the actual param name
                                param_name = alias_param[0].value

                            if "query" in metadata:
                                query_params[param_name] = param_value

            if param_name not in query_params.keys():
                if use_query_string:
                    query_params[param_name] = param_value
                elif is_json:
                    json_[param_name] = param_value
                else:
                    if isinstance(param_value, File):
                        files[param_name] = param_value
                    elif (
                        param_type_util.is_type_of(dataclass_fields.get(param_name).type, File)
                        and not specified_content_type_header
                    ):
                        # The parameter is annotated as File type, but the user gave something else. As long as
                        # Content-Type header is not explicitly given, we still assume the given value is for
                        # file uploading. The value may a File obj but in a dictionary, or might be just a file
                        # content in str/bytes. Otherwise, the underlying HTTP library might throw an error
                        files[param_name] = param_value
                    else:
                        data[param_name] = param_value

    if json_:
        if is_validation_mode:
            json_ = json.loads(json.dumps(json_, cls=CustomJsonEncoder))
        rest_func_params["json"] = json_
    if data:
        if is_validation_mode:
            data = json.loads(json.dumps(data, cls=CustomJsonEncoder))
        rest_func_params["data"] = data
    if query_params:
        rest_func_params["params"] = query_params
    if isinstance(files, MultipartFormData) and (file_data := files.to_dict()):
        rest_func_params["files"] = file_data

    # httpx lib will not automatically set Content-Type header if the `data` value is string or bytes.
    # We will set the Content-type value using from the OpenAPI specs for this case, unless the header is explicitly
    # set by a user. Otherwise, httpx lib will automatically handle this part
    if (
        (rest_data := rest_func_params.get("data"))
        and isinstance(rest_data, str | bytes)
        and not specified_content_type_header
        and endpoint.content_type
    ):
        rest_func_params.setdefault("headers", {}).update({"Content-Type": endpoint.content_type})

    return rest_func_params


def _check_params(endpoint: Endpoint, params: dict[str, Any], raw_options: dict[str, Any] | None = None) -> None:
    """Check the endpoint parameters

     A warning message will be logged if any of the following condition matches:
    - One or more unexpected (either unsupported, or API function def is old) parameters were given
    - One or more parameters are deprecated

    :param endpoint: Endpoint obj
    :param params: Request parameters
    :param raw_options: Raw request options passed to the httpx client
    """
    if raw_options:
        allowed_raw_options = get_supported_request_parameters()
        unexpected_raw_options = set((raw_options or {}).keys()).difference(allowed_raw_options)
        if unexpected_raw_options:
            raise RuntimeError(f"Invalid raw option(s):\n{list_items(unexpected_raw_options)}")

    if endpoint.is_documented:
        dataclass_fields = endpoint.model.__dataclass_fields__
        expected_params = set(dataclass_fields.keys())
        unexpected_params = set(params.keys()).difference(expected_params)
        if unexpected_params:
            msg = (
                f"The request contains one or more parameters "
                f"{endpoint.api_class.__name__}.{endpoint.func_name}() does not expect:\n"
                f"{list_items(unexpected_params)}"
            )
            logger.warning(msg)

        for param_name in params.keys():
            if param_name in dataclass_fields and param_type_util.is_deprecated_param(
                dataclass_fields[param_name].type
            ):
                logger.warning(f"DEPRECATED: parameter '{param_name}' is deprecated")


def _validate_params(endpoint: Endpoint, path_params: tuple[Any, ...], body_or_query_params: dict[str, Any]) -> None:
    """Perform Pydantic validation in strict mode

    Both endpoint parameters and param models (nested ones too) will be validated.

    NOTE: Validation will be done against the json data to allow some alternative types (eg. UUID v.s. string) while
          been strict for most cases.
          See: https://docs.pydantic.dev/latest/concepts/strict_mode/#type-coercions-in-strict-mode

    :param endpoint: Endpoint obj
    :param path_params: Request path parameters
    :param body_or_query_params: Request body or query parameters
    """
    path_param_names = (k for k, v in endpoint.model.__dataclass_fields__.items() if v.default is MISSING)
    path_params_ = OrderedDict(zip(path_param_names, path_params))
    PydanticEndpointModel = endpoint.model.to_pydantic()
    PydanticEndpointModel.validate_as_json({**path_params_, **body_or_query_params})


def _complete_endpoint(endpoint: Endpoint, path_params: tuple[str, ...], as_url: bool = False) -> str:
    """Complete endpoint path with given path variables

    :param endpoint: Endpoint obj
    :param path_params: Path variables to fill the endpoint
    :param as_url: Return URL
    """

    if path_placeholders := re.findall(r"{([^}]+)}", endpoint.path):
        if len(path_params) == len(path_placeholders):
            fmt = OrderedDict(zip(path_placeholders, path_params))
            completed_path = endpoint.path.format(**fmt)
            completed_url = endpoint.url.format(**fmt)
        else:
            if len(path_params) < len(path_placeholders):
                # One or more path variables are missing
                missing_args = path_placeholders[len(path_params) :]
                missing_args_str = ", ".join(repr(arg) for arg in missing_args)
                msg = (
                    f"{endpoint.func_name}() missing {len(missing_args)} required path "
                    f"parameter{'s' if len(missing_args) > 1 else ''}: {missing_args_str}"
                )
                raise ValueError(msg)
            else:
                # One or more extra path variables were provided
                extra_args = path_params[len(path_placeholders) :]
                extra_args_str = ", ".join(repr(arg) for arg in extra_args)
                msg = (
                    f"{endpoint.func_name}() received unexpected {len(extra_args)} extra path "
                    f"parameter{'s' if len(extra_args) > 1 else ''}: {extra_args_str}"
                )
                raise ValueError(msg)
    else:
        completed_path = endpoint.path
        completed_url = endpoint.url

    if as_url:
        return completed_url
    else:
        return completed_path


def _get_specified_content_type_header(raw_options: dict[str, Any], session_headers: dict[str, str]) -> str | None:
    """Get Content-Type header value set for the request or for the current session"""
    request_headers = raw_options.get("headers", {})
    content_type_header = (
        request_headers.get("Content-Type")
        or request_headers.get("content-type")
        or session_headers.get("Content-Type")
        or session_headers.get("content-type")
    )
    return content_type_header
