import json
import sys
from typing import TYPE_CHECKING, Callable, Union

from openapi_test_client.libraries.common.ansi_colors import ColorCodes, color
from openapi_test_client.libraries.common.logging import get_logger

from .ext import PreparedRequestExt, ResponseExt
from .utils import get_response_reason, parse_query_strings, process_request_body, process_response

if TYPE_CHECKING:
    from openapi_test_client.libraries.rest_client import RestClient


logger = get_logger(__name__)


def get_hooks(rest_client: "RestClient", quiet: bool) -> dict[str, list[Callable]]:
    """Get request/response hooks"""
    return {
        "request": [_hook_factory(_log_request, quiet)],
        "response": [
            _hook_factory(_log_response, rest_client.prettify_response_log, quiet),
            _hook_factory(_print_api_summary, rest_client.prettify_response_log, rest_client.log_headers, quiet),
        ],
    }


def _log_request(request: PreparedRequestExt, quiet: bool, **kwargs):
    """Log API request"""
    log_data = {
        "request_id": request.request_id,
        "request": f"{request.method.upper()} {request.url}",
        "method": request.method,
        "path": request.path_url,
        "payload": process_request_body(request.body),
        "request_headers": request.headers,
    }
    if not quiet:
        logger.info(f"request: {request.method} {request.url}", extra=log_data)


def _log_response(response: ResponseExt, prettify_response_log: bool, quiet: bool, *args, **kwargs):
    """Log API response"""
    request: PreparedRequestExt = response.request
    log_data = {
        "request_id": request.request_id,
        "request": f"{request.method.upper()} {request.url}",
        "method": request.method,
        "path": request.path_url,
        "status_code": response.status_code,
        "response_headers": response.headers,
        "response_time": response.elapsed.total_seconds(),
    }
    if kwargs.get("stream") and response.ok:
        log_data.update(response="N/A (streaming)")
    else:
        log_data.update(response=process_response(response, prettify=prettify_response_log))

    msg = f"response: {response.status_code}"
    if reason := get_response_reason(response):
        msg += f" ({reason})"

    if response.ok:
        if not quiet:
            logger.info(msg, extra=log_data)
    else:
        # Log response regardless of the "quiet" value
        logger.error(msg, extra=log_data)


def _print_api_summary(response: ResponseExt, prettify: bool, log_headers: bool, quiet: bool, *args, **kwargs):
    """Print API request/response summary to the console"""
    request: PreparedRequestExt = response.request
    if quiet:
        if not response.ok:
            # Print to the console regardless of the "quiet" value
            processed_resp = process_response(response, prettify=prettify)
            err = (
                f"request_id: {request.request_id}\n"
                f"request: {request.method} {request.url}\n"
                f"status_code: {response.status_code}\n"
                f"response:{processed_resp}\n"
            )
            sys.stdout.write(color(err, color_code=ColorCodes.RED))
            sys.stdout.flush()
    else:
        bullet = "-"
        summary = ""

        # request_id
        summary += color(f"{bullet} request_id: {request.request_id}\n", color_code=ColorCodes.CYAN)

        # method and url
        summary += color(f"{bullet} request: {request.method} {response.url}\n", color_code=ColorCodes.CYAN)

        # request headers
        if log_headers:
            summary += color(f"{bullet} request_headers: {request.headers}\n", color_code=ColorCodes.CYAN)

        # request payload and query parameters
        if query_strings := parse_query_strings(request.url):
            summary += color(f"{bullet} query params: {query_strings}\n", color_code=ColorCodes.CYAN)
        request_body = process_request_body(request.body, truncate_bytes=True)
        if request_body:
            try:
                payload = json.dumps(request_body)
            except TypeError:
                payload = request_body
            summary += color(f"{bullet} payload: {payload}\n", color_code=ColorCodes.CYAN)

        # status_code and reason
        status_color_code = ColorCodes.GREEN if response.ok else ColorCodes.RED
        summary += color(f"{bullet} status_code: ", color_code=ColorCodes.CYAN) + color(
            response.status_code, color_code=status_color_code
        )
        if reason := get_response_reason(response):
            summary += f" ({reason})"
        summary += "\n"

        # response
        if kwargs.get("stream") and response.ok:
            formatted_response = "N/A (streaming)"
        else:
            formatted_response = process_response(response, prettify=prettify)
        if not response.ok:
            formatted_response = color(formatted_response, color_code=ColorCodes.RED)
        if formatted_response is not None:
            summary += color(f"{bullet} response: ", color_code=ColorCodes.CYAN)
            summary += f"{formatted_response}\n"

        # response headers
        if log_headers:
            summary += color(f"{bullet} response_headers: {response.headers}\n", color_code=ColorCodes.CYAN)

        # response time
        summary += color(f"{bullet} response_time: {response.elapsed.total_seconds()}s\n", color_code=ColorCodes.CYAN)

        sys.stdout.write(summary)
        sys.stdout.flush()


def _hook_factory(hook_func: Callable, *hook_args, **hook_kwargs):
    """Dynamically create a hook with arguments"""

    def hook(hook_data: Union["PreparedRequestExt", "ResponseExt"], *request_args, **request_kwargs):
        return hook_func(hook_data, *hook_args, *request_args, **hook_kwargs, **request_kwargs)

    return hook
