from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import TYPE_CHECKING, Annotated, Any, Optional, get_args, get_origin

from common_libs.clients.rest_client.utils import get_supported_request_parameters
from common_libs.logging import get_logger
from common_libs.utils import list_items

import openapi_test_client.libraries.api.api_functions.utils.param_type as param_type_util
from openapi_test_client.libraries.api.multipart_form_data import MultipartFormData
from openapi_test_client.libraries.api.types import Alias, File
from openapi_test_client.libraries.common.json_encoder import CustomJsonEncoder

if TYPE_CHECKING:
    from common_libs.clients.rest_client.ext import JSONType

    from openapi_test_client.libraries.api import Endpoint

logger = get_logger(__name__)


def check_params(endpoint: Endpoint, params: dict[str, Any]):
    """Check the endpoint parameters

     A warning message will be logged if any of the following condition matches:
    - One or more unexpected (either unsupported, or API function def is old) parameters were given
    - One or more parameters are deprecated

    :param endpoint: Endpoint obj
    :param params: Request parameters
    """
    if endpoint.is_documented:
        dataclass_fields = endpoint.model.__dataclass_fields__
        expected_params = set(list(dataclass_fields.keys()) + get_supported_request_parameters())
        unexpected_params = set(params.keys()).difference(expected_params)
        if unexpected_params:
            msg = (
                f"The request contains one or more parameters "
                f"{endpoint.api_class.__name__}.{endpoint.func_name}() does not expect:\n{list_items(unexpected_params)}"
            )
            logger.warning(msg)

        for param_name in params.keys():
            if param_name in dataclass_fields and param_type_util.is_deprecated_param(
                dataclass_fields[param_name].type
            ):
                logger.warning(f"DEPRECATED: parameter '{param_name}' is deprecated")


def validate_params(endpoint: Endpoint, params: dict[str, Any]):
    """Perform Pydantic validation in strict mode

    Both endpoint parameters and param models (nested ones too) will be validated.

    NOTE: Validation will be done against the json data to allow some alternative types (eg. UUID v.s. string) while
          been strict for most cases.
          See: https://docs.pydantic.dev/latest/concepts/strict_mode/#type-coercions-in-strict-mode

    :param endpoint: Endpoint obj
    :param params: Request parameters
    """
    PydanticEndpointModel = endpoint.model.to_pydantic()
    PydanticEndpointModel.validate_as_json(params)


def complete_endpoint(endpoint: Endpoint, path_params: tuple[str, ...], as_url: bool = False):
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


def is_json_request(
    endpoint: Endpoint, params: dict[str, Any], requests_lib_options: dict[str, Any], session_headers: dict[str, str]
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
        specified_content_type_header = _get_specified_content_type_header(requests_lib_options, session_headers)
        if content_type := (specified_content_type_header or endpoint.content_type):
            return content_type.split(";")[0] == "application/json"
        else:
            # Our default is application/json
            return True


def generate_rest_func_params(
    endpoint: Endpoint,
    endpoint_params: dict[str, JSONType],
    session_headers: dict[str, str] = None,
    quiet: bool = False,
    use_query_string: bool = False,
    is_validation_mode: bool = False,
    **requests_lib_options,
) -> dict[str, JSONType]:
    """Convert params passed to an endpoint function to ones for a low-level rest call function.
    Also set Content-Type header if needed

    :param endpoint: Endpoint obj
    :param endpoint_params: Params passed to an endpoint function call
    :param session_headers: Request client's session headers
    :param quiet: quiet flag passed to an endpoint function call
    :param use_query_string: Force sends parameters as query strings
    :param is_validation_mode: Whether this request is in validation mode or not
    :param requests_lib_options: Raw options for the requests library
    """
    json_ = {}
    data = {}
    query = {}
    if is_json := is_json_request(endpoint, endpoint_params, requests_lib_options, session_headers):
        files = {}
    else:
        files = MultipartFormData()
    dataclass_fields = endpoint.model.__dataclass_fields__
    rest_func_params: dict[str, Any] = dict(quiet=quiet, **requests_lib_options)
    specified_content_type_header = _get_specified_content_type_header(requests_lib_options, session_headers)
    for param_name, param_value in endpoint_params.items():
        if param_name in ["json", "data", "files"]:
            rest_func_params[param_name] = param_value
        else:
            if field_obj := dataclass_fields.get(param_name):
                # Check Annotated metadata
                if param_type_util.is_optional_type(field_obj.type):
                    # If Optional[Annotated[]], Annotated is the first arg
                    field_type = get_args(field_obj.type)[0]
                else:
                    field_type = field_obj.type

                if get_origin(field_type) is Annotated:
                    # Process alias name and query parameter
                    metadata = field_type.__metadata__
                    if alias_param := [x for x in metadata if isinstance(x, Alias)]:
                        assert len(alias_param) == 1
                        # Resolve the actual param name
                        param_name = alias_param[0].value

                    if "query" in metadata:
                        query[param_name] = param_value

            if param_name not in query.keys():
                if use_query_string:
                    query[param_name] = param_value
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
                        # content in str/bytes. Otherwise requests lib might throw an error
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
    if query:
        rest_func_params["query"] = query
    if isinstance(files, MultipartFormData) and (file_data := files.to_dict()):
        rest_func_params["files"] = file_data

    # requests lib will not automatically set Content-Type header if the `data` value is string or bytes.
    # We will set the Content-type value using from the OpenAPI specs for this case, unless the header is explicitly
    # set by a user. Otherwise, requests lib will automatically handle this part
    if (data := rest_func_params.get("data")) and (
        isinstance(data, (str, bytes)) and not specified_content_type_header and endpoint.content_type
    ):
        rest_func_params.setdefault("headers", {}).update({"Content-Type": endpoint.content_type})

    return rest_func_params


def _get_specified_content_type_header(
    requests_lib_options: dict[str, Any], session_headers: dict[str, str]
) -> Optional[str]:
    """Get Content-Type header value set for the request or for the current session"""
    request_headers = requests_lib_options.get("headers", {})
    content_type_header = (
        request_headers.get("Content-Type")
        or request_headers.get("content-typ")
        or session_headers.get("Content-Type")
        or session_headers.get("content-type")
    )
    return content_type_header
