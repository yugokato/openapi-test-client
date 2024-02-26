from typing import Any, Optional

import requests.utils
from requests.hooks import HOOKS

from openapi_test_client.libraries.common.logging import get_logger

from .ext import BearerAuth, PreparedRequestExt, RestResponse, SessionExt
from .hooks import get_hooks
from .utils import generate_query_string, manage_content_type

# Monkey patch PreparedRequest and Session
requests.models.PreparedRequest = PreparedRequestExt
requests.sessions.PreparedRequest = PreparedRequestExt
requests.Session = SessionExt

# Register a custom "request" hook event
HOOKS.append("request")


logger = get_logger(__name__)


class RestClient:
    """Rest API client"""

    def __init__(
        self,
        base_url: str,
        log_headers: bool = False,
        prettify_response_log: bool = True,
        timeout: int | float = 30,
        verify_ssl_certificates: bool = True,
    ):
        """
        :param base_url: API base url
        :param log_headers: Include request/response headers to the API summary logs
        :param prettify_response_log: Prettify response in the API summary logs
        :param timeout: Session timeout in seconds
        :param verify_ssl_certificates: Verify SSL Certificates
        """
        self.url_base = base_url
        self.session = SessionExt()
        self.timeout = timeout
        self.verify_certificates = verify_ssl_certificates
        self.log_headers = log_headers
        self.prettify_response_log = prettify_response_log

    def get(self, path: str, quiet: bool = False, **query_params) -> RestResponse:
        """Make a GET API request

        :param path: Endpoint path
        :param quiet: A flag to suppress API request/response log
        :param query_params: Query parameters
        """
        return self._get(path, query=query_params, quiet=quiet)

    def post(self, path: str, files: Optional[dict[str, Any]] = None, quiet: bool = False, **payload) -> RestResponse:
        """Make a POST API request

        :param path: Endpoint path
        :param files: File to upload
        :param quiet: A flag to suppress API request/response log
        :param payload: JSON payload
        """
        return self._post(path, json=payload, files=files, quiet=quiet)

    def delete(self, path: str, quiet: bool = False, **payload) -> RestResponse:
        """Make a DELETE API request

        :param path: Endpoint path
        :param quiet: A flag to suppress API request/response log
        :param payload: JSON payload
        """
        return self._delete(path, json=payload, quiet=quiet)

    def put(self, path: str, quiet: bool = False, **payload) -> RestResponse:
        """Make a PUT API request

        :param path: Endpoint path
        :param quiet: A flag to suppress API request/response log
        :param payload: JSON payload
        """
        return self._put(path, json=payload, quiet=quiet)

    def patch(self, path: str, quiet: bool = False, **payload) -> RestResponse:
        """Make a PATCH API request

        :param path: Endpoint path
        :param quiet: A flag to suppress API request/response log
        :param payload: JSON payload
        """
        return self._patch(path, json=payload, quiet=quiet)

    def options(self, path: str, quiet: bool = False, **query_params) -> RestResponse:
        """Make an OPTIONS API request

        :param path: Endpoint path
        :param quiet: A flag to suppress API request/response log
        :param query_params: Query parameters
        """
        return self._options(path, query=query_params, quiet=quiet)

    @manage_content_type
    def _get(
        self, path: str, query: Optional[dict[str, Any]] = None, quiet: bool = False, **requests_lib_options
    ) -> RestResponse:
        """Low-level function of get()

        :param path: Endpoint path
        :param query: Query parameters
        :param quiet: A flag to suppress API request/response log
        :param requests_lib_options: Any other parameters passed directly to the requests library
        """
        r = self.session.get(
            self._generate_url(path, query=query),
            timeout=(requests_lib_options.pop("timeout", self.timeout)),
            verify=(requests_lib_options.pop("verify", self.verify_certificates)),
            hooks=get_hooks(self, quiet),
            **requests_lib_options,
        )
        stream = requests_lib_options.get("stream", False)
        return RestResponse(r, is_stream=stream)

    @manage_content_type
    def _post(
        self,
        path: str,
        json: Optional[dict[str, Any] | list[Any]] = None,
        query: Optional[dict[str, Any]] = None,
        quiet: bool = False,
        **requests_lib_options,
    ) -> RestResponse:
        """Low-level function of post()

        :param path: Endpoint path
        :param json: JSON payload
        :param query: Query parameters
        :param quiet: A flag to suppress API request/response log
        :param requests_lib_options: Any other parameters passed directly to the requests library
        """
        r = self.session.post(
            self._generate_url(path, query=query),
            json=json,
            timeout=(requests_lib_options.pop("timeout", self.timeout)),
            verify=(requests_lib_options.pop("verify", self.verify_certificates)),
            hooks=get_hooks(self, quiet),
            **requests_lib_options,
        )
        return RestResponse(r)

    @manage_content_type
    def _delete(
        self,
        path: str,
        json: dict[str, Any] | list[Any] = None,
        query: Optional[dict[str, Any]] = None,
        quiet: bool = False,
        **requests_lib_options,
    ) -> RestResponse:
        """Low-level function of delete()

        :param path: Endpoint path
        :param json: JSON payload
        :param query: Query parameters
        :param quiet: A flag to suppress API request/response log
        :param requests_lib_options: Any other parameters passed directly to the requests library
        """
        r = self.session.delete(
            self._generate_url(path, query=query),
            json=json,
            timeout=(requests_lib_options.pop("timeout", self.timeout)),
            verify=(requests_lib_options.pop("verify", self.verify_certificates)),
            hooks=get_hooks(self, quiet),
            **requests_lib_options,
        )
        return RestResponse(r)

    @manage_content_type
    def _put(
        self,
        path: str,
        json: dict[str, Any] | list[Any] = None,
        query: Optional[dict[str, Any]] = None,
        quiet: bool = False,
        **requests_lib_options,
    ) -> RestResponse:
        """Low-level function of put()

        :param path: Endpoint path
        :param json: JSON payload
        :param query: Query parameters
        :param quiet: A flag to suppress API request/response log
        :param requests_lib_options: Any other parameters passed directly to the requests library
        """
        r = self.session.put(
            self._generate_url(path, query=query),
            json=json,
            timeout=(requests_lib_options.pop("timeout", self.timeout)),
            verify=(requests_lib_options.pop("verify", self.verify_certificates)),
            hooks=get_hooks(self, quiet),
            **requests_lib_options,
        )
        return RestResponse(r)

    @manage_content_type
    def _patch(
        self,
        path: str,
        json: dict[str, Any] | list[Any] = None,
        query: Optional[dict[str, Any]] = None,
        quiet: bool = False,
        **requests_lib_options,
    ) -> RestResponse:
        """Low-level function of patch()

        :param path: Endpoint path
        :param json: JSON payload
        :param query: Query parameters
        :param quiet: A flag to suppress API request/response log
        :param requests_lib_options: Any other parameters passed directly to the requests library
        """
        r = self.session.patch(
            self._generate_url(path, query=query),
            json=json,
            timeout=(requests_lib_options.pop("timeout", self.timeout)),
            verify=(requests_lib_options.pop("verify", self.verify_certificates)),
            hooks=get_hooks(self, quiet),
            **requests_lib_options,
        )
        return RestResponse(r)

    @manage_content_type
    def _options(
        self, path: str, query: Optional[dict[str, Any]] = None, quiet: bool = False, **requests_lib_options
    ) -> RestResponse:
        """Low-level function of options()

        :param path: Endpoint path
        :param query: Query parameters
        :param quiet: A flag to suppress API request/response log
        :param requests_lib_options: Any other parameters passed directly to the requests library
        """
        r = self.session.options(
            self._generate_url(path, query=query),
            timeout=(requests_lib_options.pop("timeout", self.timeout)),
            verify=(requests_lib_options.pop("verify", self.verify_certificates)),
            hooks=get_hooks(self, quiet),
            **requests_lib_options,
        )
        return RestResponse(r)

    def get_bearer_token(self) -> Optional[str]:
        """Get bear token in the current session"""
        if isinstance(self.session.auth, BearerAuth):
            return self.session.auth.token
        elif (
            authorization_header := self.session.headers.get("Authorization")
        ) and authorization_header.lower().startswith("bear "):
            return authorization_header.split(" ")[1]

    def set_bearer_token(self, token: str):
        """Set bear token to the current session"""
        self.session.auth = BearerAuth(token)

    def unset_bear_token(self):
        """Unset bear token from the current session"""
        self.session.auth = None

    def _generate_url(self, path: str, query: Optional[dict[str, Any]] = None):
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.url_base}{path}"
        if query:
            url += f"?{generate_query_string(query)}"
        return url
