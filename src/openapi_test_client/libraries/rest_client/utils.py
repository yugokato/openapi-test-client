import inspect
import json
import time
import urllib.parse
from copy import deepcopy
from functools import lru_cache, wraps
from http import HTTPStatus
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, Callable, Optional, ParamSpec, TypeVar, Union
from urllib.parse import parse_qs, urlparse

from requests import Session

from openapi_test_client.libraries.common.logging import get_logger

if TYPE_CHECKING:
    from .ext import PreparedRequestExt, ResponseExt, RestResponse
    from .rest_client import RestClient


P = ParamSpec("P")
RT = TypeVar("RT")

logger = get_logger(__name__)


TRUNCATE_LEN = 512


def generate_query_string(query_params: dict[str, Any]):
    """Returns a string containing the URL query string based on the passed dictionary

    :param query_params: A dictionary of key/value pairs that will be used in the API call
    """

    def convert_if_bool(val):
        """Convert boolean to lower string"""
        if isinstance(val, bool):
            return str(val).lower()
        else:
            return val

    query_string = "&".join(
        urllib.parse.urlencode({k: convert_if_bool(v)}, doseq=True) for (k, v) in query_params.items() if v is not None
    )
    return query_string


def process_request_body(body: Optional[bytes], hide_sensitive_values: bool = True, truncate_bytes: bool = False):
    """Process request body (PreparedRequest.body)"""
    if body:
        body = _decode_utf8(body)
        if isinstance(body, bytes):
            if truncate_bytes and len(body) > TRUNCATE_LEN:
                body = _truncate(body)
        else:
            try:
                body = json.loads(body)
            except (
                JSONDecodeError,
                UnicodeDecodeError,
            ):
                pass
            else:
                if hide_sensitive_values:
                    body = mask_sensitive_value(body)
    return body


def mask_sensitive_value(body: Any):
    """Mask a field value when a field name of the request body contains specific word"""
    if isinstance(body, dict):
        part_field_names_to_mask_value = [
            "password"
            # TODO: Add more if needed
        ]
        for k, v in body.items():
            if isinstance(v, dict):
                mask_sensitive_value(v)
            elif isinstance(v, list):
                for nested_obj in v:
                    mask_sensitive_value(nested_obj)
            elif isinstance(v, str) and any(part in k for part in part_field_names_to_mask_value):
                body[k] = "*" * len(v)
    return body


def process_response(
    response: Union["ResponseExt", "RestResponse"], prettify: bool = False
) -> str | bytes | dict[str, Any] | list[str | bytes | dict[str, Any]]:
    """Get json-encoded content of a response if possible, otherwise return content of the response"""
    from .ext import RestResponse

    if isinstance(response, RestResponse):
        response = response._response
    try:
        resp = response.json()
        if prettify:
            resp = json.dumps(resp, indent=4)
    except JSONDecodeError:
        resp = _decode_utf8(response.content)

    return resp


def parse_query_strings(url: str) -> Optional[dict[str, Any]]:
    """Parse query strings in the URL and return as a dictionary, if any"""
    q = urlparse(url)
    if q.query:
        query_params = parse_qs(q.query)
        return {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}


def get_response_reason(response: "ResponseExt") -> str:
    """Get response reason from the response. If the response doesn't have the value, we resolve it using HTTPStatus"""
    if response.reason:
        return response.reason
    else:
        try:
            return HTTPStatus(response.status_code).phrase
        except ValueError:
            return ""


def manage_content_type(f: Callable[P, RT]) -> Callable[P, RT]:
    """Set Content-Type: application/json header by default to a request whenever appropriate"""

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> RT:
        self: RestClient = args[0]
        session_headers = self.session.headers
        request_headers = kwargs.get("headers", {})
        headers = {**session_headers, **request_headers}
        has_content_type_header = "Content-Type" in [h.title() for h in list(headers.keys())]
        content_type_set = False
        if not has_content_type_header and (kwargs.get("json") or not any([kwargs.get("data"), kwargs.get("files")])):
            self.session.headers.update({"Content-Type": "application/json"})
            content_type_set = True
        try:
            return f(*args, **kwargs)
        finally:
            if content_type_set:
                self.session.headers.pop("Content-Type", None)

    return wrapper


def retry_on(*status_code_to_retry: int, num_retry: int = 1, retry_after: float = 5, safe_methods_only: bool = True):
    def decorator_with_args(f: Callable[P, RT]) -> Callable[P, RT]:
        """Retry the request if any of specified status code is returned"""

        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> RT:
            resp: ResponseExt | RestResponse = f(*args, **kwargs)
            if safe_methods_only and resp.request.method.upper() not in ["GET", "HEAD", "OPTION"]:
                return resp

            num_retried = 0
            while num_retried < num_retry:
                if resp.status_code in status_code_to_retry:
                    original_request: PreparedRequestExt = resp.request
                    copied_request = deepcopy(original_request)
                    logger.warning(
                        f"Received status code {resp.status_code}. Retrying in {retry_after} seconds...",
                        extra={
                            "status_code": resp.status_code,
                            "response": process_response(resp, prettify=True),
                            "request_id": original_request.request_id,
                        },
                    )
                    time.sleep(retry_after)
                    resp = f(*args, **kwargs)
                    original_request.retried = copied_request
                    num_retried += 1
                else:
                    break
            if (status_code := resp.status_code) in status_code_to_retry:
                text = f"{num_retry} times" if num_retry > 1 else "once"
                logger.warning(f"Retried {text} but the request still received status code {status_code}")
            return resp

        return wrapper

    return decorator_with_args


@lru_cache
def get_supported_request_parameters() -> list[str]:
    """Return a list of supported request parameters"""
    custom_parameters = ["quiet", "query"]
    requests_lib_params = inspect.signature(Session.request).parameters.keys()
    return [x for x in requests_lib_params if x != "self"] + custom_parameters


def _decode_utf8(obj: Any):
    """Decode bytes object with UTF-8, if possible"""
    if obj and isinstance(obj, bytes):
        try:
            obj = obj.decode("utf-8")
        except UnicodeDecodeError:
            # Binary file
            pass
    return obj


def _truncate(v: str | bytes) -> str | bytes:
    """Truncate value"""
    assert isinstance(v, (str, bytes))
    trunc_pos = int(TRUNCATE_LEN / 2)
    trunc_mark = "   ...TRUNCATED...   "
    if isinstance(v, bytes):
        trunc_mark = trunc_mark.encode("utf-8")
    else:
        trunc_mark = "\n\n" + trunc_mark + "\n\n"
    return v[:trunc_pos] + trunc_mark + v[-trunc_pos:]
