from __future__ import annotations

import inspect
import re
from collections import OrderedDict
from collections.abc import Callable
from functools import cache
from typing import TYPE_CHECKING, Any

from common_libs.clients.rest_client.utils import get_supported_request_parameters
from common_libs.logging import get_logger
from common_libs.utils import list_items

from ..types import Alias, File, MultipartFormData, Query, Unset
from . import param_type as param_type_util
from .endpoint_model import clean_model_field_name

if TYPE_CHECKING:
    from .. import Endpoint, EndpointFunc

logger = get_logger(__name__)


@cache
def get_path_placeholders(path: str) -> tuple[str, ...]:
    """Return the ordered path placeholder names extracted from the endpoint path.

    :param path: Endpoint path (e.g. "/users/{user_id}/orders/{order-id}")
    """
    return tuple(re.findall(r"{([^}]+)}", path))


@cache
def get_path_param_lookup(path: str) -> dict[str, str]:
    """Return a mapping from each possible caller-facing name to its original placeholder.

    For a valid-identifier placeholder like `{user_id}`, maps `user_id` to `user_id`.
    For a non-identifier placeholder like `{customer-id}`, maps both `customer-id` to `customer-id` and
    `customer_id` to `customer-id`, since callers may pass either form.

    :param path: Endpoint path
    """
    lookup: dict[str, str] = {}
    for ph in get_path_placeholders(path):
        lookup[ph] = ph
        if not ph.isidentifier():
            lookup.setdefault(clean_model_field_name(ph), ph)
    return lookup


@cache
def get_path_param_names(path: str) -> frozenset[str]:
    """Return the Python-level name for each path placeholder.

    For valid-identifier placeholders (e.g. `{user_id}`), the name is the placeholder
    itself. For non-identifier placeholders (e.g. `{customer-id}`), the cleaned
    equivalent (`customer_id`) is returned — no Python parameter can be named
    `customer-id`.

    :param path: Endpoint path
    """
    return frozenset(ph if ph.isidentifier() else clean_model_field_name(ph) for ph in get_path_placeholders(path))


@cache
def get_params_signature(func: Callable[..., Any]) -> inspect.Signature:
    """Return the given function's signature with `self` removed.

    :param func: Original API function
    """
    sig = inspect.signature(func)
    return sig.replace(parameters=[p for n, p in sig.parameters.items() if n != "self"])


def split_params(
    path: str, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split positional and keyword arguments into path parameters and body/query parameters.

    Categorization is based on whether the parameter name matches a `{placeholder}` token in
    the endpoint path. Non-Python-identifier placeholders (e.g. `{customer-id}`) are matched
    against their cleaned equivalent (`customer_id`). Path-parameter defaults are applied when
    the caller omits them; body/query defaults are left to `get_signature_defaults()` so hook
    contracts remain unchanged.

    :param path: Endpoint path
    :param func: Original API function
    :param args: Positional arguments from the endpoint call
    :param kwargs: Keyword arguments from the endpoint call
    """
    sig = get_params_signature(func)
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError as e:
        raise TypeError(f"{func.__name__}(): {e}") from None

    var_kw_name = next((n for n, p in sig.parameters.items() if p.kind == inspect.Parameter.VAR_KEYWORD), None)
    named: dict[str, Any] = {}
    for name, value in bound.arguments.items():
        if name == var_kw_name:
            named.update(value)
        else:
            named[name] = value

    path_params_dict: dict[str, Any] = {}
    for lookup_name, original_ph in get_path_param_lookup(path).items():
        if original_ph in path_params_dict:
            continue  # already resolved via a higher-priority match
        # An explicitly given Unset means "not provided" and falls back to the signature default
        if lookup_name in named and (value := named.pop(lookup_name)) is not Unset:
            path_params_dict[original_ph] = value
        elif (
            (param := sig.parameters.get(lookup_name))
            and param.default is not inspect.Parameter.empty
            and param.default is not Unset
        ):
            # Apply the path parameter's signature default when the caller omits it
            path_params_dict[original_ph] = param.default

    return path_params_dict, named


@cache
def get_signature_defaults(func: Callable[..., Any], path: str) -> dict[str, Any]:
    """Return a cached mapping of param name to default value for non-path body/query parameters.

    Excludes path parameters (exact and cleaned-name equivalents), VAR_KEYWORD/VAR_POSITIONAL
    params, params with no default, and params whose default is Unset.

    :param func: Original API function
    :param path: Endpoint path (used to derive path-param names to exclude)
    """
    path_param_names = get_path_param_names(path)
    return {
        name: param.default
        for name, param in inspect.signature(func).parameters.items()
        if name != "self"
        and name not in path_param_names
        and param.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
        and param.default is not inspect.Parameter.empty
        and param.default is not Unset
    }


def validate_path_and_params(
    endpoint_func: EndpointFunc[Any], *path_params: Any, raw_options: dict[str, Any] | None, **body_or_query_params: Any
) -> str:
    """Validate path parameters and body/query parameters for an endpoint function call, and returns completed
    endpoint path

    :param endpoint_func: Endpoint function obj
    :param path_params: Path variables to fill the endpoint
    :param raw_options: Raw request options passed to the httpx client
    :param body_or_query_params: Body or query parameters for the endpoint
    """
    endpoint = endpoint_func.endpoint
    if endpoint.is_deprecated:
        logger.warning(f"DEPRECATED: '{endpoint}' is deprecated")

    # Fill path variables
    completed_path = _complete_endpoint(endpoint, path_params)

    # Check if parameters used are expected for the endpoint. If not, it is an indication that the API function is
    # not up-to-date unless they are invalid parameters intentionally specified. We will log a warning message for this
    # case
    _check_params(endpoint, body_or_query_params, raw_options=raw_options)

    return completed_path


def is_json_request(
    endpoint: Endpoint[Any],
    params: dict[str, Any],
    raw_options: dict[str, Any],
    session_headers: dict[str, str],
) -> bool:
    """Check if the endpoint call requires a JSON request

    Endpoints that match either of the following criteria are considered as non JSON request
    - The endpoint model contains at least one File dataclass field
    - At least one parameter value is an instance of File
    - Content-Type request/session header was explicitly specified as anything other than application/json
    - The endpoint function is marked with @endpoint.content_type() with any value other than application/json
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
    endpoint: Endpoint[Any],
    endpoint_params: dict[str, Any],
    session_headers: dict[str, str],
    quiet: bool = False,
    use_query_string: bool = False,
    **raw_options: Any,
) -> dict[str, Any]:
    """Convert params passed to an endpoint function to ones for a low-level rest call function.
    Also set Content-Type header if needed

    :param endpoint: Endpoint obj
    :param endpoint_params: Params passed to an endpoint function call
    :param session_headers: Request client's session headers
    :param quiet: quiet flag passed to an endpoint function call
    :param use_query_string: Force sends parameters as query strings
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
        if param_value is Unset:
            # Unset means "not provided" — exclude the parameter from the request entirely.
            # An explicit Unset also suppresses a concrete signature default merged by the caller
            continue
        if param_name == "raw_options":
            for k, v in raw_options.items():
                rest_func_params[k] = v
        else:
            if field_obj := dataclass_fields.get(param_name):
                # Query/body routing and alias resolution follow the parameter's annotation,
                # independent of whether the runtime value matches the declared type. (This is a
                # negative-testing client that intentionally allows type-mismatched values.)
                if annotated_type := param_type_util.get_annotated_type(
                    field_obj.type, metadata_filter=["query", Alias, Query]
                ):
                    if isinstance(annotated_type, list | tuple):
                        # This field has more than one Annotated[] as a union. Pick the variant whose
                        # type matches the given value; if none match, fall back to the first.
                        matched = next(
                            (t for t in annotated_type if param_type_util.matches_type(param_value, t)), None
                        )
                        if matched is None:
                            matched = annotated_type[0]
                            logger.warning(
                                f"The field type of '{endpoint.model.__name__}.{param_name}' has more than 1 "
                                f"Annotated[] type, but the provided value's type matches none of them. The first "
                                f"annotated type will be used for this API call.\n"
                                f"- Defined field type: {field_obj.type}\n"
                                f"- Provided value type: {type(param_value)}"
                            )
                        annotated_type = matched

                    # Process alias name and query parameter
                    metadata = annotated_type.__metadata__
                    if alias_param := [x for x in metadata if isinstance(x, Alias)]:
                        assert len(alias_param) == 1
                        # Resolve the actual param name
                        param_name = alias_param[0].value

                    if param_type_util.is_query_param(annotated_type):
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
                        field_obj is not None
                        and param_type_util.is_type_of(field_obj.type, File)
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
        rest_func_params["json"] = json_
    if data:
        rest_func_params["data"] = data
    if query_params:
        rest_func_params["params"] = query_params
    if isinstance(files, MultipartFormData) and (file_data := files.to_dict()):
        rest_func_params["files"] = file_data

    # httpx will not automatically set Content-Type when `data` is a string or bytes.
    # Fall back to the endpoint's declared Content-Type in that case, unless the header is explicitly
    # set by the caller. Otherwise httpx handles Content-Type automatically.
    if (
        (rest_data := rest_func_params.get("data"))
        and isinstance(rest_data, str | bytes)
        and not specified_content_type_header
        and endpoint.content_type
    ):
        rest_func_params.setdefault("headers", {}).update({"Content-Type": endpoint.content_type})

    return rest_func_params


def _check_params(endpoint: Endpoint[Any], params: dict[str, Any], raw_options: dict[str, Any] | None = None) -> None:
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


def _complete_endpoint(endpoint: Endpoint[Any], path_params: tuple[str, ...]) -> str:
    """Complete endpoint path with given path variables

    :param endpoint: Endpoint obj
    :param path_params: Path variables to fill the endpoint
    """

    if path_placeholders := list(get_path_placeholders(endpoint.path)):
        if len(path_params) == len(path_placeholders):
            fmt = OrderedDict(zip(path_placeholders, path_params))
            return endpoint.path.format(**fmt)
        elif len(path_params) < len(path_placeholders):
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
        return endpoint.path


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
